# MASS Advanced Workflow Guide

This document expands the basic workflow notes in `doc/workflow.md` and captures the practical explanation of the MASS workflow discussed during analysis.

It focuses only on the components currently in use in the main MASS workflow and on the benchmark-specific post-processing used for `ProjectEval`.

## 1. Entry Points

There are two main entry paths depending on how MASS is used.

- CLI / generic run:
  - `app/main.py`
  - calls `run_workflow(...)`
- ProjectEval benchmark run:
  - `app/benchmark/projecteval_runner.py`
  - calls `run_workflow(...)` once per project

The core logical entrypoint is:

- `app/workflow.py`

`run_workflow(...)`:
- loads model config
- loads system config
- creates the LLM registry
- builds the LangGraph workflow
- builds the initial graph state
- optionally merges benchmark-specific overrides
- invokes the graph

## 2. UI Benchmark Start Flow

When a benchmark is started from the interface, the first backend component that actually takes ownership of the request is:

- `app/ui_backend/benchmark_runner.py`

Important pieces:

- `BenchmarkRequest` is defined in `app/ui_backend/models.py`
- `BenchmarkRunner.start(request)` creates a session and starts a worker thread
- `_run_benchmark_thread(...)` writes config files and launches:
  - `python -m app.benchmark.projecteval_runner --config ...`

So the operational chain is:

- UI creates `BenchmarkRequest`
- `BenchmarkRunner.start(...)` accepts it
- `_run_benchmark_thread(...)` launches `projecteval_runner.py`
- `projecteval_runner.py` iterates over benchmark projects and calls `run_workflow(...)`

## 3. State and Shared Context

MASS agents do not work on isolated local variables. They read and write a shared workflow state.

This state is defined in:

- `app/graph/state.py`

The initial state is built by:

- `build_initial_state(...)`

Some important fields:

- `user_task`: the task text given to the workflow
- `requirements`: output of the requirement analyzer
- `architecture_plan`: output of the architect
- `planning_feedback`: feedback from the planning reviewer
- `implementation_summary`: coder summary
- `validation_results`: deterministic validator output
- `validation_status`: `passed` or `changes_requested`
- `review_status`: review decision
- `files_touched`: files written or modified
- `artifacts`: paths and metadata for generated outputs
- `messages`: lightweight logical history of workflow outputs
- `traces`: technical traces for observability
- `benchmark_name`: benchmark identifier such as `projecteval`
- `benchmark_context`: benchmark-specific metadata

### What `messages` and `traces` mean

- `messages`
  - logical record of what each node/agent produced
  - useful as workflow memory
- `traces`
  - technical execution record
  - includes model name, duration, transcript path, usage, response preview

### What `code_generation_request` means

The requirement analyzer also writes `code_generation_request`.

This is a bridge instruction for later stages. In the current workflow it is not the main driver of behavior, but it acts as a general implementation intent attached to the state.

## 4. Graph Construction and Routing

The workflow graph is built in:

- `app/graph/builder.py`

Routing decisions are in:

- `app/graph/routing.py`

The main active graph is:

1. `requirement_analyzer`
2. `architect`
3. `planning_reviewer`
4. `coder`
5. `web_benchmark_validator` or `batch_benchmark_validator`
6. `reviewer`
7. `finalizer`

There are two main local loops:

- planning loop:
  - `architect <-> planning_reviewer`
- implementation loop:
  - `coder -> validator -> reviewer -> coder`

## 5. Benchmark Context

During a `ProjectEval` run, `projecteval_runner.py` injects benchmark-specific information into the workflow state through `initial_overrides`.

The key fields used are:

- `benchmark_name`
- `benchmark_context`
- `skip_internal_tests`
- `event_callback`

### Where benchmark fields come from

The common benchmark context fields are:

- `project_id`
- `project_type`
- `technical_stack`
- `level`
- `mode`
- `testcode`

They come from two places.

From user selection:

- `project_ids`
- `level`
- `mode`

From the ProjectEval dataset:

- `project_type`
- `technical_stack`
- `testcode`

The dataset is loaded in:

- `app/benchmark/projecteval_runner.py`

### Why benchmark awareness matters

ProjectEval does not only test whether a project is "reasonable". It checks contract-like conditions such as:

- expected stack
- entrypoints
- routes
- selectors and ids
- exported metadata

