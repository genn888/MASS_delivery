# Experimental Results

> Source for the results slides. Numbers extracted from each session's
> `results.json` → `aggregate` block (verified on 2026-06-23). 20 projects, 284 judge
> functions per run.

## 1. Headline — the mixture wins (the money slide)

> Note on terminology: in this work the **official score IS our pass@1** (external judge
> function-level pass rate). The term "pass@1" is therefore avoided in the deck to prevent
> confusion; "completion rate" below is the separate local project-completion fraction.

| Configuration | Official score | Avg project score | Completion rate | Judge functions passed |
|---|---:|---:|---:|---:|
| Qwen3.6-27B (homogeneous) | 0.504 | 0.589 | 0.70 | 143 / 284 |
| MiniMax-M3 (homogeneous) | 0.518 | 0.599 | 0.80 | 147 / 284 |
| **Mixed (M3 planning + Qwen coding)** | **0.570** | **0.658** | **0.80** | **162 / 284** |

**Reading of the result:**
- The **Mixed configuration is best on every quality metric.**
- Mixed vs Qwen-only: **+6.6 points** of official score (0.570 vs 0.504), +19 judge functions.
- Mixed vs M3-only: **+5.2 points** of official score and a higher average project score
  (0.658 vs 0.599) — i.e. the mix beats even the strong model used everywhere.
- Mixed and M3-only both reach 0.80 completion rate (16/20) vs 0.70 for Qwen-only, suggesting
  **planning quality (where M3 sits in the mix) lifts completion**.

> Suggested chart: grouped bar, three bars (Qwen / M3 / Mixed), series = official score and
> average project score. Highlight the Mixed bars.

## 2. Interpretation — *why* the mix wins

- The **planning brain matters disproportionately**: putting the stronger reasoner (M3) on
  requirements + architecture + plan review produces better, more contract-complete plans, so
  the Coder starts from a stronger spec.
- The **production line is volume-bound**: coding/review/testing are dominated by call count
  and token volume; the efficient code model (Qwen) handles them well and cheaply.
- The mix captures **the best of both**: M3's reasoning where it counts, Qwen's efficiency
  where the volume is — and the combination exceeds M3-everywhere on average project score.

## 3. Honesty / caveats (good for a defense)

- Runs left 4–6 of 20 projects pending/incomplete (completed_projects: Mixed 16,
  M3 16, Qwen 14) — the comparison is on the same benchmark under the same caps.
- Margins between Mixed and M3-only are +5.2 pts on official score and consistent
  across average project score and completion rate; the stronger separation is against Qwen-only.
- The decisive practical argument is **cost-adjusted** (see `05_token_analysis.md`): the mix
  matches/beats M3 quality at materially lower planning-side intensity.

## 4. Raw aggregate (for backup slide)

```
mixed_m3_qwen3.6_final : completed=16/20 completion=0.80 official=0.570 avg=0.658 judge_passed=162/284
multi_agent_m3_final   : completed=16/20 completion=0.80 official=0.518 avg=0.599 judge_passed=147/284
qwen3.6_27b_final_MAS  : completed=14/20 completion=0.70 official=0.504 avg=0.589 judge_passed=143/284
```
