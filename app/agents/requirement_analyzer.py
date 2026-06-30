from __future__ import annotations
from app.agents.base_agent import BaseAgent
from app.graph.state import GraphState, append_message

class RequirementAnalyzerAgent(BaseAgent):

    def run(self, state: GraphState) -> GraphState:
        self.logger.info('Analyzing user requirements')
        prompt = self.load_prompt()
        content, traces = self.generate_text_with_trace(state=state, role='requirement_analyzer', system_prompt=prompt, context={'user_task': state['user_task'], 'workspace': state['workspace'], 'benchmark_name': state.get('benchmark_name', ''), 'benchmark_context': {key: value for key, value in state.get('benchmark_context', {}).items() if key not in {'testcode', 'nl_checklist', 'skeleton'}}})
        return {'requirements': content, 'code_generation_request': 'Implement the requested project according to the analyzed requirements and architecture plan. Produce incremental updates suitable for review.', 'messages': append_message(state, 'requirement_analyzer', content), 'traces': traces}