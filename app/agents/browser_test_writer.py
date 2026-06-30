from __future__ import annotations
from pathlib import Path
from typing import Any
from app.agents.base_agent import BaseAgent
from app.agents.test_writer import DynamicTestPayload, GeneratedTestFile, TestWriterAgent
from app.graph.state import GraphState, append_message
from app.tools.file_tools import FileTool
from app.tools.test_tools import TestTool

class BrowserTestWriterAgent(BaseAgent):
    __test__ = False
    GENERATED_PROJECT_ROOT = 'generated_project'

    def __init__(self, *args, file_tool: FileTool, test_tool: TestTool, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.file_tool = file_tool
        self.test_tool = test_tool

    def run(self, state: GraphState) -> GraphState:
        self.logger.info('Generating and running Selenium browser tests')
        prompt = self.load_prompt()
        generated_root = state.get('artifacts', {}).get('generated_root')
        if not generated_root:
            result = {'success': False, 'returncode': 1, 'stdout': '', 'stderr': 'Generated project root is missing before browser testing.', 'no_tests_collected': True, 'generated_tests': []}
            summary = 'Browser test analysis failed: generated project root is missing.'
            return {'browser_test_results': result, 'test_status': 'failed_bug', 'messages': append_message(state, 'browser_test_writer', summary), 'artifacts': {**state.get('artifacts', {}), 'browser_test_results': result}}
        django_check = self.test_tool.run_django_check(Path(generated_root))
        if not django_check.get('success', True):
            result = {**django_check, 'no_tests_collected': False, 'generated_tests': [], 'summary': 'Django sanity check failed before generated browser tests were written.', 'failure_summary': {**django_check.get('failure_summary', {}), 'kind': 'django_manage_check_failed'}}
            summary = self._render_summary('Django sanity check failed before generated browser tests were written.', result)
            artifact_path = self.file_tool.write_text('artifacts/browser_test_summary.md', summary)
            return {'browser_test_results': result, 'test_status': 'failed_bug', 'messages': append_message(state, 'browser_test_writer', summary), 'artifacts': {**state.get('artifacts', {}), 'browser_test_results': result, 'browser_test_summary': str(artifact_path), 'django_health_check': django_check}, 'files_touched': list(state.get('files_touched', [])) + [str(artifact_path)]}
        current_implementation = self.file_tool.get_focused_snapshot(project_root_rel=self.GENERATED_PROJECT_ROOT, touched_paths=state.get('files_touched', []), max_total_files=20, excluded_path_patterns=('**/__init__.py', '**/migrations/**', 'tests/**', '*.sqlite3', '*.db'))
        generation_context = {'user_task': state['user_task'], 'requirements': state.get('requirements', ''), 'architecture_plan': state.get('architecture_plan', ''), 'implementation_summary': state.get('implementation_summary', ''), 'static_analysis_results': state.get('static_analysis_results', {}), 'dynamic_test_results': self._compact_test_results(state.get('dynamic_test_results', {})), 'django_health_check': django_check, 'browser_test_server_policy': "For Django subprocess browser tests, choose a free 127.0.0.1 port at runtime with socket.bind(('127.0.0.1', 0)); never hard-code 8000. Start runserver on that selected port, build base_url from it, and skip if the launched subprocess exits instead of accepting an already-running unrelated server.", 'current_implementation': current_implementation, 'benchmark_name': state.get('benchmark_name', ''), 'benchmark_contract': state.get('benchmark_contract_compact', {})}
        response_format = {'type': 'json_object', 'mime_type': 'application/json'} if self.llm.capabilities.supports_json else None
        payload, traces, _raw_content = self.generate_parsed_payload_with_retries(state=state, role='browser_test_writer', system_prompt=prompt, context=generation_context, parser=self._parse_payload, response_format=response_format, retry_instruction="The previous browser-test-writer response was not a valid JSON object. Regenerate the payload now. The first character of your response must be '{'. Return exactly one JSON object with keys 'summary' and 'files'. Each file must include 'path' and 'content'. Do not include analysis, markdown, code fences, or explanatory text outside the JSON.", fallback_factory=self._fallback_browser_payload)
        written_paths = self._write_test_files(payload)
        syntax_results = self.file_tool.validate_python_syntax([str(path.relative_to(self.file_tool.workspace)) for path in written_paths if path.suffix == '.py'])
        if not syntax_results.get('success', True):
            result = {'command': [], 'returncode': 1, 'success': False, 'no_tests_collected': False, 'stdout': '', 'stderr': 'Generated browser tests failed Python syntax validation.', 'generated_tests': [str(path) for path in written_paths], 'summary': payload.summary, 'failure_summary': {'status': 'failed', 'failures': [{'kind': 'generated_browser_test_syntax_error', 'path': error.get('path'), 'message': error.get('message')} for error in syntax_results.get('errors', []) if isinstance(error, dict)]}}
            status = 'failed_bug'
            summary = self._render_summary(payload.summary, result)
            artifact_path = self.file_tool.write_text('artifacts/browser_test_summary.md', summary)
            return {'browser_test_results': result, 'test_status': status, 'messages': append_message(state, 'browser_test_writer', summary), 'artifacts': {**state.get('artifacts', {}), 'browser_test_results': result, 'browser_test_summary': str(artifact_path)}, 'files_touched': list(state.get('files_touched', [])) + [str(path) for path in written_paths] + [str(artifact_path)], 'traces': traces}
        browser_tests_dir = Path(generated_root) / 'tests' / 'browser'
        result = self.test_tool.run_pytest_target(Path(generated_root), browser_tests_dir)
        result['generated_tests'] = [str(path) for path in written_paths]
        result['summary'] = payload.summary
        status = 'passed' if result.get('success') else 'failed_bug'
        summary = self._render_summary(payload.summary, result)
        artifact_path = self.file_tool.write_text('artifacts/browser_test_summary.md', summary)
        return {'browser_test_results': result, 'test_status': status, 'messages': append_message(state, 'browser_test_writer', summary), 'artifacts': {**state.get('artifacts', {}), 'browser_test_results': result, 'browser_test_summary': str(artifact_path)}, 'files_touched': list(state.get('files_touched', [])) + [str(path) for path in written_paths] + [str(artifact_path)], 'traces': traces}

    def _write_test_files(self, payload: DynamicTestPayload) -> list[Path]:
        files: list[tuple[str, str]] = []
        for generated_file in payload.files:
            relative_path = self._normalize_browser_test_path(generated_file.path)
            files.append((f'{self.GENERATED_PROJECT_ROOT}/{relative_path}', generated_file.content))
        return self.file_tool.write_files(files)

    @staticmethod
    def _normalize_browser_test_path(path: str) -> str:
        clean = path.strip().replace('\\', '/').lstrip('/')
        if '..' in Path(clean).parts:
            raise ValueError(f'Generated browser test path cannot escape project root: {path}')
        if not clean.startswith('tests/browser/'):
            clean = f"tests/browser/{clean.removeprefix('tests/')}"
        if not clean.endswith('.py'):
            clean = f'{clean}.py'
        return clean

    def _parse_payload_or_fallback(self, content: str) -> DynamicTestPayload:
        try:
            return TestWriterAgent._parse_payload(content)
        except Exception as exc:
            self.logger.warning('Falling back to generic browser tests after parse failure: %s', exc)
            return self._fallback_browser_payload()

    def _fallback_browser_payload(self) -> DynamicTestPayload:
        return DynamicTestPayload(summary='Fallback Selenium availability test generated because the browser-test response was not valid JSON.', files=[GeneratedTestFile(path='tests/browser/test_browser_environment.py', content=self._fallback_browser_test_content())])

    @staticmethod
    def _parse_payload(content: str) -> DynamicTestPayload:
        return TestWriterAgent._parse_payload(content)

    @staticmethod
    def _fallback_browser_test_content() -> str:
        return "import pytest\n\n\ndef test_selenium_browser_environment_available():\n    webdriver = pytest.importorskip('selenium.webdriver')\n    options = webdriver.ChromeOptions()\n    options.add_argument('--headless=new')\n    options.add_argument('--no-sandbox')\n    options.add_argument('--disable-dev-shm-usage')\n    try:\n        driver = webdriver.Chrome(options=options)\n    except Exception as exc:\n        pytest.skip(f'Selenium Chrome browser unavailable: {exc}')\n    else:\n        driver.quit()\n"

    @staticmethod
    def _render_summary(summary: str, result: dict[str, Any]) -> str:
        status = 'passed' if result.get('success') else 'failed'
        stdout = str(result.get('stdout') or '').strip()
        stderr = str(result.get('stderr') or '').strip()
        if len(stdout) > 3000:
            stdout = stdout[:3000].rstrip() + '...'
        if len(stderr) > 3000:
            stderr = stderr[:3000].rstrip() + '...'
        return f"Browser test analysis {status}.\n\n{summary}\n\nReturn code: {result.get('returncode')}\n\nStdout:\n{stdout or '(empty)'}\n\nStderr:\n{stderr or '(empty)'}"

    @staticmethod
    def _compact_test_results(results: dict[str, Any]) -> dict[str, Any]:
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
        return {'success': results.get('success'), 'returncode': results.get('returncode'), 'no_tests_collected': results.get('no_tests_collected'), 'summary': str(results.get('summary') or '')[:1000], 'failure_summary': failure_summary, 'stderr_excerpt': str(results.get('stderr') or '')[:750], 'stdout_excerpt': str(results.get('stdout') or '')[:750]}