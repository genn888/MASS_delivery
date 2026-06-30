# Experimental Methodology — The Mixture-of-Models Study

> Source for the experimental-design slides. Configuration facts from
> `sessions/*/models_config.generated.yaml`; benchmark facts from `app/benchmark/`.

## 1. The core hypothesis

> Model choice should be a **per-role decision**, not a global one. Planning/review roles are
> reasoning-bound and benefit from a stronger model; coding/testing roles are volume-bound and
> are better served by an efficient code model. A **per-role mixture** should dominate either
> homogeneous baseline on quality, without paying the stronger model's full cost.

## 2. The three configurations (matched runs)

Same architecture, same 20 ProjectEval projects, same iteration caps — only the
**role → model mapping** changes.

| Role | Qwen-only | M3-only | **Mixed (contribution)** |
|---|---|---|---|
| requirement_analyzer | Qwen3.6-27B | MiniMax-M3 | **MiniMax-M3** |
| architect | Qwen3.6-27B | MiniMax-M3 | **MiniMax-M3** |
| planning_reviewer | Qwen3.6-27B | MiniMax-M3 | **MiniMax-M3** |
| coder | Qwen3.6-27B | MiniMax-M3 | **Qwen3.6-27B** |
| reviewer | Qwen3.6-27B | MiniMax-M3 | **Qwen3.6-27B** |
| test_writer | Qwen3.6-27B | MiniMax-M3 | **Qwen3.6-27B** |
| browser_test_writer | Qwen3.6-27B | MiniMax-M3 | **Qwen3.6-27B** |

**Rationale of the split:** MiniMax-M3 (the stronger reasoner) handles the *planning brain*
— requirements, architecture, plan review. Qwen3.6-27B (efficient code model) handles the
*production line* — coding, review, and test authoring, which together account for the vast
majority of calls and tokens.

Session names:
- `qwen3.6_27b_final_MAS` — homogeneous Qwen3.6-27B
- `multi_agent_m3_final` — homogeneous MiniMax-M3
- `mixed_m3_qwen3.6_final` — the mixture-of-models

## 3. Model setup (from config)

| Model | Serving | Notes |
|---|---|---|
| **Qwen3.6-27B** | local vLLM (HPC UNISA, `localhost:8003`) | temperature 0.0–0.2 per role; `max_context` 262k; coder `max_tokens` 65k |
| **MiniMax-M3** | HuggingFace Router / Together (`router.huggingface.co`) | `max_context` 204k; long request timeouts (1500s) due to slow generation |

Both expose `supports_json: true`, `supports_system_prompt: true`. JSON-mode response format
is used wherever the model supports it.

## 4. Benchmark — ProjectEval

- **20 real software projects** (Level 2), each with an **external automated judge** that
  scores functional correctness (pages/selectors/URLs/expected text/output files).
- Metrics reported:
  - **`official_score`** — the external judge's function-level pass rate (the headline metric;
    out of 284 judge functions total). In this work this IS our pass@1.
  - **completion rate** — fraction of projects the system marked completed locally.
  - **`average_project_score`** — mean per-project judge score.
- The judge is the **independent arbiter** — the system cannot game it (the contract is
  treated as externally owned throughout).

## 5. Why this is a fair comparison

- Identical agent graph, prompts, tools, iteration caps, and benchmark for all three runs.
- The **only** variable is which model serves which role.
- Cost is measured from the same source (on-disk transcripts), counted identically for all
  three runs (see `05_token_analysis.md`).
