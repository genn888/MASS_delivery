# Agent: Parameter Solver

The Parameter Solver is a specialized agent used during benchmarks (ProjectEval) to bridge the gap between generated code and external evaluation.

## Responsibilities
- Analyze the generated source code.
- Identify the exact HTML IDs, XPaths, or URLs used for specific features.
- Map these implementations to the parameters required by the ProjectEval benchmark.
- Return a structured JSON mapping.

## Prompting Details
The agent is highly constrained to return valid JSON and follow strict rules for format types:
- `*_xpath` must start with `//`.
- `*_id` must be raw literal attributes.
- `*_url` must be fully qualified.
- **System Prompt**: Generated via `build_parameter_solver_system_prompt()` in `app/benchmark/projecteval_runner.py`.

## Implementation
- **Function**: `solve_parameters`
- **Location**: `app/benchmark/projecteval_runner.py`
- **Utility**: It uses heuristic normalization (`normalize_parameter_answers`) to ensure high accuracy even if the LLM makes minor formatting errors.

## Workflow Interaction
- This agent is **external** to the main LangGraph cycle.
- It is executed after the project generation is finished, during the `ProjectEval` post-processing phase, before running the external "Judge".
