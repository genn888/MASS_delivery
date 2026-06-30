# Agent: Architect

The Architect agent is responsible for designing the system based on the requirements. It produces an implementation-ready plan.

## Responsibilities
- Define components and their responsibilities.
- Design the shared state usage.
- Outline workflow phases and routing.
- Set an iteration strategy.
- Ensure the plan honors the requested technical stack.
- Optimize for observability, especially for web projects (e.g., preference for multi-page architecture with stable URLs).

## Prompting Details
The architect is instructed to avoid complex JavaScript-driven layouts in favor of structural simplicity and linear navigation to ensure the project is easily verifiable by automated tools.
- **System Prompt**: `app/prompts/architect.txt`
- **Injected Context**: Requirements, planning feedback (if any).

## Implementation
- **Class**: `ArchitectAgent`
- **File**: `app/agents/architect.py`

## Workflow Interaction
- **Input Node**: `requirement_analyzer` or `planning_reviewer` (in case of requested changes).
- **Output Node**: `planning_reviewer` or `coder`.
- **Output State**: Populates the `architecture_plan` field in the `GraphState`.
