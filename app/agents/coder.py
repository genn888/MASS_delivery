from __future__ import annotations
import ast
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from app.agents.base_agent import BaseAgent
from app.graph.state import GraphState, append_message
from app.tools.agent_tools import CHECK_TOOLS, READ_TOOLS, WRITE_TOOLS, build_tool_registry
from app.tools.file_tools import FileTool
from app.tools.test_tools import TestTool

@dataclass(slots=True)
class GeneratedFile:
    path: str
    content: str

@dataclass(slots=True)
class GenerationPayload:
    summary: str
    files: list[GeneratedFile]
    delete_paths: list[str]

class CoderAgent(BaseAgent):
    GENERATED_PROJECT_ROOT = 'generated_project'
    AGENTIC_MAX_TOOL_STEPS = 50
    PROMPT_MODULES = {'console': 'coder_console.txt', 'web': 'coder_web.txt', 'django': 'coder_django.txt', 'repair': 'coder_repair.txt', 'tests': 'coder_tests.txt'}

    def __init__(self, *args, file_tool: FileTool, test_tool: TestTool | None=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.file_tool = file_tool
        self.test_tool = test_tool

    def run(self, state: GraphState) -> GraphState:
        next_iteration = state.get('coding_iteration', 0) + 1
        self.logger.info('Generating implementation payload iteration %s', next_iteration)
        if state.get('use_agentic_tools'):
            return self._run_agentic(state, next_iteration)
        prompt = self._load_prompt_for_state(state, next_iteration)
        response_format = None
        if self.llm.capabilities.supports_json:
            response_format = {'type': 'json_object', 'mime_type': 'application/json'}
        context = {'user_task': state['user_task'], 'requirements': state.get('requirements', ''), 'architecture_plan': state.get('architecture_plan', '') if next_iteration == 1 else '', 'reviewer_feedback': state.get('reviewer_feedback', ''), 'validation_results': state.get('validation_results', {}), 'test_status': state.get('test_status', 'not_run'), 'coding_iteration': next_iteration, 'benchmark_name': state.get('benchmark_name', ''), 'benchmark_contract': state.get('benchmark_contract_compact', {}), 'skip_internal_tests': state.get('skip_internal_tests', False)}
        if next_iteration > 1:
            error_paths = self._extract_error_file_paths(state)
            if not error_paths:
                error_paths = self._extract_reviewer_feedback_file_paths(state)
            if error_paths:
                context['current_implementation'] = self._get_current_project_files(error_paths)
                context['implementation_context'] = 'focused_subset'
            else:
                context['current_implementation'] = self._get_current_project_files()
                context['implementation_context'] = 'full_project'
        try:
            payload, traces, raw_content = self.generate_parsed_payload_with_retries(state=state, role='coder', system_prompt=prompt, context=context, parser=self._parse_payload, response_format=response_format, retry_instruction="The previous coder response was empty or invalid JSON. Return exactly one valid JSON object now. The first character must be '{'. Include a non-empty summary and a non-empty files array with complete project files. Do not include analysis, markdown, code fences, or explanatory text outside the JSON.")
        except Exception as exc:
            if next_iteration <= 1 or not self._is_timeout_like_error(exc):
                raise
            fallback_context = dict(context)
            failure_digest = self._build_failure_digest(state)
            error_paths = self._extract_error_file_paths(state) or self._infer_failure_file_paths(failure_digest)
            if not error_paths:
                raise
            fallback_context['current_implementation'] = self._get_current_project_files(error_paths)
            fallback_context['implementation_context'] = 'targeted_failure_subset_after_timeout'
            fallback_context['failure_digest'] = failure_digest
            fallback_context['timeout_recovery_note'] = 'The previous coder request timed out or failed at provider level. Retry with this smaller, failure-localized context and patch only the necessary files.'
            payload, traces, raw_content = self.generate_parsed_payload_with_retries(state=state, role='coder', system_prompt=prompt, context=fallback_context, parser=self._parse_payload, response_format=response_format, retry_instruction="The previous coder response was empty or invalid JSON. Return exactly one valid JSON object now. The first character must be '{'. Include a non-empty summary and a non-empty files array with complete project files. Do not include analysis, markdown, code fences, or explanatory text outside the JSON.")
        if next_iteration == 1:
            self.file_tool.remove_dir(self.GENERATED_PROJECT_ROOT)
        deleted_paths = [self._target_delete_path(relative_path) for relative_path in payload.delete_paths]
        for relative_path in deleted_paths:
            self.file_tool.remove_path(relative_path)
        files_to_write = [(self._target_path(generated_file.path), generated_file.content) for generated_file in payload.files]
        written_paths = self.file_tool.write_files(files_to_write)
        lint_results = self.file_tool.validate_python_syntax([relative_path for relative_path, _ in files_to_write])
        framework_results = self.file_tool.validate_framework_sanity(self.GENERATED_PROJECT_ROOT)
        lint_results = self._merge_validation_results(lint_results, framework_results)
        artifact_path = Path('artifacts') / 'implementation_summary.md'
        summary_with_files = self._build_summary(payload, lint_results)
        self.file_tool.write_text(str(artifact_path), summary_with_files)
        touched = list(state.get('files_touched', []))
        touched.extend((str(self.file_tool.resolve_path(path)) for path in deleted_paths))
        touched.extend((str(path) for path in written_paths))
        touched.append(str(self.file_tool.resolve_path(str(artifact_path))))
        return {'coding_iteration': next_iteration, 'implementation_summary': summary_with_files, 'lint_results': lint_results, 'artifacts': {**state.get('artifacts', {}), 'implementation_summary': str(self.file_tool.resolve_path(str(artifact_path))), 'generated_files': [str(path) for path in written_paths], 'generated_root': str(self.file_tool.resolve_path(self.GENERATED_PROJECT_ROOT)), 'lint_results': lint_results}, 'files_touched': touched, 'messages': append_message(state, 'coder', summary_with_files), 'traces': traces}

    def _run_agentic(self, state: GraphState, next_iteration: int) -> GraphState:
        """Agentic implementation: the model builds/repairs the project via tools."""
        self.logger.info('Coder: agentic tool loop enabled (iteration %s)', next_iteration)
        if next_iteration == 1:
            self.file_tool.remove_dir(self.GENERATED_PROJECT_ROOT)
        prompt = self._load_agentic_prompt_for_state(state, next_iteration)
        registry = build_tool_registry(file_tool=self.file_tool, test_tool=self.test_tool, project_root_rel=self.GENERATED_PROJECT_ROOT)
        context: dict[str, Any] = {'user_task': state['user_task'], 'requirements': state.get('requirements', ''), 'architecture_plan': state.get('architecture_plan', '') if next_iteration == 1 else '', 'reviewer_feedback': state.get('reviewer_feedback', ''), 'test_status': state.get('test_status', 'not_run'), 'coding_iteration': next_iteration, 'benchmark_name': state.get('benchmark_name', ''), 'benchmark_contract': state.get('benchmark_contract_compact', {}), 'skip_internal_tests': state.get('skip_internal_tests', False)}
        if next_iteration > 1:
            context['failure_digest'] = self._build_failure_digest(state)
            context['repair_instruction'] = 'Repair the EXISTING project. Use list_files/read_file/grep to inspect the current files and the failures above, then write_file only the files that need changes.'
        content, traces = self.run_tool_loop(state=state, role='coder', system_prompt=prompt, context=context, registry=registry, tool_names=READ_TOOLS + WRITE_TOOLS + CHECK_TOOLS, max_steps=self.AGENTIC_MAX_TOOL_STEPS)
        ignored_dirs = {'__pycache__', '.pytest_cache', '.git', '.mypy_cache', 'node_modules'}
        root = self.file_tool.resolve_path(self.GENERATED_PROJECT_ROOT)
        written_files = [p for p in sorted(root.rglob('*')) if p.is_file() and (not set(p.parts) & ignored_dirs)] if root.exists() else []
        py_rel = [str(p.relative_to(self.file_tool.workspace)) for p in written_files if p.suffix == '.py']
        lint_results = self.file_tool.validate_python_syntax(py_rel)
        framework_results = self.file_tool.validate_framework_sanity(self.GENERATED_PROJECT_ROOT)
        lint_results = self._merge_validation_results(lint_results, framework_results)
        summary = self._build_agentic_summary(content, written_files, root, lint_results)
        artifact_path = Path('artifacts') / 'implementation_summary.md'
        self.file_tool.write_text(str(artifact_path), summary)
        touched = list(state.get('files_touched', []))
        touched.extend((str(p) for p in written_files))
        touched.append(str(self.file_tool.resolve_path(str(artifact_path))))
        return {'coding_iteration': next_iteration, 'implementation_summary': summary, 'lint_results': lint_results, 'artifacts': {**state.get('artifacts', {}), 'implementation_summary': str(self.file_tool.resolve_path(str(artifact_path))), 'generated_files': [str(p) for p in written_files], 'generated_root': str(self.file_tool.resolve_path(self.GENERATED_PROJECT_ROOT)), 'lint_results': lint_results}, 'files_touched': touched, 'messages': append_message(state, 'coder', summary), 'traces': traces}

    @staticmethod
    def _build_agentic_summary(content: str, written_files: list[Path], root: Path, lint_results: dict[str, Any]) -> str:
        file_lines = '\n'.join((f'- `{p.relative_to(root).as_posix()}`' for p in written_files))
        syntax_status = 'passed' if lint_results.get('success') else 'failed'
        error_lines = ''
        if not lint_results.get('success'):
            error_lines = '\n\nValidation errors:\n' + '\n'.join((f"- `{error.get('path')}`: {error.get('message')}" for error in lint_results.get('errors', []) if isinstance(error, dict)))
        body = content.strip() or 'Agentic implementation completed.'
        return f"{body}\n\nFiles in project:\n{file_lines or '- (none)'}\n\nSyntax/framework validation: {syntax_status}{error_lines}"

    def _select_prompt_modules(self, state: GraphState, next_iteration: int) -> list[str]:
        contract = state.get('benchmark_contract_compact') or {}
        project_type = str(contract.get('project_type') or '').strip().lower()
        technical_stack = str(contract.get('technical_stack') or '').strip().lower()
        reviewer_feedback = str(state.get('reviewer_feedback') or '').lower()
        modules: list[str] = []
        if project_type in ('console', 'batch'):
            modules.append('console')
        if project_type == 'website':
            modules.append('web')
        if 'django' in technical_stack or self.file_tool.resolve_path(f'{self.GENERATED_PROJECT_ROOT}/manage.py').exists():
            modules.append('django')
        if next_iteration > 1:
            modules.append('repair')
        if 'local_test_bug' in reviewer_feedback:
            modules.append('tests')
        return modules

    def _compose_prompt(self, base_text: str, modules: list[str]) -> str:
        prompt_parts = [base_text]
        for module in modules:
            module_path = self.prompt_path.with_name(self.PROMPT_MODULES[module])
            prompt_parts.append(module_path.read_text(encoding='utf-8').strip())
        return '\n\n'.join(prompt_parts)

    def _load_prompt_for_state(self, state: GraphState, next_iteration: int) -> str:
        return self._compose_prompt(self.load_prompt(), self._select_prompt_modules(state, next_iteration))

    def _load_agentic_prompt_for_state(self, state: GraphState, next_iteration: int) -> str:
        base = self.prompt_path.with_name('coder_agentic.txt').read_text(encoding='utf-8').strip()
        return self._compose_prompt(base, self._select_prompt_modules(state, next_iteration))

    def _get_current_project_files(self, error_paths: list[str]=None) -> str:
        """Return the subset of project files the coder needs."""
        if error_paths:
            return self.file_tool.get_focused_snapshot(project_root_rel=self.GENERATED_PROJECT_ROOT, error_paths=error_paths)
        else:
            return self.file_tool.get_full_snapshot(self.GENERATED_PROJECT_ROOT)

    def _extract_error_file_paths(self, state: GraphState) -> list[str]:
        results = state.get('lint_results', {})
        errors = results.get('errors', [])
        paths = set()
        for error in errors:
            if isinstance(error, dict) and error.get('path'):
                paths.add(error['path'])
            if isinstance(error, dict) and error.get('message'):
                paths.update(self._extract_paths_from_failure_text(str(error['message'])))
        for key in ('dynamic_test_results', 'browser_test_results'):
            test_results = state.get(key, {})
            if isinstance(test_results, dict):
                paths.update(self._extract_paths_from_failure_text(str(test_results.get('stderr') or '')))
                paths.update(self._extract_paths_from_failure_text(str(test_results.get('summary') or '')))
        return sorted(list(paths))

    def _extract_reviewer_feedback_file_paths(self, state: GraphState) -> list[str]:
        feedback = str(state.get('reviewer_feedback') or '')
        if not feedback:
            return []
        root = self.file_tool.resolve_path(self.GENERATED_PROJECT_ROOT)
        paths: set[str] = set()
        for match in re.findall('(?:generated_project/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\\.(?:py|html|js|css|json|md|txt)', feedback):
            relative_path = match.removeprefix(f'{self.GENERATED_PROJECT_ROOT}/')
            candidate = root / relative_path
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.is_file() and '__pycache__' not in candidate.parts:
                paths.add(f'{self.GENERATED_PROJECT_ROOT}/{relative_path}')
        return sorted(paths)

    @staticmethod
    def _extract_paths_from_failure_text(text: str) -> set[str]:
        if not text:
            return set()
        paths: set[str] = set()
        marker = f'{CoderAgent.GENERATED_PROJECT_ROOT}/'
        for match in re.finditer('File "([^"]+)"', text):
            raw_path = match.group(1)
            if marker in raw_path:
                rel = raw_path.split(marker, 1)[1]
                if rel and (not rel.startswith('__pycache__/')):
                    paths.add(f'{CoderAgent.GENERATED_PROJECT_ROOT}/{rel}')
        for dotted in re.findall("from '([A-Za-z_][\\w]*(?:\\.[A-Za-z_][\\w]*)*)'", text):
            parts = dotted.split('.')
            if len(parts) >= 2:
                paths.add(str(Path(CoderAgent.GENERATED_PROJECT_ROOT, *parts).with_suffix('.py')))
        return paths

    def _build_failure_digest(self, state: GraphState) -> str:
        """Build a small, file-localization oriented digest for repair iterations."""
        chunks: list[str] = []
        reviewer_feedback = str(state.get('reviewer_feedback') or '').strip()
        if reviewer_feedback:
            chunks.append(f'reviewer_feedback:\n{reviewer_feedback[:3000]}')
        for label, key in (('dynamic_tests', 'dynamic_test_results'), ('browser_tests', 'browser_test_results'), ('static_analysis', 'static_analysis_results')):
            result = state.get(key, {})
            if not isinstance(result, dict) or not result:
                continue
            compact = {'success': result.get('success'), 'returncode': result.get('returncode'), 'summary': result.get('summary'), 'failure_summary': result.get('failure_summary', {})}
            chunks.append(f'{label}:\n{json.dumps(compact, indent=2, ensure_ascii=True)[:4000]}')
        return '\n\n'.join(chunks)[:9000]

    def _infer_failure_file_paths(self, failure_digest: str) -> list[str]:
        """Infer likely application files from dynamic/Selenium failures."""
        if not failure_digest:
            return []
        root = self.file_tool.resolve_path(self.GENERATED_PROJECT_ROOT)
        if not root.exists():
            return []
        lowered = failure_digest.lower()
        candidates: set[Path] = set()
        selector_tokens = set(re.findall('(?:id|name|class)[=:\\s\\"\']+([A-Za-z_][\\w:-]{2,})', failure_digest))
        selector_tokens.update(re.findall('By\\.(?:ID|NAME|CLASS_NAME),\\s*[\'\\"]([^\'\\"]+)[\'\\"]', failure_digest))
        selector_tokens.update(re.findall('\\[id=\\\\?\\"([^\\"\\\\]+)\\\\?\\"\\]', failure_digest))
        for path in root.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or 'tests' in path.parts:
                continue
            if path.suffix not in {'.py', '.html', '.js', '.css'}:
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            text_lower = text.lower()
            rel = path.relative_to(root)
            if any((token and token in text for token in selector_tokens)):
                candidates.add(rel)
                continue
            if any((word in lowered and word in text_lower for word in ('redirect', 'datetime', 'date/time', 'form', 'selenium'))):
                if path.suffix in {'.py', '.html'}:
                    candidates.add(rel)
        important_names = {'views.py', 'forms.py', 'models.py', 'urls.py', 'settings.py', 'calendar.html', 'home.html', 'events.html', 'event_detail.html', 'event_edit.html'}
        for path in root.rglob('*'):
            if path.is_file() and path.name in important_names and ('__pycache__' not in path.parts):
                if path.name.lower().replace('.py', '').replace('.html', '') in lowered:
                    candidates.add(path.relative_to(root))
        if any((word in lowered for word in ('datetime-local', 'date/time', 'datetime', 'selenium'))):
            for path in root.rglob('*'):
                if path.is_file() and path.name in {'forms.py', 'views.py'}:
                    candidates.add(path.relative_to(root))
        return [f'{self.GENERATED_PROJECT_ROOT}/{path.as_posix()}' for path in sorted(candidates)[:12]]

    @staticmethod
    def _is_timeout_like_error(exc: Exception) -> bool:
        name = exc.__class__.__name__.lower()
        text = str(exc).lower()
        return 'timeout' in name or 'timeout' in text or 'timed out' in text or ('api' in name and 'connection' in name) or ('rate' in name and 'limit' in name)

    def _parse_payload(self, content: str) -> GenerationPayload:
        normalized = content.strip()
        if normalized.startswith('```'):
            normalized = self._strip_code_fence(normalized)
        data = self._load_payload_json(normalized)
        files_raw = data.get('files', [])
        if not isinstance(files_raw, list) or not files_raw:
            raise ValueError("Coder payload must include a non-empty 'files' list.")
        files: list[GeneratedFile] = []
        for item in files_raw:
            path = item.get('path')
            file_content = item.get('content')
            if not isinstance(path, str) or not path.strip():
                raise ValueError("Each generated file must include a non-empty string 'path'.")
            if not isinstance(file_content, str):
                raise ValueError(f"Generated file '{path}' must include string 'content'.")
            files.append(GeneratedFile(path=path, content=file_content))
        summary = data.get('summary')
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("Coder payload must include a non-empty string 'summary'.")
        delete_paths_raw = data.get('delete_paths', [])
        if not isinstance(delete_paths_raw, list):
            raise ValueError("Coder payload 'delete_paths' must be a list when provided.")
        delete_paths: list[str] = []
        for relative_path in delete_paths_raw:
            if not isinstance(relative_path, str):
                raise ValueError("Each coder 'delete_paths' entry must be a string.")
            delete_paths.append(self._normalize_delete_path(relative_path))
        return GenerationPayload(summary=summary.strip(), files=files, delete_paths=delete_paths)

    @staticmethod
    def _load_payload_json(normalized: str) -> dict[str, Any]:
        try:
            loaded = json.loads(normalized)
            if not isinstance(loaded, dict):
                raise ValueError('Coder payload must be a JSON object.')
            return loaded
        except json.JSONDecodeError:
            repaired = CoderAgent._repair_common_json_issues(normalized)
            loaded = json.loads(repaired)
            if not isinstance(loaded, dict):
                raise ValueError('Coder payload must be a JSON object.')
            return loaded

    @staticmethod
    def _repair_common_json_issues(text: str) -> str:
        repaired = text.strip()
        first_brace = repaired.find('{')
        last_brace = repaired.rfind('}')
        if first_brace != -1 and last_brace != -1 and (last_brace > first_brace):
            repaired = repaired[first_brace:last_brace + 1]
        repaired = re.sub('(?<=")\\s*\\}\\s*\\},\\s*\\{', '\n    },\n    {', repaired)
        repaired = re.sub('(?<=")\\s*\\}\\s*,\\s*\\{', '\n    },\n    {', repaired)
        repaired = re.sub('(?<=")\\s*,\\s*\\{', '\n    },\n    {', repaired)
        previous = None
        while previous != repaired:
            previous = repaired
            repaired = repaired.replace(',\n]', '\n]')
            repaired = repaired.replace(',\n}', '\n}')
            repaired = repaired.replace(', ]', ' ]')
            repaired = repaired.replace(', }', ' }')
        return repaired

    @staticmethod
    def _strip_code_fence(content: str) -> str:
        lines = content.splitlines()
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].startswith('```'):
            lines = lines[:-1]
        return '\n'.join(lines).strip()

    @staticmethod
    def _build_summary(payload: GenerationPayload, lint_results: dict[str, Any]) -> str:
        file_lines = '\n'.join((f'- `{generated_file.path}`' for generated_file in payload.files))
        deleted_lines = '\n'.join((f'- `{path}`' for path in payload.delete_paths))
        deleted_section = f'\n\nDeleted paths:\n{deleted_lines}' if deleted_lines else ''
        syntax_status = 'passed' if lint_results.get('success') else 'failed'
        error_lines = ''
        if not lint_results.get('success'):
            rendered = '\n'.join((f"- `{error['path']}`: {error['message']}" for error in lint_results.get('errors', []) if isinstance(error, dict)))
            error_lines = f'\n\nSyntax validation errors:\n{rendered}'
        return f'{payload.summary.strip()}\n\nWritten files:\n{file_lines}{deleted_section}\n\nSyntax validation: {syntax_status}{error_lines}'

    @staticmethod
    def _merge_validation_results(syntax_results: dict[str, Any], framework_results: dict[str, Any]) -> dict[str, Any]:
        checked_files = list(syntax_results.get('checked_files', []))
        checked_files.extend((path for path in framework_results.get('checked_files', []) if path not in checked_files))
        errors = list(syntax_results.get('errors', []))
        errors.extend(framework_results.get('errors', []))
        return {'checked_files': checked_files, 'success': not errors, 'errors': errors}

    @classmethod
    def _target_path(cls, relative_path: str) -> str:
        normalized = relative_path.strip().lstrip('/\\')
        return str(Path(cls.GENERATED_PROJECT_ROOT) / normalized)

    @classmethod
    def _normalize_delete_path(cls, relative_path: str) -> str:
        raw = relative_path.strip().replace('\\', '/').strip('/')
        parts = raw.split('/')
        if not raw or relative_path.strip().startswith(('/', '\\')) or re.match('^[A-Za-z]:', relative_path.strip()) or any((part in {'', '.', '..'} for part in parts)):
            raise ValueError('Coder delete paths must be non-empty relative paths inside generated_project.')
        if parts[0] == cls.GENERATED_PROJECT_ROOT:
            parts = parts[1:]
        if not parts:
            raise ValueError('Coder cannot delete the generated project root.')
        return '/'.join(parts)

    @classmethod
    def _target_delete_path(cls, relative_path: str) -> str:
        normalized = cls._normalize_delete_path(relative_path)
        return str(Path(cls.GENERATED_PROJECT_ROOT, normalized))