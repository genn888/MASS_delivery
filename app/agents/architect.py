from __future__ import annotations
from app.agents.base_agent import BaseAgent
from app.graph.state import GraphState, append_message

class ArchitectAgent(BaseAgent):

    def run(self, state: GraphState) -> GraphState:
        next_iteration = state.get('planning_iteration', 0) + 1
        self.logger.info('Generating architecture plan iteration %s', next_iteration)
        prompt = self.load_prompt()
        content, traces = self.generate_text_with_trace(state=state, role='architect', system_prompt=prompt, context={'user_task': state['user_task'], 'requirements': state.get('requirements', ''), 'planning_feedback': state.get('planning_feedback', ''), 'planning_iteration': next_iteration, 'max_planning_iterations': state.get('max_planning_iterations', 0), 'benchmark_name': state.get('benchmark_name', ''), 'benchmark_contract': state.get('benchmark_contract_compact', {})})
        return {'planning_iteration': next_iteration, 'architecture_plan': content, 'messages': append_message(state, 'architect', content), 'traces': traces}