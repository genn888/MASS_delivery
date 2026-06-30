# Agent: Planning Reviewer

The Planning Reviewer acts as a sanity check for the architect's plan.

## Responsibilities
- Review the architecture plan against the requirements.
- Identify missing components or weak iteration logic.
- Ensure the routing and test strategies are clear.
- Provide binary feedback: "Approved" or "Changes requested".

## Prompting Details
The agent is focused on finding gaps in the strategy before any code is written.
- **System Prompt**: `app/prompts/planning_reviewer.txt`

## Implementation
- **Class**: `PlanningReviewerAgent`
- **File**: `app/agents/planning_reviewer.py`

## Workflow Interaction
- **Input Node**: `architect`.
- **Output Node**:
    - Returns to `architect` if "Changes requested".
    - Proceeds to `coder` if "Approved".
