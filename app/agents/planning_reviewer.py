from __future__ import annotations
from app.agents.base_agent import BaseAgent
from app.agents.review_decision import parse_review_decision
from app.graph.state import GraphState, append_message

class PlanningReviewerAgent(BaseAgent):

    def run(self, state: GraphState) -> GraphState:
        self.logger.info('Reviewing architecture plan')
        prompt = self.load_prompt()
        content, traces = self.generate_text_with_trace(state=state, role='planning_reviewer', system_prompt=prompt, context={'requirements': state.get('requirements', ''), 'architecture_plan': state.get('architecture_plan', ''), 'planning_iteration': state.get('planning_iteration', 0), 'max_planning_iterations': state.get('max_planning_iterations', 0), 'benchmark_name': state.get('benchmark_name', ''), 'benchmark_contract': state.get('benchmark_contract_compact', {})})
        decision = parse_review_decision(content)
        status = 'approved' if decision == 'approved' else 'needs_revision'
        return {'review_status': status, 'planning_feedback': content, 'messages': append_message(state, 'planning_reviewer', content), 'traces': traces}