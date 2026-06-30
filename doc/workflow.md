# System Workflow Documentation

This document describes the execution flow of the MASS system, managed via a LangGraph state machine.

## Workflow Overview

The system follows a structured multi-agent workflow to transform a user task into a verified project. The flow is iterative, allowing for cycles between implementation, validation, and review.

### Entry Point
The workflow starts at the `requirement_analyzer` node.

### Execution Graph

1.  **`requirement_analyzer`**
    - **Input**: User task.
    - **Output**: Formalized requirements.
    - **Transition**: Moves directly to `architect`.

2.  **`architect`**
    - **Input**: Requirements.
    - **Output**: High-level architecture and implementation plan.
    - **Routing**: Can go to `planning_reviewer` (if a review is requested/required) or directly to `coder`.

3.  **`planning_reviewer`**
    - **Input**: Architecture plan.
    - **Output**: Feedback or approval.
    - **Routing**: If changes are requested, returns to `architect`. If approved, proceeds to `coder`.

4.  **`coder`**
    - **Input**: Architecture plan and feedback.
    - **Output**: Source code in the workspace.
    - **Routing**: Proceeds to a **validator node** (`web_benchmark_validator` or `batch_benchmark_validator`) based on project type.

5.  **`web_benchmark_validator` / `batch_benchmark_validator`** (Static Validators)
    - **Action**: Executes deterministic checks (e.g., checks if the homepage loads, verifies element IDs).
    - **Routing**: 
        - If validation fails: Returns to `coder` for fixing.
        - If validation passes: Proceeds to `reviewer`.
        - *Condition*: If a maximum number of local iterations is reached, it can proceed to `finalizer`.

6.  **`reviewer`**
    - **Input**: Generated code and validation results.
    - **Output**: Feedback or approval.
    - **Routing**:
        - If changes requested: Returns to `coder`.
        - If approved: Proceeds to `finalizer`.

7.  **`finalizer`**
    - **Action**: Generates a summary report (`final_report.json`), updates global iteration counters, and determines the final status.
    - **Termination**: Ends at `END`.

## Iterations and Conditions

- **Local Loops**:
    - **Architect <-> Planning Reviewer**: Refines the plan before coding starts.
    - **Coder <-> Validator**: Fixes deterministic issues (linting, structure, expected IDs) before the human-like review.
    - **Coder <-> Reviewer**: High-level review and bug fixing.
- **Global Iterations**: The workflow can repeat the entire process if the `finalizer` determines that the task is not "completed" and `max_global_iterations` has not been reached.

## Implementation Details

- **Graph Builder**: `app/graph/builder.py`
- **Routing Logic**: `app/graph/routing.py`
- **State Management**: `app/graph/state.py`
- **Workflow Runner**: `app/workflow.py`
