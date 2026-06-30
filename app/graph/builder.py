from __future__ import annotations
import json
import logging
import time
from pathlib import Path
from typing import Any
from langgraph.graph import END, START, StateGraph
from app.agents.architect import ArchitectAgent
from app.agents.benchmark_contract import BenchmarkContractAgent
from app.agents.browser_test_writer import BrowserTestWriterAgent
from app.agents.coder import CoderAgent
from app.agents.planning_reviewer import PlanningReviewerAgent
from app.agents.requirement_analyzer import RequirementAnalyzerAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.test_writer import TestWriterAgent
from app.analysis.static_analyzer import analyze_generated_project
from app.graph.checkpoint import mark_checkpoint_completed, prepare_pre_node_snapshot, save_checkpoint
from app.graph.code_history import record_code_history
from app.graph.routing import route_after_planning_review, route_after_architect, route_after_reviewer
from app.graph.state import GraphState, append_message
from app.llm.base_client import BaseLLMClient
from app.llm.model_config import SystemConfig
from app.tools.file_tools import FileTool
from app.tools.test_tools import TestTool
from app.observability.events import emit_agent_event
logger = logging.getLogger(__name__)

def _coding_iterations_exhausted(state: GraphState) -> bool:
    return state.get('coding_iteration', 0) >= state.get('max_coding_iterations', 0)

def route_after_dynamic_tests(state: GraphState) -> str:
    dynamic_results = state.get('dynamic_test_results', {})
    failure_summary = dynamic_results.get('failure_summary', {}) if isinstance(dynamic_results, dict) else {}
    if isinstance(failure_summary, dict) and failure_summary.get('kind') == 'django_manage_check_failed':
        return 'finalizer' if _coding_iterations_exhausted(state) else 'reviewer'
    project_type = str(state.get('benchmark_context', {}).get('project_type', '')).strip().lower()
    if project_type == 'website':
        return 'browser_test_writer'
    return 'finalizer' if _coding_iterations_exhausted(state) else 'reviewer'

def route_after_browser_tests(state: GraphState) -> str:
    return 'finalizer' if _coding_iterations_exhausted(state) else 'reviewer'

def route_after_coder(state: GraphState) -> str:
    if state.get('run_static_analysis', True):
        return 'static_analysis'
    if state.get('run_dynamic_analysis', True):
        return 'test_writer'
    return 'finalizer' if _coding_iterations_exhausted(state) else 'reviewer'

def route_after_static_analysis(state: GraphState) -> str:
    if state.get('run_dynamic_analysis', True):
        return 'test_writer'
    return 'finalizer' if _coding_iterations_exhausted(state) else 'reviewer'

