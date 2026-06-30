# Architecture — Agents, State, and Orchestration

> Source of truth for the architecture slides. All facts below are extracted from the
> codebase (`app/graph/builder.py`, `app/graph/routing.py`, `app/agents/*`,
> `app/prompts/*`). Keep slide text concise; push detail into speaker notes.

## 1. System overview

MASS is a **stateful multi-agent graph** built on **LangGraph** (`StateGraph`). A single
shared, typed state object (`GraphState`) flows through a series of specialized agent
nodes connected by **conditional edges** (routing functions). Each agent reads what it
needs from the state and returns a partial update; the graph decides the next node.

The pipeline turns one natural-language task into a **verified, runnable project** plus a
`final_report.json`. Every model call is persisted as a transcript for full reproducibility.

**Node set (10 nodes):**
`requirement_analyzer → benchmark_contract → architect ↔ planning_reviewer → coder →
static_analysis → test_writer → browser_test_writer → reviewer → finalizer`

## 2. Shared state (GraphState)

The state is the single integration point between agents (no direct agent-to-agent calls).
Key fields the agents read/write:

- `user_task`, `requirements`, `architecture_plan`, `implementation_summary`
- `benchmark_contract` / `benchmark_contract_compact` (the external judge contract)
- `reviewer_feedback`, `review_status` (`approved` / `changes_requested`)
- `lint_results`, `static_analysis_results`, `dynamic_test_results`, `browser_test_results`
- iteration counters: `planning_iteration`, `coding_iteration`, `global_iteration`
- limits: `max_planning_iterations`, `max_coding_iterations`, `max_global_iterations`
- `files_touched`, `artifacts`, `traces`, `messages`
- feature flags: `use_agentic_tools`, `run_static_analysis`, `run_dynamic_analysis`,
  `skip_internal_tests`

## 3. The agents (role by role)

Each agent has a **strict role boundary** enforced in its system prompt. Planning agents
are explicitly forbidden from emitting code; only the Coder writes files.

### Agent 1 — Requirement Analyzer
- **Input:** raw user task. **Output:** structured requirements (scope, functional /
  non-functional requirements, constraints, open assumptions).
- Compact, code-free; output is designed to be passed straight to the Architect.
- Cheapest agent: ~1 call per project, tiny input.

### Agent 2 — Benchmark Contract
- Builds a compact, machine-readable **contract** from the benchmark spec: required URLs,
  selectors, expected texts, output files, project type, technical stack.
- This contract is the "ground truth" every downstream agent must satisfy and must treat as
  **externally owned** (never edit it as a repair).

### Agent 3 — Architect
- Produces an **implementation-ready architecture plan**: components & responsibilities,
  shared-state usage, workflow phases, iteration strategy, artifact strategy, failure
  handling.
- Contract-aware: maps every contract URL/selector/text to a concrete implementation path;
  optimizes for **observability and stable state transitions** (multi-page, stable URLs,
  static-DOM elements) so the external judge can verify deterministically.
- Larger token budget than other planners (up to 32k output) — it does the heavy reasoning.

### Agent 4 — Planning Reviewer
- Reviews the architecture plan against requirements **before any code is written**.
- Returns `Approved: ...` or `Changes requested: ...`, focusing on missing components, weak
  iteration logic, unclear routing, contract-coverage gaps.
- Drives the **planning loop** (see §4).

### Agent 5 — Coder (the engine)
- Generates / repairs the full project. Two execution modes:
  - **Structured-JSON mode (default):** returns one JSON object `{summary, delete_paths,
    files:[{path,content}]}`; the system writes the files.
  - **Agentic tool mode (`use_agentic_tools`):** the model builds the project by *calling
    tools* (`write_file`, `read_file`, `list_files`, `grep`, `validate_python`,
    `django_check`, `run_pytest`) in a ReAct loop (up to 50 tool steps).
- On iteration 1 it writes a complete runnable project; on later iterations it patches only
  the files implicated by the failure digest (focused subset) — a key cost optimization.
- After writing, the system always re-validates syntax + framework sanity as a safety net.

### Agent 6 — Reviewer
- Two modes selected automatically from state:
  - **`analysis_fix_advisor`** (when lint / static analysis failed): acts as a fix advisor,
    returns ≤4 blocking items, ≤1200 chars, each with classification + file + cause + exact
    fix. Always forces `changes_requested` to route back to the Coder.
  - **`quality_review`** (when analysis is clean): correctness + completeness review with a
    **contract-coverage gate** — every page/selector/URL/expected-text/output-file must be
    implemented, or it returns `changes_requested`.
- Drives the **coding/repair loop** (see §4).

### Test agents (the verification layer) — see `02_tooling_and_loops.md`
- **Test Writer** — generates and runs a small project-owned **pytest** suite (dynamic test).
- **Browser Test Writer** — generates and runs a small **Selenium** suite for web projects.
- **Static Analysis** (deterministic node, not an LLM) — `analyze_generated_project`.

### Finalizer (deterministic node)
- Aggregates lint / static / dynamic / browser outcomes into a single `test_status`
  (`passed`, `failed_bug`, `failed_architecture`, `failed_validation`) and `final_status`,
  writes `final_report.json`, and marks the workflow checkpoint complete.

## 4. Iterative loops (the heart of the system)

Two nested review loops, each bounded by an iteration cap to guarantee termination:

**Planning loop** (`route_after_architect`, `route_after_planning_review`):
```
architect → planning_reviewer → (approved? → coder) | (changes? → architect)
            until planning_iteration >= max_planning_iterations
```

**Coding / repair loop** (`route_after_reviewer` + analysis routing):
```
coder → static_analysis → test_writer → [browser_test_writer if website] → reviewer
reviewer → (approved? → finalizer) | (changes_requested? → coder)
           until coding_iteration >= max_coding_iterations
```

Routing nuances (real, from `app/graph/routing.py` and `builder.py`):
- Internal **dynamic + Selenium tests are advisory**, not blocking: only **lint and static
  analysis** drive the mandatory analysis-fix loop. (Rationale: generated tests are often
  brittle and do not affect the official judge; treating them as blocking wasted iterations
  patching tests instead of the app.)
- Browser tests only run for `project_type == website`.
- A Django `manage.py check` failure short-circuits back to the Reviewer/Coder.

## 5. Prompt engineering (modular + contract-locked)

Prompts are **composed at runtime**, not monolithic:
- A **base role prompt** (`coder.txt`, `reviewer.txt`, …) plus **modular fragments** selected
  from the project type / stack: `coder_console.txt`, `coder_web.txt`, `coder_django.txt`,
  `coder_repair.txt` (added on repair iterations), `coder_tests.txt`, and reviewer analogues.
- A large **"contract-lock" block** (PROJECTEVAL_CONTRACT_LOCK) injects benchmark-specific
  guardrails: e.g. never use judge variable names as HTML ids, seed Django data so pages are
  non-empty, one canonical template per page, local-test-safe `ALLOWED_HOSTS`, etc.
- Strict **role boundaries** in every prompt (planners must not emit code).

This modularity means each model call sees only the rules relevant to that task type,
keeping prompts focused and tokens efficient.
