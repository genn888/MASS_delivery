from __future__ import annotations
import json
from pathlib import Path
from app.agents.base_agent import BaseAgent
from app.benchmark.contract import build_benchmark_contract, compact_contract_for_prompt
from app.graph.state import GraphState, append_message

class BenchmarkContractAgent(BaseAgent):
    """Deterministic ProjectEval contract builder."""

    def run(self, state: GraphState) -> GraphState:
        benchmark_name = state.get('benchmark_name', '')
        raw_context = state.get('benchmark_context', {})
        if benchmark_name != 'projecteval':
            return {'benchmark_contract': {}, 'benchmark_contract_compact': {}, 'messages': append_message(state, 'benchmark_contract', 'No benchmark contract required.')}
        contract = build_benchmark_contract(project_id=str(raw_context.get('project_id', '')), project_type=str(raw_context.get('project_type', '')), technical_stack=str(raw_context.get('technical_stack', '')), level=raw_context.get('level'), mode=str(raw_context.get('mode', '')), testcode=state.get('benchmark_testcode', []), nl_checklist=state.get('benchmark_checklist', []))
        compact = compact_contract_for_prompt(contract)
        artifact_path = None
        workspace = state.get('workspace')
        if workspace:
            artifact_dir = Path(workspace) / 'artifacts'
            artifact_dir.mkdir(parents=True, exist_ok=True)
            target = artifact_dir / 'benchmark_contract.json'
            target.write_text(json.dumps(contract, indent=2, ensure_ascii=True), encoding='utf-8')
            artifact_path = str(target)
        summary = str(contract.get('summary') or 'Benchmark contract generated.')
        trace = {'agent': 'BenchmarkContractAgent', 'role': 'benchmark_contract', 'provider': None, 'model': None, 'prompt_path': str(self.prompt_path), 'transcript_path': None, 'duration_ms': 0.0, 'finish_reason': 'deterministic', 'usage': {}, 'response_preview': summary[:500]}
        return {'benchmark_contract': contract, 'benchmark_contract_compact': compact, 'messages': append_message(state, 'benchmark_contract', summary), 'artifacts': {**state.get('artifacts', {}), 'benchmark_contract': artifact_path}, 'traces': list(state.get('traces', [])) + [trace]}