# deck_context — source material for the MASS thesis presentation

Curated, fact-checked context to feed **Claude design** (claude.ai) for generating the
slide deck. All numbers are extracted from the codebase and session logs (verified
2026-06-22). Deck language: **English**. Audience: seminar / thesis defense (medium depth).

## How to use
1. Open a new chat on claude.ai.
2. Attach (or paste, in order) `00_storyline.md` → `05_token_analysis.md` and
   `assets/architecture_diagram.svg`.
3. Paste the prompt from `PROMPT.md`.

## Files
- `00_storyline.md` — master outline + slide-by-slide skeleton (the narrative).
- `01_architecture.md` — agents, shared state, orchestration, loops, prompts.
- `02_tooling_and_loops.md` — verification layer (static / dynamic / Selenium), agentic
  tool/ReAct loop, memory & checkpoints, robustness.
- `03_methodology_mix.md` — the 3 configurations, role→model mapping, ProjectEval benchmark.
- `04_results.md` — official score / results and interpretation.
- `05_token_analysis.md` — tokens per agent / per session, cost-vs-quality.
- `PROMPT.md` — the prompt to paste into Claude design.
- `assets/architecture_diagram.svg` — the 10-node agent graph (model color-coded).

## Underlying sources
- Architecture: `app/graph/builder.py`, `app/graph/routing.py`, `app/agents/*`,
  `app/tools/agent_tools.py`, `app/prompts/*`.
- Results: `sessions/{mixed_m3_qwen3.6_final,qwen3.6_27b_final_MAS,multi_agent_m3_final}/results.json`.
- Tokens: `sessions/*/project_*/artifacts/agent_transcripts/*.json` and the per-session
  `token_usage_report.md`.
