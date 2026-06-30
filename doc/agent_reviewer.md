# Agent: Reviewer

The Reviewer agent performs a high-level review of the implemented code.

## Responsibilities
- Evaluate the code against requirements and architecture.
- Identify bugs, architectural inconsistencies, or missing features.
- Provide feedback for the Coder.

## Prompting Details
The reviewer looks at the entire implementation summary and the generated files.
- **System Prompt**: `app/prompts/reviewer.txt`

## Implementation
- **Class**: `ReviewerAgent`
- **File**: `app/agents/reviewer.py`

## Workflow Interaction
- **Input Node**: Transitions from a validator node after passing static checks.
- **Output Node**:
    - Returns to `coder` if changes are needed.
    - Transitions to `finalizer` if the work is approved.
