# Agent: Parameter Repairer

The Parameter Repairer is a fallback agent dedicated to fixing malformed JSON responses from the Parameter Solver.

## Responsibilities
- Take a malformed or invalid JSON response and the associated error message.
- Reconstruct the JSON object according to the required schema.
- Preserve the technical logic while fixing syntax or structure issues.

## Prompting Details
The agent is explicitly instructed to "prefer correctness over copying malformed text" and to avoid any commentary or markdown formatting.
- **System Prompt**: Generated via `repair_parameter_response()` in `app/benchmark/projecteval_runner.py`.

## Implementation
- **Function**: `repair_parameter_response`
- **Location**: `app/benchmark/projecteval_runner.py`

## Workflow Interaction
- It is triggered automatically if the `Parameter Solver` outputs invalid JSON or if parsing fails after local heuristic repairs.
- After repair, the output is sent back to the parser.
