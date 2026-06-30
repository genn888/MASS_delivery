from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from app.agents.base_agent import BaseAgent
from app.graph.state import GraphState, append_message
from app.tools.file_tools import FileTool
from app.tools.test_tools import TestTool

@dataclass(slots=True)
class GeneratedTestFile:
    path: str
    content: str

@dataclass(slots=True)
class DynamicTestPayload:
    summary: str
    files: list[GeneratedTestFile]

class TestWriterAgent(BaseAgent):
    __test__ = False
    GENERATED_PROJECT_ROOT = 'generated_project'

    def __init__(self, *args, file_tool: FileTool, test_tool: TestTool, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.file_tool = file_tool
        self.test_tool = test_tool

    def run(self, state: GraphState) -> GraphState:
        self.logger.info('Generating and running dynamic tests')
        prompt = self.load_prompt()
        generated_root = state.get('artifacts', {}).get('generated_root')
        if not generated_root:
            result = {'success': False, 'returncode': 1, 'stdout': '', 'stderr': 'Generated project root is missing before dynamic testing.', 'no_tests_collected': True, 'generated_tests': []}
            summary = 'Dynamic test analysis failed: generated project root is missing.'
            return {'dynamic_test_results': result, 'test_results': result, 'test_status': 'failed_bug', 'messages': append_message(state, 'test_writer', summary), 'artifacts': {**state.get('artifacts', {}), 'dynamic_test_results': result}}
        django_check = self.test_tool.run_django_check(Path(generated_root))
        if not django_check.get('success', True):
            result = {**django_check, 'no_tests_collected': False, 'generated_tests': [], 'summary': 'Django sanity check failed before generated dynamic tests were written.', 'failure_summary': {**django_check.get('failure_summary', {}), 'kind': 'django_manage_check_failed'}}
            summary = self._render_summary('Django sanity check failed before generated dynamic tests were written.', result)
            artifact_path = self.file_tool.write_text('artifacts/dynamic_test_summary.md', summary)
            return {'dynamic_test_results': result, 'test_results': result, 'test_status': 'failed_bug', 'messages': append_message(state, 'test_writer', summary), 'artifacts': {**state.get('artifacts', {}), 'dynamic_test_results': result, 'dynamic_test_summary': str(artifact_path), 'django_health_check': django_check}, 'files_touched': list(state.get('files_touched', [])) + [str(artifact_path)]}
        current_implementation = self.file_tool.get_focused_snapshot(project_root_rel=self.GENERATED_PROJECT_ROOT, touched_paths=state.get('files_touched', []), max_total_files=25)
        generation_context = {'user_task': state['user_task'], 'requirements': state.get('requirements', ''), 'architecture_plan': state.get('architecture_plan', ''), 'implementation_summary': state.get('implementation_summary', ''), 'static_analysis_results': state.get('static_analysis_results', {}), 'django_health_check': django_check, 'current_implementation': current_implementation, 'benchmark_name': state.get('benchmark_name', ''), 'benchmark_contract': state.get('benchmark_contract_compact', {})}
        response_format = {'type': 'json_object', 'mime_type': 'application/json'} if self.llm.capabilities.supports_json else None
        payload, traces, _raw_content = self.generate_parsed_payload_with_retries(state=state, role='test_writer', system_prompt=prompt, context=generation_context, parser=self._parse_payload, response_format=response_format, retry_instruction="The previous test-writer response was not a valid JSON object. Regenerate the payload now. The first character of your response must be '{'. Return exactly one JSON object with keys 'summary' and 'files'. Each file must include 'path' and 'content'. Do not include analysis, markdown, code fences, or explanatory text outside the JSON.", fallback_factory=self._fallback_dynamic_payload)
        written_paths = self._write_test_files(payload)
        syntax_results = self.file_tool.validate_python_syntax([str(path.relative_to(self.file_tool.workspace)) for path in written_paths if path.suffix == '.py'])
        if not syntax_results.get('success', True):
            result = {'command': [], 'returncode': 1, 'success': False, 'no_tests_collected': False, 'stdout': '', 'stderr': 'Generated dynamic tests failed Python syntax validation.', 'generated_tests': [str(path) for path in written_paths], 'summary': payload.summary, 'failure_summary': {'status': 'failed', 'failures': [{'kind': 'generated_test_syntax_error', 'path': error.get('path'), 'message': error.get('message')} for error in syntax_results.get('errors', []) if isinstance(error, dict)]}}
            status = 'failed_bug'
            summary = self._render_summary(payload.summary, result)
            artifact_path = self.file_tool.write_text('artifacts/dynamic_test_summary.md', summary)
            return {'dynamic_test_results': result, 'test_results': result, 'test_status': status, 'messages': append_message(state, 'test_writer', summary), 'artifacts': {**state.get('artifacts', {}), 'dynamic_test_results': result, 'dynamic_test_summary': str(artifact_path)}, 'files_touched': list(state.get('files_touched', [])) + [str(path) for path in written_paths] + [str(artifact_path)], 'traces': traces}
        result = self.test_tool.run_pytest_targets(Path(generated_root), written_paths)
        result['generated_tests'] = [str(path) for path in written_paths]
        result['summary'] = payload.summary
        status = 'passed' if result.get('success') else 'failed_bug'
        summary = self._render_summary(payload.summary, result)
        artifact_path = self.file_tool.write_text('artifacts/dynamic_test_summary.md', summary)
        return {'dynamic_test_results': result, 'test_results': result, 'test_status': status, 'messages': append_message(state, 'test_writer', summary), 'artifacts': {**state.get('artifacts', {}), 'dynamic_test_results': result, 'dynamic_test_summary': str(artifact_path)}, 'files_touched': list(state.get('files_touched', [])) + [str(path) for path in written_paths] + [str(artifact_path)], 'traces': traces}

    def _write_test_files(self, payload: DynamicTestPayload) -> list[Path]:
        files: list[tuple[str, str]] = []
        for generated_file in payload.files:
            relative_path = self._normalize_test_path(generated_file.path)
            files.append((f'{self.GENERATED_PROJECT_ROOT}/{relative_path}', generated_file.content))
        return self.file_tool.write_files(files)

    @staticmethod
    def _normalize_test_path(path: str) -> str:
        clean = path.strip().replace('\\', '/').lstrip('/')
        if '..' in Path(clean).parts:
            raise ValueError(f'Generated test path cannot escape project root: {path}')
        if not clean.startswith('tests/'):
            clean = f'tests/{clean}'
        if not clean.endswith('.py'):
            clean = f'{clean}.py'
        return clean

    def _parse_payload_or_fallback(self, content: str) -> DynamicTestPayload:
        try:
            return self._parse_payload(content)
        except Exception as exc:
            self.logger.warning('Falling back to generic dynamic tests after parse failure: %s', exc)
            return self._fallback_dynamic_payload()

    @staticmethod
    def _fallback_dynamic_payload() -> DynamicTestPayload:
        return DynamicTestPayload(summary='Fallback generic smoke tests generated because the test-writer response was not valid JSON.', files=[GeneratedTestFile(path='tests/test_generated_smoke.py', content="from pathlib import Path\n\n\ndef test_project_contains_source_files():\n    root = Path(__file__).resolve().parents[1]\n    files = [p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts]\n    assert files, 'generated project should contain source files'\n\n\ndef test_no_empty_python_modules():\n    root = Path(__file__).resolve().parents[1]\n    py_files = [p for p in root.rglob('*.py') if 'tests' not in p.parts and '__pycache__' not in p.parts]\n    assert py_files, 'generated project should expose at least one Python source file'\n    empty = [p.relative_to(root).as_posix() for p in py_files if not p.read_text(encoding='utf-8').strip()]\n    assert not empty, f'empty Python files found: {empty}'\n")])

    @staticmethod
    def _parse_payload(content: str) -> DynamicTestPayload:
        normalized = content.strip()
        if normalized.startswith('```'):
            normalized = TestWriterAgent._strip_code_fence(normalized)
        data = json.loads(TestWriterAgent._extract_json_object(normalized))
        if not isinstance(data, dict):
            raise ValueError('Dynamic test payload must be a JSON object.')
        summary = data.get('summary')
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError('Dynamic test payload must include a non-empty summary.')
        files_raw = data.get('files')
        if not isinstance(files_raw, list) or not files_raw:
            raise ValueError('Dynamic test payload must include a non-empty files list.')
        files: list[GeneratedTestFile] = []
        for item in files_raw:
            if not isinstance(item, dict):
                raise ValueError('Each generated test file must be an object.')
            path = item.get('path')
            file_content = item.get('content')
            if not isinstance(path, str) or not path.strip():
                raise ValueError('Each generated test file must include a path.')
            if not isinstance(file_content, str) or not file_content.strip():
                raise ValueError(f'Generated test file {path!r} must include content.')
            files.append(GeneratedTestFile(path=path, content=file_content))
        return DynamicTestPayload(summary=summary.strip(), files=files)

    @staticmethod
    def _extract_json_object(text: str) -> str:
        start = text.find('{')
        end = text.rfind('}')
        if start == -1 or end == -1 or end <= start:
            raise ValueError('No JSON object found in dynamic test payload.')
        return re.sub(',(\\s*[\\]}])', '\\1', text[start:end + 1])

    @staticmethod
    def _strip_code_fence(content: str) -> str:
        lines = content.splitlines()
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].startswith('```'):
            lines = lines[:-1]
        return '\n'.join(lines).strip()

    @staticmethod
    def _render_summary(summary: str, result: dict[str, Any]) -> str:
        status = 'passed' if result.get('success') else 'failed'
        stdout = str(result.get('stdout') or '').strip()
        stderr = str(result.get('stderr') or '').strip()
        if len(stdout) > 3000:
            stdout = stdout[:3000].rstrip() + '...'
        if len(stderr) > 3000:
            stderr = stderr[:3000].rstrip() + '...'
        return f"Dynamic test analysis {status}.\n\n{summary}\n\nReturn code: {result.get('returncode')}\n\nStdout:\n{stdout or '(empty)'}\n\nStderr:\n{stderr or '(empty)'}"