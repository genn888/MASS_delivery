# PROMPT — paste this into Claude (Claude design / canvas) together with the context files

> **How to use:** open a new chat on claude.ai, attach the files `00_storyline.md` …
> `05_token_analysis.md` from this folder (and `assets/architecture_diagram.svg`), then paste
> the prompt below. If a tool/file size limit applies, paste the files' content inline in the
> order 00 → 05.

---

## PROMPT

You are an expert presentation designer and ML systems communicator. Using ONLY the attached
context files as the source of truth, design a polished, defense-ready slide deck for my
master's thesis.

**Topic:** MASS — a heterogeneous multi-agent system that turns a natural-language task into
verified, runnable software. My main contribution is a **mixture-of-models** study: assigning
a stronger reasoning model (MiniMax-M3) to planning roles and an efficient code model
(Qwen3.6-27B) to coding/testing roles, and showing the mix beats either homogeneous setup.

**Audience & tone:** academic seminar / thesis defense. Medium technical depth: slides should
be clean and visual (one idea per slide); put deeper technical detail in **speaker notes**.

**Language:** English.

**Deliverable:** a complete slide deck. Follow the slide-by-slide skeleton in
`00_storyline.md` (~20 main slides + 4 backup). For EACH slide give me:
1. a concise title,
2. 3–6 bullet points (short, telegraphic — not paragraphs),
3. a clear description of the visual/diagram/chart to place on that slide,
4. speaker notes (2–4 sentences of the deeper detail).

**Hard requirements:**
- Treat every number as ground truth from the files — do NOT invent or round away figures.
  Reproduce the key tables exactly (results in `04`, token tables in `05`).
- The **architecture diagram** (slide 4) is the centerpiece: render the 10-node agent graph
  (requirement_analyzer → benchmark_contract → architect ↔ planning_reviewer → coder →
  static_analysis → test_writer → browser_test_writer → reviewer → finalizer) showing the two
  iterative loops (planning loop, coding/repair loop) and color-coding which model serves each
  role in the Mixed config (M3 = planning roles, Qwen = coding/testing roles). You may base it
  on `assets/architecture_diagram.svg`.
- Include these charts (describe them precisely so I can build them):
  - grouped bar: official score & avg project score for Qwen / M3 / Mixed (slide 16),
  - 100%-stacked bar of tokens per agent showing the coder dominating ~75–80% (slide 18),
  - cost-vs-quality scatter: x = total tokens, y = official score, 3 points (slide 19).
- Devote real estate to: agent-by-agent roles, the iterative loops, memory/checkpoints/
  transcripts, modular contract-locked prompts, and the verification layer (static analysis,
  dynamic pytest, Selenium browser tests, agentic tool/ReAct loop).
- End with 3 takeaways: (1) separation of concerns + executable verification, (2) model choice
  is per-role not global, (3) the coder loop dominates cost.

**Design system:**
- Academic, minimal, high-contrast. One accent color for "Mixed" (the contribution) used
  consistently to make our config pop in every chart.
- Use a 2-color scheme to distinguish the two models everywhere (e.g. M3 = blue family,
  Qwen = green family); keep it consistent between the architecture diagram and the charts.
- Readable from the back of a room: large type, minimal text per slide, generous whitespace.
- Consistent iconography for agents; consistent layout grid.

First, restate the deck outline you'll produce (titles only) so I can confirm. Then produce
the full slide content.

---

## Optional follow-ups to ask Claude after the first pass
- "Generate the deck as an HTML/reveal.js presentation I can export to PDF."
- "Produce the architecture diagram as standalone SVG with the model color-coding."
- "Tighten every slide to max 5 bullets and move overflow to speaker notes."
- "Make a 5-minute version (10 slides) and a full 20-minute version."
