from __future__ import annotations
from app.graph.state import GraphState

def route_after_planning_review(state: GraphState) -> str:
    if state.get('review_status') == 'approved':
        return 'coder'
    return 'architect'

def route_after_architect(state: GraphState) -> str:
    if state.get('planning_iteration', 0) >= state.get('max_planning_iterations', 0):
        return 'coder'
    return 'planning_reviewer'

def route_after_reviewer(state: GraphState) -> str:
    if state.get('review_status') == 'approved':
        return 'end'
    if state.get('coding_iteration', 0) >= state.get('max_coding_iterations', 0):
        return 'end'
    return 'coder'