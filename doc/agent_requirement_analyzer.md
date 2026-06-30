# Agent: Requirement Analyzer

The Requirement Analyzer is the first agent in the workflow. Its goal is to translate the raw user task into a structured set of implementation-oriented requirements.

## Responsibilities
- Define the scope of the project.
- Enumerate functional and non-functional requirements.
- Identify constraints and list open assumptions.
- Provide a clear foundation for the Architect.

## Prompting Details
The agent is prompted to be concise and structured. It focuses on turning ambiguity into actionable specifications.
- **System Prompt**: `app/prompts/requirement_analyzer.txt`
- **Context Provided**:
    - `user_task`: The original instruction from the user.
    - `benchmark_context`: If running a benchmark, specific technical hints or constraints.

## Implementation
- **Class**: `RequirementAnalyzerAgent`
- **File**: `app/agents/requirement_analyzer.py`

## Workflow Interaction
- **Starts**: After the workflow starts (START -> `requirement_analyzer`).
- **Ends**: Transitions to the `architect` node.
- **Output State**: Populates the `requirements` field in the `GraphState`.