If the workflow does not know it is solving a benchmark task, it may optimize for a generic "build a plausible app" objective rather than "build an app that satisfies the benchmark contract".

So benchmark awareness is intentional in MASS.

### Methodological note about leakage

In the current MASS setup, the workflow is strongly benchmark-aware.

The system sees:

- task text derived from the benchmark
- benchmark context
- hints derived from evaluator expectations

In the original MASS benchmark path, this also includes direct or near-direct exposure to benchmark `testcode` in several places.

This means MASS is not a blind benchmark setup. It is closer to a benchmark-optimized system than to a pure generalization evaluation.

## 6. Requirement Analyzer

Files:

- `app/agents/requirement_analyzer.py`
- prompt: `app/prompts/requirement_analyzer.txt`

Position in workflow:

- first real agent after `START`

Responsibilities:

- reads `user_task`
- optionally reads benchmark context
- transforms the initial task into structured requirements
- prepares cleaner input for later planning

Reads from state:

- `user_task`
- `workspace`
- `benchmark_name`
- `benchmark_context`

Why those extra fields matter:

- `workspace`
  - the working directory for the run
  - useful operational context
- `benchmark_name`
  - tells the agent whether this is a benchmarked run, for example `projecteval`
- `benchmark_context`
  - detailed benchmark metadata

Writes to state:

- `requirements`
- `code_generation_request`
- `messages`
- `traces`

Interpretation:

- `requirements`
  - structured requirement output
- `code_generation_request`
  - general implementation intent for downstream stages
- `messages`
  - workflow memory
- `traces`
  - technical execution record

## 7. Architect

Files:

- `app/agents/architect.py`
- prompt: `app/prompts/architect.txt`

Responsibilities:

- takes `requirements`
- produces a high-level architecture plan
- can revise the plan using planning feedback from a previous review cycle

Reads from state:

- `user_task`
- `requirements`
- `planning_feedback`
- `planning_iteration`
- `max_planning_iterations`
- `benchmark_name`
- `benchmark_context`

Writes to state:

- `planning_iteration`
- `architecture_plan`
- `messages`
- `traces`

Interpretation:

- requirement analyzer says what the system should do
- architect says how it should be structured

## 8. Planning Reviewer

Files:

- `app/agents/planning_reviewer.py`
- prompt: `app/prompts/planning_reviewer.txt`

Responsibilities:

- reviews the architecture plan before coding starts
- acts as a quality gate for the planning phase

Reads from state:

- `requirements`
- `architecture_plan`
- `planning_iteration`
- `max_planning_iterations`
- `benchmark_name`
- `benchmark_context`

Writes to state:

- `review_status`
- `planning_feedback`
- `messages`
- `traces`

Decision model:

- if output contains `approved`, MASS interprets that as approval
- otherwise it is treated as revision needed

Routing:

- `approved` -> `coder`
- otherwise -> back to `architect`

## 9. Coder

Files:

- `app/agents/coder.py`
- prompt: `app/prompts/coder.txt`

Responsibilities:

- generates the actual project files
- writes them under `generated_project`
- validates local technical plausibility immediately after generation

Reads from state:

- `user_task`
- `requirements`
- `architecture_plan`
- `reviewer_feedback`
- `validation_results`
- `test_status`
- `coding_iteration`
- `benchmark_name`
- `benchmark_context`
- `skip_internal_tests`

On later iterations it also reads the current project snapshot:

- full project snapshot, or
- focused snapshot based on known error paths

### Structured output

The coder expects a JSON-like payload with:

- `summary`
- `files`

Each file has:

- `path`
- `content`

The coder also contains JSON repair logic for malformed model output.

### Local technical checks after generation

Immediately after writing files, the coder performs local checks.

These are not the benchmark validators. They are pre-validation checks intended to catch obviously broken outputs early.

The checks are implemented via:

- `app/tools/file_tools.py`

#### 1. Python syntax validation

Method:

- `validate_python_syntax(...)`

Behavior:

- inspects only written `.py` files
- runs `py_compile.compile(...)`
- collects syntax errors with path and message

This catches things like:

- `SyntaxError`
- indentation problems
- malformed strings
- broken parentheses

#### 2. Framework sanity validation

Method:

- `validate_framework_sanity(...)`

This currently focuses mostly on Django-like structures.

Examples:

