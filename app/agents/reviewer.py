from __future__ import annotations
import re
from pathlib import Path
from app.agents.base_agent import BaseAgent
from app.agents.review_decision import parse_review_decision
from app.graph.state import GraphState, append_message
from app.tools.agent_tools import READ_TOOLS, build_tool_registry
from app.tools.file_tools import FileTool

class ReviewerAgent(BaseAgent):
    GENERATED_PROJECT_ROOT = 'generated_project'
    AGENTIC_MAX_TOOL_STEPS = 15
    PROMPT_MODULES = {'tests': 'reviewer_tests.txt', 'console': 'reviewer_console.txt', 'web': 'reviewer_web.txt', 'django': 'reviewer_django.txt'}

    def __init__(self, *args, file_tool: FileTool, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.file_tool = file_tool

    def run(self, state: GraphState) -> GraphState:
        if state.get('coding_iteration', 0) >= state.get('max_coding_iterations', 0):
            self.logger.info('Reviewer: skipping final review because coding iterations are exhausted (%s/%s)', state.get('coding_iteration', 0), state.get('max_coding_iterations', 0))
            return {'review_status': state.get('review_status', 'changes_requested'), 'reviewer_feedback': state.get('reviewer_feedback', '')}
        validation_status = state.get('validation_status', 'passed')
        validation_results = state.get('validation_results', {})
        lint_results = state.get('lint_results', {})
        lint_failed = bool(lint_results) and (not lint_results.get('success', True))
        static_analysis_results = state.get('static_analysis_results', {})
        dynamic_test_results = state.get('dynamic_test_results', {})
        browser_test_results = state.get('browser_test_results', {})
        analysis_failed = lint_failed or (bool(static_analysis_results) and (not static_analysis_results.get('success', True)))
        mode = 'analysis_fix_advisor' if analysis_failed or validation_status == 'changes_requested' else 'quality_review'
        self.logger.info('Reviewer: running in mode=%s', mode)
        prompt = self._load_prompt_for_state(state)
        review_context = {'mode': mode, 'validation_status': validation_status, 'validation_results': validation_results, 'static_analysis_results': self._compact_static_results(static_analysis_results), 'dynamic_test_results': self._compact_test_results(dynamic_test_results), 'browser_test_results': self._compact_test_results(browser_test_results), 'implementation_summary': state.get('implementation_summary', ''), 'architecture_plan': '' if mode == 'analysis_fix_advisor' else state.get('architecture_plan', ''), 'lint_results': lint_results, 'coding_iteration': state.get('coding_iteration', 0), 'max_coding_iterations': state.get('max_coding_iterations', 0), 'benchmark_name': state.get('benchmark_name', ''), 'benchmark_contract': state.get('benchmark_contract_compact', {})}
        if state.get('use_agentic_tools'):
            self.logger.info('Reviewer: agentic tool loop enabled')
            registry = build_tool_registry(file_tool=self.file_tool, project_root_rel=self.GENERATED_PROJECT_ROOT)
            agentic_context = {**review_context, 'project_inspection': f"Inspect the generated project yourself with the tools before deciding. The project root is '{self.GENERATED_PROJECT_ROOT}'."}
            content, traces = self.run_tool_loop(state=state, role='reviewer', system_prompt=self._augment_prompt_for_tools(prompt), context=agentic_context, registry=registry, tool_names=READ_TOOLS, max_steps=self.AGENTIC_MAX_TOOL_STEPS)
        else:
            if mode == 'analysis_fix_advisor':
                error_paths = self._extract_error_file_paths(state)
                current_implementation = self.file_tool.get_focused_snapshot(project_root_rel=self.GENERATED_PROJECT_ROOT, error_paths=error_paths, excluded_path_patterns=('tests/**',))
            else:
                current_implementation = self.file_tool.get_focused_snapshot(project_root_rel=self.GENERATED_PROJECT_ROOT, touched_paths=state.get('files_touched', []), excluded_path_patterns=('tests/**',))
            content, traces = self.generate_text_with_trace(state=state, role='reviewer', system_prompt=prompt, context={**review_context, 'current_implementation': current_implementation})
        if mode == 'analysis_fix_advisor':
            status = 'changes_requested'
        else:
            status = parse_review_decision(content)
        return {'review_status': status, 'reviewer_feedback': content, 'messages': append_message(state, 'reviewer', content), 'traces': traces}

    def _load_prompt_for_state(self, state: GraphState) -> str:
        contract = state.get('benchmark_contract_compact') or {}
        project_type = str(contract.get('project_type') or '').strip().lower()
        technical_stack = str(contract.get('technical_stack') or '').strip().lower()
        modules = ['tests']
        if project_type in ('console', 'batch'):
            modules.append('console')
        if project_type == 'website':
            modules.append('web')
        if 'django' in technical_stack or self.file_tool.resolve_path(f'{self.GENERATED_PROJECT_ROOT}/manage.py').exists():
            modules.append('django')
        prompt_parts = [self.load_prompt()]
        for module in modules:
            module_path = self.prompt_path.with_name(self.PROMPT_MODULES[module])
            prompt_parts.append(module_path.read_text(encoding='utf-8').strip())
        return '\n\n'.join(prompt_parts)

    @staticmethod
    def _augment_prompt_for_tools(prompt: str) -> str:
        return prompt + '\n\n## Tool-based inspection\nYou can call tools to inspect the generated project before deciding:\n- `list_files` (optionally under a subdirectory) to see the file tree\n- `read_file` (by path relative to the project root) to read a file\n- `grep` (regex) to locate selectors, routes, imports, or definitions\nRead the implementation files that matter for the results provided, then stop calling tools and return your review in the required format, including the explicit decision keyword.'

    @staticmethod
    def _extract_error_file_paths(state: GraphState) -> list[str]:
        paths: list[str] = []
        for error in state.get('lint_results', {}).get('errors', []):
            if isinstance(error, dict) and error.get('path'):
                paths.append(error['path'])
            if isinstance(error, dict) and error.get('message'):
                paths.extend(ReviewerAgent._extract_paths_from_failure_text(str(error['message'])))
        for issue in state.get('validation_results', {}).get('issues', []):
            if isinstance(issue, dict) and issue.get('file'):
                paths.append(issue['file'])
        for hint in state.get('validation_results', {}).get('fix_hints', []):
            if isinstance(hint, dict) and hint.get('target'):
                paths.append(hint['target'])
        for issue in state.get('static_analysis_results', {}).get('issues', []):
            if isinstance(issue, dict) and issue.get('file'):
                paths.append(f"{ReviewerAgent.GENERATED_PROJECT_ROOT}/{issue['file']}")
        for hint in state.get('static_analysis_results', {}).get('fix_hints', []):
            if isinstance(hint, dict) and hint.get('target'):
                paths.append(f"{ReviewerAgent.GENERATED_PROJECT_ROOT}/{hint['target']}")
        for key in ('dynamic_test_results', 'browser_test_results'):
            results = state.get(key, {})
            if isinstance(results, dict):
                paths.extend(ReviewerAgent._extract_paths_from_failure_text(str(results.get('stderr') or '')))
                paths.extend(ReviewerAgent._extract_paths_from_failure_text(str(results.get('stdout') or '')))
                paths.extend(ReviewerAgent._extract_paths_from_failure_text(str(results.get('summary') or '')))
                paths.extend(ReviewerAgent._extract_paths_from_failure_text(str(results.get('failure_summary') or '')))
                for generated_test in results.get('generated_tests') or []:
                    normalized = ReviewerAgent._normalize_project_path(str(generated_test))
                    if normalized:
                        paths.append(normalized)
        return list(set(paths))

    @staticmethod
    def _extract_paths_from_failure_text(text: str) -> list[str]:
        if not text:
            return []
        paths: set[str] = set()
        for match in re.finditer('File "([^"]+)"', text):
            normalized = ReviewerAgent._normalize_project_path(match.group(1))
            if normalized:
                paths.add(normalized)
        for raw_path in re.findall('(?<![\\w/])((?:tests/)?[A-Za-z_][\\w./-]*\\.py)(?::\\d+)?', text):
            normalized = ReviewerAgent._normalize_project_path(raw_path)
            if normalized:
                paths.add(normalized)
        for dotted in re.findall("from '([A-Za-z_][\\w]*(?:\\.[A-Za-z_][\\w]*)*)'", text):
            parts = dotted.split('.')
            if len(parts) >= 2:
                paths.add(str(Path(ReviewerAgent.GENERATED_PROJECT_ROOT, *parts).with_suffix('.py')))
        return sorted(paths)

    @staticmethod
    def _normalize_project_path(raw_path: str) -> str | None:
        if not raw_path:
            return None
        marker = f'{ReviewerAgent.GENERATED_PROJECT_ROOT}/'
        normalized = raw_path.replace('\\', '/')
        if marker in normalized:
            normalized = normalized.split(marker, 1)[1]
        normalized = normalized.lstrip('./')
        if not normalized or normalized.startswith('__pycache__/') or (not normalized.endswith('.py')):
            return None
        return f'{ReviewerAgent.GENERATED_PROJECT_ROOT}/{normalized}'

    @staticmethod
    def _compact_static_results(results: dict) -> dict:
        if not isinstance(results, dict):
            return {}
        return {'success': results.get('success'), 'summary': results.get('summary'), 'issues': list(results.get('issues', []))[:12], 'fix_hints': list(results.get('fix_hints', []))[:12]}

    @staticmethod
    def _compact_test_results(results: dict) -> dict:
        if not isinstance(results, dict):
            return {}
        failure_summary = results.get('failure_summary', {})
        if isinstance(failure_summary, dict):
            failures = []
            for failure in list(failure_summary.get('failures', []))[:4]:
                if isinstance(failure, dict):
                    failures.append({'title': str(failure.get('title') or '')[:180], 'details': str(failure.get('details') or '')[:500], 'kind': failure.get('kind'), 'path': failure.get('path'), 'message': str(failure.get('message') or '')[:500]})
                else:
                    failures.append(str(failure)[:500])
            failure_summary = {'status': failure_summary.get('status'), 'summary': str(failure_summary.get('summary') or '')[:500], 'failures': failures, 'truncated': failure_summary.get('truncated'), 'kind': failure_summary.get('kind')}
        return {'success': results.get('success'), 'returncode': results.get('returncode'), 'no_tests_collected': results.get('no_tests_collected'), 'summary': str(results.get('summary') or '')[:1000], 'failure_summary': failure_summary, 'generated_tests': list(results.get('generated_tests', []))[:8], 'stderr_excerpt': str(results.get('stderr') or '')[:750], 'stdout_excerpt': str(results.get('stdout') or '')[:750]}