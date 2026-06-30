from __future__ import annotations
from pathlib import Path
from typing import Any, TypedDict
from app.llm.model_config import SystemConfig

class GraphState(TypedDict, total=False):
    user_task: str
    requirements: str
    architecture_plan: str
    planning_feedback: str
    code_generation_request: str
    implementation_summary: str
    reviewer_feedback: str
    test_results: dict[str, Any]
    lint_results: dict[str, Any]
    static_analysis_results: dict[str, Any]
    dynamic_test_results: dict[str, Any]
    browser_test_results: dict[str, Any]
    validation_results: dict[str, Any]
    validation_status: str
    files_touched: list[str]
    artifacts: dict[str, Any]
    planning_iteration: int
    coding_iteration: int
    global_iteration: int
    max_planning_iterations: int
    max_coding_iterations: int
    max_global_iterations: int
    review_status: str
    test_status: str
    final_status: str
    final_output_path: str
    messages: list[dict[str, str]]
    traces: list[dict[str, Any]]
    benchmark_name: str
    benchmark_context: dict[str, Any]
    benchmark_testcode: list[dict[str, Any]]
    benchmark_checklist: list[dict[str, Any]]
    benchmark_contract: dict[str, Any]
    benchmark_contract_compact: dict[str, Any]
    skip_internal_tests: bool
    run_static_analysis: bool
    run_dynamic_analysis: bool
    use_agentic_tools: bool
    workspace: str
    event_callback: Any

def append_message(state: GraphState, role: str, content: str) -> list[dict[str, str]]:
    messages = list(state.get('messages', []))
    messages.append({'role': role, 'content': content})
    return messages

def append_trace(state: GraphState, trace: dict[str, Any]) -> list[dict[str, Any]]:
    traces = list(state.get('traces', []))
    traces.append(trace)
    return traces

def build_initial_state(user_task: str, workspace: Path, system_config: SystemConfig) -> GraphState:
    return GraphState(user_task=user_task, requirements='', architecture_plan='', planning_feedback='', code_generation_request='', implementation_summary='', reviewer_feedback='', test_results={}, lint_results={}, static_analysis_results={}, dynamic_test_results={}, browser_test_results={}, validation_results={}, validation_status='not_run', files_touched=[], artifacts={}, planning_iteration=0, coding_iteration=0, global_iteration=0, max_planning_iterations=system_config.max_planning_iterations, max_coding_iterations=system_config.max_coding_iterations, max_global_iterations=system_config.max_global_iterations, review_status='pending', test_status='not_run', final_status='running', final_output_path='', messages=[], traces=[], benchmark_name='', benchmark_context={}, benchmark_testcode=[], benchmark_checklist=[], benchmark_contract={}, benchmark_contract_compact={}, skip_internal_tests=False, run_static_analysis=True, run_dynamic_analysis=True, use_agentic_tools=False, workspace=str(workspace), event_callback=None)