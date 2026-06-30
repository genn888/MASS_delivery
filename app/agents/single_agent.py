from __future__ import annotations
from pathlib import Path
from typing import Any
from app.agents.coder import CoderAgent
from app.graph.state import GraphState, append_message
from app.tools.file_tools import FileTool

class SingleAgent(CoderAgent):
    """Monolithic ProjectEval generator used for single-agent baselines."""

    def __init__(self, *args, file_tool: FileTool, **kwargs) -> None:
        super().__init__(*args, file_tool=file_tool, **kwargs)

    def run(self, state: GraphState) -> GraphState:
        next_iteration = state.get('coding_iteration', 0) + 1
        self.logger.info('Generating single-agent implementation payload iteration %s', next_iteration)
        prompt = self.load_prompt()
        response_format = None
        if self.llm.capabilities.supports_json:
            response_format = {'type': 'json_object', 'mime_type': 'application/json'}
        context: dict[str, Any] = {'user_task': state['user_task'], 'single_agent_iteration': next_iteration, 'max_single_agent_iterations': state.get('max_coding_iterations', 0), 'benchmark_name': state.get('benchmark_name', ''), 'benchmark_contract': state.get('benchmark_contract_compact', {}), 'previous_feedback': self._build_feedback_digest(state)}
        if next_iteration > 1:
            error_paths = self._extract_error_file_paths(state)
            if error_paths:
                context['current_implementation'] = self._get_current_project_files(error_paths)
                context['implementation_context'] = 'focused_subset'
            else:
                context['current_implementation'] = self.file_tool.get_focused_snapshot(project_root_rel=self.GENERATED_PROJECT_ROOT, touched_paths=state.get('files_touched', []), max_total_files=35)
                context['implementation_context'] = 'touched_subset'
        payload, traces, _raw_content = self.generate_parsed_payload_with_retries(state=state, role='single_agent', system_prompt=prompt, context=context, parser=self._parse_payload, response_format=response_format, retry_instruction="The previous single-agent response was empty or invalid JSON. Return exactly one valid JSON object now. The first character must be '{'. Include a non-empty summary and a non-empty files array with complete project files. Do not include analysis, markdown, code fences, or explanatory text outside the JSON.")
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
        return {'coding_iteration': next_iteration, 'implementation_summary': summary_with_files, 'lint_results': lint_results, 'artifacts': {**state.get('artifacts', {}), 'implementation_summary': str(self.file_tool.resolve_path(str(artifact_path))), 'generated_files': [str(path) for path in written_paths], 'generated_root': str(self.file_tool.resolve_path(self.GENERATED_PROJECT_ROOT)), 'lint_results': lint_results}, 'files_touched': touched, 'messages': append_message(state, 'single_agent', summary_with_files), 'traces': traces}

    @staticmethod
    def _build_feedback_digest(state: GraphState) -> dict[str, Any]:
        lint_results = state.get('lint_results', {})
        static_results = state.get('static_analysis_results', {})
        return {'lint_success': lint_results.get('success') if isinstance(lint_results, dict) else None, 'lint_errors': list(lint_results.get('errors', []))[:8] if isinstance(lint_results, dict) else [], 'static_success': static_results.get('success') if isinstance(static_results, dict) else None, 'static_summary': static_results.get('summary') if isinstance(static_results, dict) else '', 'static_issues': list(static_results.get('issues', []))[:12] if isinstance(static_results, dict) else [], 'review_status': state.get('review_status', '')}