# Tooling, Verification Layer, Memory & Loops

> Source for the "tools / verification / memory" slides. Extracted from
> `app/tools/agent_tools.py`, `app/agents/coder.py`, `app/agents/test_writer.py`,
> `app/agents/browser_test_writer.py`, `app/agents/base_agent.py`, `app/graph/checkpoint.py`.

## 1. The verification layer — three executable stages

Generated code is never trusted; it is **executed and checked** in three escalating stages.
Crucially, only the first two are *blocking*; the test stages are advisory signals.

### Stage 1 — Static analysis (deterministic, blocking)
- Node `static_analysis` runs `analyze_generated_project()` over the generated root.
- Plus per-write **syntax validation** (`validate_python_syntax`) and **framework sanity**
  checks done by the Coder itself after every write.
- A failure here forces the Reviewer into `analysis_fix_advisor` mode → back to Coder.

### Stage 2 — Dynamic tests (pytest, advisory)
- The **Test Writer** agent generates a small project-owned pytest suite (smoke + behavior +
  route/selector contract tests), then the system runs it with `run_pytest_targets`.
- For Django: runs `manage.py check` first; enforces correct test setup order
  (`sys.path` → `DJANGO_SETTINGS_MODULE` → `django.setup()` → imports).
- Has a **deterministic fallback** smoke test if the model output is not valid JSON.

### Stage 3 — Selenium browser tests (advisory, websites only)
- The **Browser Test Writer** generates a small Selenium suite for 3–6 high-signal flows
  from the contract (visible DOM, navigation, click/submit, post-submit state, stable IDs).
- Robust subprocess launch policy: pick a **free localhost port at runtime** (never hard-code
  8000), start with `sys.executable`, poll until reachable or process exits, terminate
  cleanly; **skip (not fail)** if Chrome/driver unavailable.
- Tests live under `tests/browser/`; runs via `run_pytest_target`.

> **Design decision worth a slide:** dynamic + browser failures are *advisory*. They are
> brittle (click-intercepted, stale elements) and do not affect the official judge, so making
> them blocking caused the Coder to burn iterations fixing generated tests instead of the app.

## 2. The agentic tool layer (ReAct loop)

When `use_agentic_tools` is on, coding/review agents act through an **OpenAI-style function
tool registry** (`build_tool_registry`) scoped to the workspace. Every tool returns a compact
JSON string so results can be fed back as `role="tool"` messages without blowing the context.

| Preset | Tools | Used by |
|---|---|---|
| `READ_TOOLS` | `read_file`, `list_files`, `grep` | Reviewer (inspect), Coder |
| `WRITE_TOOLS` | `write_file`, `delete_path` | Coder |
| `CHECK_TOOLS` | `validate_python`, `django_check`, `run_pytest` | Coder |

- The Coder runs a ReAct loop up to **50 tool steps**; the Reviewer is capped at **15** (it
  only needs to inspect a few files and decide).
- Output budgets are enforced (e.g. 16k chars per read, 100 grep matches) so re-injected tool
  results stay small.
- The model is told to **batch parallel `write_file` calls** in one turn to cut round-trips,
  then `validate_python` / `django_check`, then stop and return a short summary.

## 3. Memory, checkpoints & transcripts (persistence)

Three layers of persistence give the system its "memory" and full reproducibility:

1. **Conversation memory (in-state):** `messages` accumulates an append-only log
   (`append_message`); `traces` records every model call (agent, role, model, usage,
   duration, finish reason). Within the agentic tool loop, stale tool results are pruned from
   the growing transcript to control context size while preserving information.
2. **Workflow checkpoints:** every node is wrapped (`_checkpointed_node`) to snapshot state
   *before* it runs (`prepare_pre_node_snapshot`, `save_checkpoint`) with a resume node, so a
   crashed/interrupted run can **resume from the last completed node** instead of restarting.
   The Coder additionally records a **code history** snapshot per iteration.
3. **Agent transcripts (on disk):** every single model call is written to
   `artifacts/agent_transcripts/NN_<timestamp>_<Agent>_<role>.json` containing the full
   system prompt, user prompt, response, finish reason, configured/resolved model, and
   **token `usage`**. These transcripts are exactly what powers the token analysis in
   `05_token_analysis.md`.

## 4. Robustness: retries, JSON repair, timeout recovery

- `generate_parsed_payload_with_retries` retries with an explicit "return valid JSON only"
  instruction; `_repair_common_json_issues` fixes common malformed-JSON patterns from long
  outputs (trailing commas, broken object separators).
- The Coder has a **timeout-recovery path**: on a provider timeout in a repair iteration it
  retries with a smaller, failure-localized file subset.
- Test writers fall back to deterministic generic tests if the model output cannot be parsed.

## 5. Termination guarantees

Every loop is bounded: planning, coding, and global iteration counters with hard caps.
When caps are hit, routing always converges to the `finalizer`, which emits the final report.
