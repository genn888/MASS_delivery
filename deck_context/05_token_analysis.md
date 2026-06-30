# Token Analysis — Where the Budget Goes

> Source for the cost slides. All numbers recomputed **uniformly** across the three sessions
> from on-disk transcripts (`*/artifacts/agent_transcripts/*.json`, field `usage`) on
> 2026-06-23 (after re-running M3's outlier project_18 under the 50-step cap), so the three
> runs are directly comparable. (Note: per-session
> `token_usage_report.md` files exist too, but earlier ones counted a slightly different
> transcript set; the tables here are the canonical, like-for-like numbers for the deck.)

## 1. Session totals

| Configuration | Model calls | Input tokens | Output tokens | **Total tokens** |
|---|---:|---:|---:|---:|
| Qwen3.6-27B (homogeneous) | 490 | 8,397,930 | 899,231 | **9,297,161** |
| MiniMax-M3 (homogeneous) | 667 | 12,597,940 | 591,702 | **13,189,642** |
| **Mixed (M3 planning + Qwen coding)** | 498 | 8,967,490 | 910,240 | **9,877,730** |

Observations:
- **Qwen-only is the cheapest** (~9.30M) but also the lowest quality.
- **Mixed (~9.88M) costs LESS than M3-only (~13.19M)** while scoring higher — the
  mix is strictly better than M3-everywhere on this benchmark (more quality, fewer tokens).
- M3 has the most calls (667) and an extreme input/output ratio (~21:1) — its agentic loop
  accumulates lots of context and emits little per turn.

## 2. Tokens per agent (total tokens, with call count)

| Agent | Qwen-only | M3-only | Mixed |
|---|---:|---:|---:|
| coder | 6,591,957 (285) | 9,482,687 (421) | 6,604,547 (288) |
| reviewer | 845,841 (69) | 2,037,091 (123) | 1,197,818 (77) |
| test_writer | 933,298 (43) | 769,166 (36) | 1,155,047 (45) |
| browser_test_writer | 302,334 (16) | 322,890 (16) | 349,571 (16) |
| architect | 384,028 (37) | 354,854 (31) | 352,621 (32) |
| planning_reviewer | 164,891 (20) | 172,439 (20) | 166,953 (20) |
| requirement_analyzer | 74,812 (20) | 50,515 (20) | 51,173 (20) |

**The single biggest insight:** the **Coder dominates the budget** in every configuration:
- Qwen-only: coder = **70.9%** of all tokens
- M3-only: coder = **71.9%**
- Mixed: coder = **66.9%**

Planning agents (requirement_analyzer + architect + planning_reviewer) together are only
**~4.4–5.8%** of the budget in MiniMax/Mixed (and ~6.7% in Qwen-only) — i.e. **upgrading the planning models to M3 is almost free** in
token terms, yet it lifts quality. This is the quantitative backbone of the mixture argument:
*spend the strong model on the cheap-but-high-leverage planning roles; keep the efficient
model on the expensive coding loop.*

> Suggested chart: 100%-stacked horizontal bar per configuration, segments = agents, coder
> segment emphasized. Or a single "coder ≈ 67–72% of all tokens" callout.

## 3. Cost vs quality (the decision slide)

| Configuration | Total tokens (M) | Official score | Official score per 1M tokens |
|---|---:|---:|---:|
| Qwen-only | 9.30 | 0.504 | 0.0542 |
| M3-only | 13.19 | 0.518 | 0.0393 |
| **Mixed** | 9.88 | 0.570 | 0.0577 |

Reading:
- **Mixed dominates M3-only on both axes** — higher score *and* fewer tokens.
- **Qwen-only is the most token-efficient per quality point** (cheapest path to a "good
  enough" result), but tops out at the lowest absolute quality.
- The practical takeaway: if quality is the goal, **Mixed is the efficient frontier point**
  — it gets the best score for less than the all-strong-model cost.

> Suggested chart: scatter / quadrant, x = total tokens (cost), y = official score; three
> points labelled. Mixed sits up-and-left of M3 (better and cheaper); Qwen sits low-left.

## 4. Per-project token cost (backup material)

Per-project token totals are available in each session's `token_usage_report.md`
(e.g. for Qwen-only: project_20 = 1.56M tokens / 51 calls is the most expensive,
project_15 = 65.5k the cheapest; mean ≈ 464.9k tokens / ~24 calls). Use these for a
"token cost varies 50× across projects; retries on hard projects drive the tail" backup slide.

Per-project tables live at:
- `sessions/qwen3.6_27b_final_MAS/token_usage_report.md`
- `sessions/multi_agent_m3_final/token_usage_report.md`
- `sessions/mixed_m3_qwen3.6_final/token_usage_report.md` (regenerated for this deck)
