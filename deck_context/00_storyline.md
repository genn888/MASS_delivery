# Presentation Storyline — MASS: Mixture-of-Models for a Multi-Agent Software Factory

> This file is the **master outline** for the deck. It defines the narrative arc and a
> slide-by-slide skeleton. The other files (`01_*`–`05_*`) provide the detailed source
> material the slide generator should pull from. Deck language: **English**. Audience:
> seminar / thesis-defense (medium technical depth — clear diagrams and highlights on
> slides, deep detail in speaker notes and backup slides).

## One-sentence thesis

A heterogeneous **multi-agent system (MASS)** turns a natural-language task into a
verified, runnable software project; the central contribution is showing that a
**mixture-of-models** — assigning a stronger reasoning model to planning roles and an
efficient code model to coding/testing roles — **beats either homogeneous configuration**
on the ProjectEval benchmark, at comparable or lower cost.

## The narrative arc (the "why this matters")

1. **Problem** — Single-LLM code generation is brittle: no separation of concerns, no
   verification loop, no cost control. ProjectEval (20 real projects, external judge) is hard.
2. **Idea** — Decompose software construction into specialized agents in a stateful graph,
   with iterative review loops and *executable* verification (static analysis, dynamic
   pytest, Selenium browser tests).
3. **Contribution** — Not all roles need the same model. Planning/review roles benefit from
   a stronger reasoner (MiniMax-M3); coding/testing roles are dominated by volume and are
   better served by an efficient code model (Qwen3.6-27B). **Mix them per role.**
4. **Evidence** — Three matched runs (Qwen-only, M3-only, Mixed) on the same 20 projects.
   Mixed wins on official judge score and average project score.
5. **Cost lens** — Token accounting per agent / per project / per session shows *where* the
   budget goes (the coder loop dominates) and that the mix buys quality without M3-level cost.

## Slide-by-slide skeleton (~20 slides + backup)

| # | Slide | Source file | Visual |
|---|---|---|---|
| 1 | Title — MASS: Mixture-of-Models for Multi-Agent Code Generation | — | clean title, author, university, date |
| 2 | The problem: from prompt to *verified* software | 00 | before/after or pain-points icons |
| 3 | Contribution at a glance (the money slide, teaser) | 04 | 3-bar chart: official score Qwen vs M3 vs Mixed |
| 4 | System overview — the agent graph | 01 | **architecture diagram (centerpiece)** |
| 5 | Shared state & orchestration (LangGraph) | 01 | state object + node/edge schematic |
| 6 | Agent 1–2: Requirement Analyzer + Benchmark Contract | 01 | role cards |
| 7 | Agent 3–4: Architect + Planning Reviewer (planning loop) | 01 + 02 | loop diagram |
| 8 | Agent 5: Coder (the engine) | 01 + 02 | role card + JSON/agentic toggle |
| 9 | Verification layer: static → dynamic → browser | 02 | 3-stage pipeline |
| 10 | Agent: Reviewer (the fix-advisor loop) | 01 + 02 | analysis-fix vs quality-review modes |
| 11 | Tools in coding/testing agents (agentic ReAct loop) | 02 | tool registry diagram |
| 12 | Memory, checkpoints & transcripts | 02 | layered persistence |
| 13 | Prompt engineering: modular, contract-locked prompts | 01 | prompt-composition diagram |
| 14 | Experimental design: 3 configurations | 03 | role→model assignment matrix |
| 15 | Benchmark: ProjectEval + external judge | 03 | benchmark facts |
| 16 | Results: official score & avg score | 04 | grouped bar chart |
| 17 | Results: per-project consistency | 04 | per-project comparison |
| 18 | Token analysis: where the budget goes | 05 | stacked bar per agent |
| 19 | Token analysis: cost vs quality | 05 | scatter / quadrant (cost x score) |
| 20 | Conclusions & future work | 00 | takeaways |
| B1–B4 | Backup: full prompts, full token tables, graph routing rules, per-project tables | 01/02/05 | tables |

## Three takeaways the audience must remember

- **Separation of concerns + executable verification** makes LLM code generation reliable.
- **Model choice is a per-role decision**, not a global one — the mix dominates.
- **The coder loop dominates cost** (~67–72% of tokens); that is where optimization pays off.
