# Agent: Coder

The Coder agent is the "workhorse" that creates the actual source code files.

## Responsibilities
- Implement the project based on the requirements and architecture plan.
- Produce incremental updates.
- Ensure the code follows the technical stack.
- Fix issues identified by the Reviewer or the Static Validator.

## Prompting Details
The Coder must return a valid JSON object containing a summary and a list of files with their paths and full content.
- **System Prompt**: `app/prompts/coder.txt`
- **Output Format**:
  ```json
  {
    "summary": "markdown string",
    "files": [
      { "path": "...", "content": "..." }
    ]
  }
  ```

## Implementation
- **Class**: `CoderAgent`
- **File**: `app/agents/coder.py`
- **Utility**: Uses `FileTool` to interact with the filesystem.

## Workflow Interaction
- **Input Node**: `architect`, `planning_reviewer`, `reviewer`, or `validator`.
- **Output Node**: Transitions to one of the **Static Validators** (`web_benchmark_validator` or `batch_benchmark_validator`).