def build_workflow(llm_registry: dict[str, BaseLLMClient], workspace: Path, system_config: SystemConfig, start_node: str='requirement_analyzer'):
    _ = system_config
    file_tool = FileTool(workspace)
    test_tool = TestTool(workspace)
    requirement_analyzer = RequirementAnalyzerAgent(llm=llm_registry['requirement_analyzer'], prompt_path=Path('app/prompts/requirement_analyzer.txt'))
    benchmark_contract = BenchmarkContractAgent(llm=llm_registry['requirement_analyzer'], prompt_path=Path('app/prompts/benchmark_contract.txt'))
    architect = ArchitectAgent(llm=llm_registry['architect'], prompt_path=Path('app/prompts/architect.txt'))
    planning_reviewer = PlanningReviewerAgent(llm=llm_registry['planning_reviewer'], prompt_path=Path('app/prompts/planning_reviewer.txt'))
    coder = CoderAgent(llm=llm_registry['coder'], prompt_path=Path('app/prompts/coder.txt'), file_tool=file_tool, test_tool=test_tool)
    test_writer = TestWriterAgent(llm=llm_registry['test_writer'], prompt_path=Path('app/prompts/test_writer.txt'), file_tool=file_tool, test_tool=test_tool)
    browser_test_writer = BrowserTestWriterAgent(llm=llm_registry.get('browser_test_writer', llm_registry['test_writer']), prompt_path=Path('app/prompts/browser_test_writer.txt'), file_tool=file_tool, test_tool=test_tool)
    reviewer = ReviewerAgent(llm=llm_registry['reviewer'], prompt_path=Path('app/prompts/reviewer.txt'), file_tool=file_tool)

    def static_analysis_node(state: GraphState) -> GraphState:
        emit_agent_event(state.get('event_callback'), agent_name='static_analysis', event_type='start', content='Static analysis started.', metadata={})
        generated_root = state.get('artifacts', {}).get('generated_root')
        if generated_root:
            result = analyze_generated_project(Path(generated_root), benchmark_contract=state.get('benchmark_contract', {}))
        else:
            result = {'success': False, 'issues': [{'severity': 'error', 'code': 'missing_generated_root', 'message': 'Generated project root is missing before static analysis.', 'file': None}], 'summary': 'Static analysis failed: generated project root is missing.', 'fix_hints': [{'code': 'missing_generated_root', 'action': 'regenerate_project_root'}]}
        summary = str(result.get('summary', '')).strip()
        trace = {'agent': 'static_analysis', 'role': 'static_analysis', 'provider': None, 'model': None, 'duration_ms': 0.0, 'finish_reason': None, 'usage': {}, 'response_preview': summary[:500]}
        emit_agent_event(state.get('event_callback'), agent_name='static_analysis', event_type='end', content=summary or 'Static analysis completed.', metadata={'success': bool(result.get('success')), 'issue_count': len(result.get('issues', []))})
        return {'static_analysis_results': result, 'messages': append_message(state, 'static_analysis', summary or 'Static analysis completed.'), 'artifacts': {**state.get('artifacts', {}), 'static_analysis_results': result}, 'traces': list(state.get('traces', [])) + [trace]}

    def finalizer_node(state: GraphState) -> GraphState:
        next_global_iteration = state.get('global_iteration', 0) + 1
        logger.info('Running workflow finalizer iteration %s', next_global_iteration)
        emit_agent_event(state.get('event_callback'), agent_name='workflow_finalizer', event_type='start', content=f'Workflow finalizer iteration {next_global_iteration} started.', metadata={'global_iteration': next_global_iteration})
        generated_root = state.get('artifacts', {}).get('generated_root')
        started_at = time.perf_counter()
        lint_results = state.get('lint_results', {})
        lint_failed = bool(lint_results) and (not lint_results.get('success', True))
        static_analysis_results = state.get('static_analysis_results', {})
        static_analysis_failed = bool(static_analysis_results) and (not static_analysis_results.get('success', True))
        dynamic_test_results = state.get('dynamic_test_results', {})
        dynamic_tests_ran = bool(dynamic_test_results)
        dynamic_tests_failed = dynamic_tests_ran and (not dynamic_test_results.get('success', True))
        browser_test_results = state.get('browser_test_results', {})
        browser_tests_ran = bool(browser_test_results)
        browser_tests_failed = browser_tests_ran and (not browser_test_results.get('success', True))
        if lint_failed:
            result = {'command': [], 'returncode': 1, 'success': False, 'no_tests_collected': False, 'stdout': '', 'stderr': '', 'note': 'Internal validation failed before test execution.'}
        elif static_analysis_failed:
            result = {'command': [], 'returncode': 1, 'success': False, 'no_tests_collected': False, 'stdout': '', 'stderr': str(static_analysis_results.get('summary', '')), 'note': 'Static analysis failed before finalization.'}
        elif browser_tests_failed:
            result = browser_test_results
        elif dynamic_tests_ran:
            result = dynamic_test_results
        elif browser_tests_ran:
            result = browser_test_results
        elif state.get('skip_internal_tests', False):
            result = {'command': [], 'returncode': 0, 'success': True, 'no_tests_collected': False, 'stdout': '', 'stderr': '', 'note': 'Internal tests skipped because external benchmark evaluation is enabled.'}
        else:
            result = {'command': [], 'returncode': 0, 'success': True, 'no_tests_collected': False, 'stdout': '', 'stderr': '', 'note': 'Internal tests disabled for this benchmark run.'}
        test_duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        test_writer_summary = str(dynamic_test_results.get('summary') or 'Dynamic tests not run.')
        merged_traces = list(state.get('traces', []))
        artifact_dir = Path(state['workspace']) / 'artifacts'
        artifact_dir.mkdir(parents=True, exist_ok=True)
        report_path = artifact_dir / 'final_report.json'
        browser_test_summary = str(browser_test_results.get('summary') or 'Browser tests not run.')
        output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}\n{test_writer_summary}\n{browser_test_summary}".lower()
        status = 'passed'
        if lint_failed:
            status = 'failed_bug'
        elif static_analysis_failed:
            status = 'failed_validation'
        elif dynamic_tests_failed:
            status = 'failed_architecture' if 'importerror' in output else 'failed_bug'
        elif browser_tests_failed:
            status = 'failed_architecture' if 'importerror' in output else 'failed_bug'
        elif result.get('no_tests_collected'):
            status = 'failed_bug'
        elif not result['success']:
            status = 'failed_architecture' if 'importerror' in output else 'failed_bug'
        final_status = state.get('final_status', 'running')
        if status == 'passed':
            final_status = 'completed'
        elif status == 'failed_validation':
            final_status = 'incomplete'
        elif next_global_iteration >= state.get('max_global_iterations', 0):
            final_status = 'incomplete'
        report_payload: dict[str, Any] = {'user_task': state.get('user_task'), 'requirements': state.get('requirements'), 'architecture_plan': state.get('architecture_plan'), 'implementation_summary': state.get('implementation_summary'), 'review_status': state.get('review_status'), 'validation_results': state.get('validation_results', {}), 'validation_status': state.get('validation_status', 'not_run'), 'static_analysis_results': static_analysis_results, 'dynamic_test_results': dynamic_test_results, 'browser_test_results': browser_test_results, 'test_status': status, 'final_status': final_status, 'iterations': {'planning': state.get('planning_iteration', 0), 'coding': state.get('coding_iteration', 0), 'global': next_global_iteration}, 'test_results': result, 'test_writer_summary': test_writer_summary, 'browser_test_summary': browser_test_summary, 'generated_root': generated_root, 'traces': merged_traces, 'benchmark_summary': {'total_traces': len(merged_traces) + 1, 'finalizer_duration_ms': test_duration_ms, 'static_analysis_blocked_tests': static_analysis_failed, 'dynamic_tests_ran': dynamic_tests_ran, 'browser_tests_ran': browser_tests_ran, 'benchmark_contract_hash': (state.get('benchmark_contract') or {}).get('hash'), 'benchmark_contract_summary': (state.get('benchmark_contract') or {}).get('summary')}}
        report_path.write_text(json.dumps(report_payload, indent=2), encoding='utf-8')
        emit_agent_event(state.get('event_callback'), agent_name='workflow_finalizer', event_type='end', content=f'Final report generated with technical status {status}.', metadata={'status': status, 'returncode': result['returncode']})
        updated_messages = append_message({'messages': list(state.get('messages', []))}, 'workflow_finalizer', f'Final report generated. Technical status={status}.')
        update = {'global_iteration': next_global_iteration, 'test_results': result, 'test_status': status, 'final_status': final_status, 'final_output_path': str(report_path), 'artifacts': {**state.get('artifacts', {}), 'final_report': str(report_path)}, 'files_touched': list(state.get('files_touched', [])) + [str(report_path)], 'messages': updated_messages, 'traces': merged_traces + [{'agent': 'workflow_finalizer', 'role': 'finalizer', 'provider': None, 'model': None, 'duration_ms': test_duration_ms, 'finish_reason': None, 'usage': {}, 'response_preview': f"finalizer status={status}, returncode={result['returncode']}"}]}
        completed_state = {**state, **update}
        mark_checkpoint_completed(workspace=Path(state['workspace']), state=completed_state)
        return update
    graph = StateGraph(GraphState)
    nodes = {'requirement_analyzer': requirement_analyzer.run, 'benchmark_contract': benchmark_contract.run, 'architect': architect.run, 'planning_reviewer': planning_reviewer.run, 'coder': coder.run, 'static_analysis': static_analysis_node, 'test_writer': test_writer.run, 'browser_test_writer': browser_test_writer.run, 'reviewer': reviewer.run, 'finalizer': finalizer_node}
    if start_node not in nodes:
        raise ValueError(f'Unsupported workflow start node: {start_node}')
    for node_name, node_func in nodes.items():
        graph.add_node(node_name, _checkpointed_node(node_name, node_func))
    graph.add_edge(START, start_node)
    graph.add_edge('requirement_analyzer', 'benchmark_contract')
    graph.add_edge('benchmark_contract', 'architect')
    graph.add_conditional_edges('architect', route_after_architect, {'planning_reviewer': 'planning_reviewer', 'coder': 'coder'})
    graph.add_conditional_edges('planning_reviewer', route_after_planning_review, {'architect': 'architect', 'coder': 'coder'})
    graph.add_conditional_edges('coder', route_after_coder, {'static_analysis': 'static_analysis', 'test_writer': 'test_writer', 'reviewer': 'reviewer', 'finalizer': 'finalizer'})
    graph.add_conditional_edges('static_analysis', route_after_static_analysis, {'test_writer': 'test_writer', 'reviewer': 'reviewer', 'finalizer': 'finalizer'})
    graph.add_conditional_edges('test_writer', route_after_dynamic_tests, {'browser_test_writer': 'browser_test_writer', 'reviewer': 'reviewer', 'finalizer': 'finalizer'})
    graph.add_conditional_edges('browser_test_writer', route_after_browser_tests, {'reviewer': 'reviewer', 'finalizer': 'finalizer'})
    graph.add_conditional_edges('reviewer', route_after_reviewer, {'coder': 'coder', 'end': 'finalizer'})
    graph.add_edge('finalizer', END)
    return graph.compile()