- if `settings.py` exists but `manage.py` is missing, flag an error
- if `manage.py` exists but has no `DJANGO_SETTINGS_MODULE`, flag an error
- if admin route is used but `django.contrib.admin` is missing from `INSTALLED_APPS`, flag an error
- if `DATABASES` is declared without `ENGINE`, flag an error
- run a Django smoke check:
  - `manage.py migrate --noinput`
  - `django.test.Client().get('/')`

#### 3. Summary building

After syntax and framework sanity are merged, the coder writes:

- `artifacts/implementation_summary.md`

This summary includes:

- generated file list
- syntax status
- any collected local errors


Writes to state:

- `coding_iteration`
- `implementation_summary`
- `lint_results`
- `artifacts`
- `files_touched`
- `messages`
- `traces`

## 10. Benchmark Validators

The benchmark validator is separate from the coder's local lint-like checks.

The coder asks:

- "Is the project obviously broken?"

The benchmark validator asks:

- "Is the project structurally aligned with what ProjectEval expects?"

Routing into validator:

- `app/graph/routing.py`

If `project_type == "website"`:

- `web_benchmark_validator`

Otherwise:

- `batch_benchmark_validator`

### 10.1 Web Benchmark Validator

File:

- `app/validation/web_benchmark_validator.py`

Responsibilities:

- deterministic structural checks for website projects
- verifies benchmark-facing DOM structure and selector contracts

Reads:

- generated `.html` and `.py` files
- `benchmark_context`
- in the original MASS setup, also direct `testcode`

Common checks:

- Django bootstrap sanity
- duplicate ids
- expected selectors exist
- selector control types are correct
  - input
  - select
  - button/link
  - display container
- hidden or conditionally rendered evaluator-facing elements
- semantic navigation expectations such as expected URLs

Output:

- `success`
- `issues`
- `summary`
- `fix_hints`

### 10.2 Batch Benchmark Validator

File:

- `app/validation/batch_benchmark_validator.py`

Responsibilities:

- deterministic structural checks for non-website benchmark projects

Typical checks:

- Python sources exist when stack requires them
- some batch entrypoint exists
  - `main.py`
  - `app.py`
  - `run.py`
  - `__main__`
  - `argparse`
  - `sys.argv`
- expected output artifact names appear in source
- some evidence of error handling exists if benchmark descriptions imply invalid/error flows

Output:

- `success`
- `issues`
- `summary`
- `fix_hints`

### Validator node wrappers in builder

The validator nodes in `builder.py`:

- emit observability events
- call the deterministic validator functions
- translate success/failure into:
  - `validation_results`
  - `validation_status`
  - `review_status`
  - `reviewer_feedback`

If validation fails:

- `validation_status = changes_requested`

If it passes:

- `validation_status = passed`

## 11. Reviewer

Files:

- `app/agents/reviewer.py`
- prompt: `app/prompts/reviewer.txt`

Responsibilities:

- converts technical validation output into feedback the coder can act on
- performs quality review when deterministic validation already passed
- can approve the implementation for termination

Reads from state:

- `validation_status`
- `validation_results`
- `lint_results`
- `implementation_summary`
- `architecture_plan`
- `coding_iteration`
- `max_coding_iterations`
- `benchmark_name`
- `benchmark_context`

### Fast path on lint errors

If local `lint_results` already contain errors, the reviewer skips the LLM call and immediately returns:

- `review_status = changes_requested`
- direct technical feedback

### Two operating modes

#### `validation_fix_advisor`

Used when:

- `validation_status == changes_requested`

Behavior:

- collects focused relevant files
- looks at validator issues and fix hints
- gives targeted instructions for the coder
- always returns `changes_requested`

This mode cannot approve the project.

#### `quality_review`

Used when:

- deterministic validation passed

Behavior:

- reviews touched files plus key entrypoints
- performs higher-level quality review against implementation and architecture
- can approve or request changes

Decision convention:

- if output contains `approved`, MASS treats it as approval
- otherwise it is treated as `changes_requested`

Writes to state:

- `review_status`
- `reviewer_feedback`
- `messages`
- `traces`

Routing after reviewer:

- `approved` -> `finalizer`
- otherwise -> back to `coder` unless coding budget is exhausted

## 12. Finalizer

The finalizer is not an LLM agent. It is a workflow node defined inline in:

- `app/graph/builder.py`

Responsibilities:

- interprets final technical state
- computes workflow outcome
- writes `artifacts/final_report.json`

Reads from state:

