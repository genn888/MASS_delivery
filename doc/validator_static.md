# Static Validator (Deterministic)

The Static Validator is **not an LLM-based agent**. It is a set of hardcoded Python functions that perform deterministic verification of the generated project.

## Responsibilities
- **Linting**: Checks for basic syntax errors or missing imports.
- **Structural Verification**: Ensures required files (like `manage.py` or `requirements.txt`) exist.
- **Web Verification**: For website projects, it checks if the application starts and if the homepage is reachable.
- **ProjectEval Integration**: In benchmark runs, it verifies if the implemented features match the expected element IDs or selectors required by the benchmark's external tests.

## Why it's not an LLM
Using a deterministic validator provides several advantages:
1.  **Reliability**: It catches common mistakes (like missing dependencies) that an LLM might overlook.
2.  **Cost-Efficiency**: It avoids unnecessary LLM calls for simple checks.
3.  **Speed**: Execution is near-instant compared to model generation.

## Implementation
The validator is split into nodes in the LangGraph that call specific Python modules:
- **Graph Nodes**: `web_benchmark_validator`, `batch_benchmark_validator`
- **Source Files**: 
    - `app/validation/web_benchmark_validator.py`
    - `app/validation/batch_benchmark_validator.py`
- **Builder Definition**: `app/graph/builder.py`

## Workflow Interaction
- **Trigger**: Called every time the `Coder` finishes a pass.
- **Behavior**: If validation fails, the feedback is passed back to the `Coder`. If it passes, the project is handed over to the `Reviewer` (LLM) for a more qualitative check.