def _checkpointed_node(node_name: str, node_func):

    def wrapped(state: GraphState) -> GraphState:
        workspace = Path(state['workspace'])
        prepare_pre_node_snapshot(workspace=workspace, node_name=node_name)
        save_checkpoint(workspace=workspace, state=state, current_node=node_name, resume_node=node_name, status='in_progress', last_completed_node=_infer_last_completed_node(node_name, state), note=f'{node_name} started')
        update = node_func(state)
        if node_name == 'coder':
            record_code_history(workspace=workspace, coding_iteration=update.get('coding_iteration'))
        return update
    return wrapped

def _infer_last_completed_node(node_name: str, state: GraphState) -> str | None:
    if node_name == 'requirement_analyzer':
        return None
    if node_name == 'benchmark_contract':
        return 'requirement_analyzer'
    if node_name == 'architect':
        return 'planning_reviewer' if state.get('planning_iteration', 0) > 0 else 'benchmark_contract'
    if node_name == 'planning_reviewer':
        return 'architect'
    if node_name == 'coder':
        return 'reviewer' if state.get('coding_iteration', 0) > 0 else 'planning_reviewer'
    if node_name == 'static_analysis':
        return 'coder'
    if node_name == 'test_writer':
        return 'static_analysis' if state.get('run_static_analysis', True) else 'coder'
    if node_name == 'browser_test_writer':
        return 'test_writer'
    if node_name == 'reviewer':
        if state.get('browser_test_results'):
            return 'browser_test_writer'
        if state.get('dynamic_test_results'):
            return 'test_writer'
        if state.get('static_analysis_results'):
            return 'static_analysis'
        return 'coder'
    if node_name == 'finalizer':
        if state.get('browser_test_results'):
            return 'browser_test_writer'
        if state.get('dynamic_test_results'):
            return 'test_writer'
        if state.get('static_analysis_results'):
            return 'static_analysis'
        return 'reviewer' if state.get('reviewer_feedback') else 'coder'
    return None