- `global_iteration`
- `lint_results`
- `validation_results`
- `skip_internal_tests`
- `workspace`
- `requirements`
- `architecture_plan`
- `implementation_summary`
- `review_status`
- `traces`
- `artifacts.generated_root`

### What it decides

It produces a technical final status such as:

- `passed`
- `failed_bug`
- `failed_validation`
- `failed_architecture`

Then it maps that into workflow-level status such as:

- `completed`
- `incomplete`

### Output

Main artifact:

- `artifacts/final_report.json`

State updates include:

- `test_results`
- `test_status`
- `final_status`
- `final_output_path`
- updated `artifacts`
- updated `messages`
- updated `traces`

## 13. What Happens After the Finalizer

Inside a ProjectEval run, the finalizer is not the end of the benchmark pipeline.

After `run_workflow(...)` returns `final_state`, control goes back to:

- `app/benchmark/projecteval_runner.py`

Then MASS:

1. reads `generated_root`
2. converts the generated project into exportable benchmark JSON
3. computes benchmark metadata
4. exports the run in ProjectEval format
5. optionally launches the official judge
6. collects benchmark scores

So:

- finalizer closes the workflow
- `projecteval_runner.py` closes the benchmark pipeline

## 14. Parameter Solver and Parameter Repairer

These components are used in ProjectEval post-processing, not as nodes inside the main LangGraph workflow.

Relevant role names:

- `parameter_solver`
- `parameter_repairer`

These roles are configured in the model config YAML files.

### What they do

After the project has been generated, MASS still needs benchmark metadata such as:

- parameter values
- startfile
- information block

This is where:

- `solve_parameters(...)`
- `repair_parameter_response(...)`

come in.

#### Parameter Solver

Responsibilities:

- infer values needed by ProjectEval from generated project code
- produce structured JSON parameter answers

Examples:

- ids
- URLs
- xpaths
- class names
- paths

#### Parameter Repairer

Responsibilities:

- repair malformed JSON output from parameter solving
- preserve intended parameter content while restoring schema compliance

This is not a conceptual reviewer of the app. It is a structured-output repair stage.

### Output files

The benchmark post-processing writes workspace cache files such as:

- `projecteval_parameter_values.json`
- `projecteval_information.json`
- `projecteval_startfile.txt`

## 15. How Benchmark Scores Are Computed

After workflow completion and metadata preparation, `projecteval_runner.py` exports the run and can invoke the official ProjectEval judge:

- `run_judge.py`

This happens through:

- `maybe_run_projecteval_script(...)`

Then MASS extracts:

- `judge_project_scores`
- `judge_function_details`
- `judge_score_row`
- `fixed_pass_at_1`

For a single project, the most directly useful fields are stored in:

- `per_project_results[project_id]["judge_score"]`
- `per_project_results[project_id]["judge_details"]`

These are also written into:

- `per_project_results.json`
- `run_summary.json`

So to inspect benchmark performance for one project, the important outputs are:

- project-level score
- function-level judge details


## 16. End-to-End Summary

The active MASS flow for ProjectEval is:

1. UI starts benchmark through `BenchmarkRunner`
2. `projecteval_runner.py` selects projects and builds benchmark-aware tasks
3. `run_workflow(...)` initializes state and runs LangGraph
4. `requirement_analyzer` structures requirements
5. `architect` generates an architecture plan
6. `planning_reviewer` approves or requests revisions
7. `coder` writes project files and runs local technical checks
8. deterministic benchmark validator checks benchmark-facing structure
9. `reviewer` either advises fixes or approves
10. `finalizer` writes `final_report.json`
11. `projecteval_runner.py` exports benchmark artifacts
12. parameter solver and parameter repairer compute benchmark metadata
13. ProjectEval judge computes official benchmark scores

## 17. Important Files

- `app/main.py`
- `app/workflow.py`
- `app/graph/state.py`
- `app/graph/builder.py`
- `app/graph/routing.py`
- `app/agents/base_agent.py`
- `app/agents/requirement_analyzer.py`
- `app/agents/architect.py`
- `app/agents/planning_reviewer.py`
- `app/agents/coder.py`
- `app/agents/reviewer.py`
- `app/tools/file_tools.py`
- `app/validation/web_benchmark_validator.py`
- `app/validation/batch_benchmark_validator.py`
- `app/benchmark/projecteval_runner.py`
- `app/ui_backend/benchmark_runner.py`
- `app/ui_backend/models.py`
