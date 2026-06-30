const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.author = "Gennaro D'Ambrosio";
pres.title = "MASS — Multi-Agent Sequential System";

// ---- palette ----
const NAVY = "0F172A";
const SLATE = "1E293B";
const MUTED = "64748B";
const LIGHT = "F1F5F9";
const CARDBG = "F8FAFC";
const WHITE = "FFFFFF";
const M3 = "2563EB";       // MiniMax-M3 (planning)
const M3BG = "DBEAFE";
const QWEN = "16A34A";     // Qwen3.6 (coding/testing)
const QWENBG = "DCFCE7";
const DET = "64748B";      // deterministic node
const DETBG = "E2E8F0";
const ACCENT = "F59E0B";   // Mixed / the contribution
const ACCENTD = "B45309";

const HFONT = "Georgia";
const BFONT = "Calibri";
const W = 13.33, H = 7.5;
const ML = 0.6;

const mkShadow = () => ({ type: "outer", color: "000000", blur: 7, offset: 3, angle: 135, opacity: 0.12 });

let pageNo = 0;
function footer(slide, label) {
  pageNo++;
  slide.addText("MASS · Multi-Agent Sequential System", {
    x: ML, y: 7.05, w: 9, h: 0.3, fontFace: BFONT, fontSize: 9, color: MUTED, align: "left", margin: 0,
  });
  slide.addText(String(pageNo), {
    x: W - 1.1, y: 7.05, w: 0.5, h: 0.3, fontFace: BFONT, fontSize: 9, color: MUTED, align: "right", margin: 0,
  });
}

function contentHeader(slide, kicker, title) {
  slide.background = { color: WHITE };
  slide.addText(kicker.toUpperCase(), {
    x: ML, y: 0.42, w: 12, h: 0.3, fontFace: BFONT, fontSize: 12, bold: true, color: ACCENTD, charSpacing: 2, margin: 0,
  });
  slide.addText(title, {
    x: ML, y: 0.72, w: 12.1, h: 0.8, fontFace: HFONT, fontSize: 30, bold: true, color: NAVY, margin: 0,
  });
}

function node(slide, x, y, w, h, line1, line2, bg, border, opts = {}) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.06, fill: { color: bg }, line: { color: border, width: 1.75 }, shadow: mkShadow(),
  });
  const runs = [{ text: line1, options: { bold: true, fontSize: opts.fs || 12, color: opts.tc || SLATE, breakLine: !!line2 } }];
  if (line2) runs.push({ text: line2, options: { fontSize: opts.fs2 || 9.5, color: opts.tc2 || MUTED } });
  slide.addText(runs, { x, y, w, h, align: "center", valign: "middle", fontFace: BFONT, margin: 2 });
}

function arrow(slide, x, y, w, h, color = MUTED, dash = false) {
  slide.addShape(pres.shapes.LINE, {
    x, y, w, h, line: { color, width: 2, dashType: dash ? "dash" : "solid", endArrowType: "triangle" },
  });
}

// orthogonal connector segment from (x1,y1) to (x2,y2); arrowhead only on the last segment
function seg(slide, x1, y1, x2, y2, color, dash, arrowEnd) {
  const line = { color, width: 2, dashType: dash ? "dash" : "solid" };
  if (arrowEnd) line.endArrowType = "triangle";
  // Normalize to a positive-size bounding box and use flips for direction, otherwise
  // PowerPoint/pptxgenjs collapse negative w/h (right-to-left or bottom-to-top) lines to 0.
  const opts = {
    x: Math.min(x1, x2), y: Math.min(y1, y2),
    w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), line,
  };
  if (x2 < x1) opts.flipH = true;
  if (y2 < y1) opts.flipV = true;
  slide.addShape(pres.shapes.LINE, opts);
}

// ============================================================== SLIDE 1 — TITLE
{
  const s = pres.addSlide();
  s.background = { color: NAVY };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.22, h: H, fill: { color: M3 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.22, y: 0, w: 0.22, h: H, fill: { color: QWEN } });
  s.addText("MASTER'S THESIS · MULTI-AGENT SYSTEMS", {
    x: 1.1, y: 1.5, w: 11, h: 0.4, fontFace: BFONT, fontSize: 14, bold: true, color: ACCENT, charSpacing: 3, margin: 0,
  });
  s.addText("MASS", {
    x: 1.1, y: 2.0, w: 11, h: 1.2, fontFace: HFONT, fontSize: 72, bold: true, color: WHITE, margin: 0,
  });
  s.addText("Multi-Agent Sequential System", {
    x: 1.1, y: 3.25, w: 11.2, h: 0.8, fontFace: HFONT, fontSize: 26, italic: true, color: "CBD5E1", margin: 0,
  });
  s.addText([
    { text: "A heterogeneous multi-agent system that turns a natural-language task into ", options: {} },
    { text: "verified, runnable software", options: { bold: true, color: WHITE } },
    { text: " — and a study showing a per-role ", options: {} },
    { text: "mixture-of-models beats homogeneous baselines.", options: { bold: true, color: ACCENT } },
  ], { x: 1.1, y: 4.25, w: 10.8, h: 1.0, fontFace: BFONT, fontSize: 16, color: "94A3B8", lineSpacingMultiple: 1.15, margin: 0 });
  s.addShape(pres.shapes.LINE, { x: 1.12, y: 5.7, w: 4.5, h: 0, line: { color: "334155", width: 1 } });
  s.addText([
    { text: "Gennaro D'Ambrosio · Giuseppe Marotta", options: { bold: true, color: WHITE, breakLine: true } },
    { text: "Università degli Studi di Salerno · June 2026", options: { color: "94A3B8", fontSize: 13 } },
  ], { x: 1.1, y: 5.85, w: 8, h: 0.8, fontFace: BFONT, fontSize: 15, margin: 0 });
}

// ============================================================== SLIDE 2 — CONTRIBUTION TEASER
{
  const s = pres.addSlide();
  contentHeader(s, "Contribution at a glance", "Mixing models per role wins");
  s.addText([
    { text: "Same agent graph, same 20 ProjectEval projects. Only the ", options: {} },
    { text: "role → model mapping", options: { bold: true, color: NAVY } },
    { text: " changes. The mixture scores highest on the external judge.", options: {} },
  ], { x: ML, y: 1.65, w: 6.0, h: 1.2, fontFace: BFONT, fontSize: 16, color: SLATE, lineSpacingMultiple: 1.15, margin: 0 });

  // big stat
  s.addText("0.570", { x: ML, y: 3.1, w: 3.2, h: 1.1, fontFace: HFONT, fontSize: 66, bold: true, color: ACCENTD, margin: 0 });
  s.addText([
    { text: "official score (Mixed)", options: { bold: true, breakLine: true, color: NAVY } },
    { text: "vs 0.518 (M3-only) and 0.504 (Qwen-only)", options: { color: MUTED, fontSize: 12 } },
  ], { x: ML, y: 4.2, w: 5.2, h: 0.8, fontFace: BFONT, fontSize: 14, margin: 0 });
  s.addText("+ best on average project score and completion, at LOWER cost than M3-only.", {
    x: ML, y: 5.05, w: 5.6, h: 0.8, fontFace: BFONT, fontSize: 13, italic: true, color: QWEN, margin: 0,
  });

  s.addChart(pres.charts.BAR, [
    { name: "Official score", labels: ["Qwen-only", "M3-only", "Mixed"], values: [0.504, 0.518, 0.570] },
  ], {
    x: 7.0, y: 1.7, w: 5.9, h: 4.9, barDir: "col",
    chartColors: [QWEN, M3, ACCENT],
    chartArea: { fill: { color: WHITE } }, showLegend: false,
    showValue: true, dataLabelFormatCode: "0.000", dataLabelPosition: "outEnd", dataLabelColor: SLATE, dataLabelFontSize: 14, dataLabelFontBold: true,
    catAxisLabelColor: SLATE, catAxisLabelFontSize: 13, catAxisLabelFontBold: true,
    valAxisHidden: true, valAxisMaxVal: 0.6, valAxisMinVal: 0,
    valGridLine: { style: "none" }, catGridLine: { style: "none" },
    barGapWidthPct: 60,
    showTitle: true, title: "ProjectEval official score", titleColor: MUTED, titleFontSize: 13, titleFontFace: BFONT,
  });
  footer(s);
}

// ============================================================== SLIDE 4 — ARCHITECTURE DIAGRAM
{
  const s = pres.addSlide();
  contentHeader(s, "System overview", "The multi-agent graph (LangGraph)");
  // legend
  const leg = [[M3BG, M3, "MiniMax-M3 (planning)"], [QWENBG, QWEN, "Qwen3.6 (coding/testing)"], [DETBG, DET, "deterministic node"]];
  leg.forEach((l, i) => {
    const lx = ML + i * 3.4;
    s.addShape(pres.shapes.RECTANGLE, { x: lx, y: 1.55, w: 0.22, h: 0.22, fill: { color: l[0] }, line: { color: l[1], width: 1.5 } });
    s.addText(l[2], { x: lx + 0.3, y: 1.5, w: 3.1, h: 0.32, fontFace: BFONT, fontSize: 11, color: SLATE, margin: 0, valign: "middle" });
  });

  const r1y = 2.1, nh = 0.82, nw = 2.75;
  const r1x = [ML, ML + 3.05, ML + 6.1, ML + 9.15];
  node(s, r1x[0], r1y, nw, nh, "Requirement", "Analyzer", M3BG, M3, { tc: "1E3A8A" });
  node(s, r1x[1], r1y, nw, nh, "Benchmark", "Contract", DETBG, DET, { tc: "334155" });
  node(s, r1x[2], r1y, nw, nh, "Architect", "", M3BG, M3, { tc: "1E3A8A", fs: 13 });
  node(s, r1x[3], r1y, nw, nh, "Planning", "Reviewer", M3BG, M3, { tc: "1E3A8A" });
  // row 1 flow (Req -> Bench -> Architect -> Planning Reviewer)
  seg(s, r1x[0] + nw, 2.51, r1x[1], 2.51, MUTED, false, true);
  seg(s, r1x[1] + nw, 2.51, r1x[2], 2.51, MUTED, false, true);
  seg(s, r1x[2] + nw, 2.51, r1x[3], 2.51, MUTED, false, true);
  // planning loop: Planning Reviewer -> Architect (changes)
  seg(s, 10.5, 2.92, 10.5, 3.18, ACCENTD, true, false);
  seg(s, 10.5, 3.18, 8.075, 3.18, ACCENTD, true, false);
  seg(s, 8.075, 3.18, 8.075, 2.92, ACCENTD, true, true);
  s.addText("planning loop", { x: 8.2, y: 3.2, w: 2.1, h: 0.22, fontFace: BFONT, fontSize: 9, italic: true, color: ACCENTD, margin: 0 });

  // Coder
  const cy = 3.85, cw = 3.0, cx = (W - cw) / 2;
  node(s, cx, cy, cw, 0.95, "Coder", "JSON payload  |  agentic tool/ReAct loop", QWENBG, QWEN, { tc: "166534", fs: 16, fs2: 9.5, tc2: "166534" });
  // planning approved -> Coder
  seg(s, 11.7, 2.92, 11.7, 3.55, MUTED, false, false);
  seg(s, 11.7, 3.55, 6.665, 3.55, MUTED, false, false);
  seg(s, 6.665, 3.55, 6.665, cy, MUTED, false, true);
  s.addText("approved", { x: 10.45, y: 3.58, w: 1.6, h: 0.22, fontFace: BFONT, fontSize: 9, italic: true, color: MUTED, margin: 0 });

  // verification row
  const vy = 5.25, vw = 2.18, vh = 0.9;
  const vx = [ML, ML + 2.45, ML + 4.9, ML + 7.35, ML + 9.8];
  node(s, vx[0], vy, vw, vh, "Static Analysis", "blocking", DETBG, DET, { tc: "334155", fs: 12, fs2: 9, tc2: ACCENTD });
  node(s, vx[1], vy, vw, vh, "Test Writer", "pytest · advisory", QWENBG, QWEN, { tc: "166534", fs: 12, fs2: 9, tc2: "166534" });
  node(s, vx[2], vy, vw, vh, "Browser Tests", "Selenium · advisory", QWENBG, QWEN, { tc: "166534", fs: 12, fs2: 9, tc2: "166534" });
  node(s, vx[3], vy, vw, vh, "Reviewer", "", QWENBG, QWEN, { tc: "166534", fs: 14 });
  node(s, vx[4], vy, vw, vh, "Finalizer", "final_report", DETBG, DET, { tc: "334155", fs: 12, fs2: 9 });
  // Coder -> Static Analysis
  seg(s, 5.4, cy + 0.95, 5.4, 5.02, MUTED, false, false);
  seg(s, 5.4, 5.02, vx[0] + vw / 2, 5.02, MUTED, false, false);
  seg(s, vx[0] + vw / 2, 5.02, vx[0] + vw / 2, vy, MUTED, false, true);
  // verification chain
  seg(s, vx[0] + vw, 5.7, vx[1], 5.7, MUTED, false, true);
  seg(s, vx[1] + vw, 5.7, vx[2], 5.7, MUTED, false, true);
  seg(s, vx[2] + vw, 5.7, vx[3], 5.7, MUTED, false, true);
  seg(s, vx[3] + vw, 5.7, vx[4], 5.7, MUTED, false, true);
  // coding / repair loop: Reviewer -> Coder (changes)
  seg(s, vx[3] + vw / 2, vy, vx[3] + vw / 2, 4.95, ACCENTD, true, false);
  seg(s, vx[3] + vw / 2, 4.95, 7.5, 4.95, ACCENTD, true, false);
  seg(s, 7.5, 4.95, 7.5, cy + 0.95, ACCENTD, true, true);
  s.addText("coding / repair loop", { x: 6.95, y: 5.0, w: 2.0, h: 0.22, fontFace: BFONT, fontSize: 8.5, italic: true, color: ACCENTD, margin: 0 });

  // shared state band
  s.addShape(pres.shapes.RECTANGLE, { x: ML, y: 6.45, w: W - 2 * ML, h: 0.5, fill: { color: LIGHT }, line: { color: "CBD5E1", width: 1 } });
  s.addText([
    { text: "Shared GraphState  ·  ", options: { bold: true, color: NAVY } },
    { text: "checkpoints (resume)  ·  agent transcripts (token usage)  ·  bounded iteration caps", options: { color: SLATE } },
  ], { x: ML, y: 6.45, w: W - 2 * ML, h: 0.5, fontFace: BFONT, fontSize: 12, align: "center", valign: "middle", margin: 0 });
}

// ============================================================== SLIDE 5 — STATE & ORCHESTRATION
{
  const s = pres.addSlide();
  contentHeader(s, "Orchestration", "One shared state, conditional routing");
  s.addText([
    { text: "Stateful graph on LangGraph.", options: { bold: true, color: NAVY, breakLine: true } },
    { text: "10 agent/utility nodes connected by routing functions. Agents never call each other directly — they read and update one typed GraphState.", options: { breakLine: true } },
    { text: "", options: { breakLine: true, fontSize: 6 } },
    { text: "Two nested review loops, each bounded by an iteration cap → guaranteed termination at the finalizer.", options: {} },
  ], { x: ML, y: 1.75, w: 6.0, h: 2.4, fontFace: BFONT, fontSize: 15, color: SLATE, lineSpacingMultiple: 1.12, margin: 0 });

  const items = [
    ["Plan & contract", "requirements · architecture_plan · benchmark_contract"],
    ["Feedback", "reviewer_feedback · review_status (approved / changes)"],
    ["Verification", "lint · static · dynamic · browser results"],
    ["Control", "planning / coding / global iteration counters + caps"],
    ["Persistence", "files_touched · artifacts · traces · messages"],
  ];
  let yy = 1.75;
  items.forEach((it) => {
    s.addShape(pres.shapes.RECTANGLE, { x: 7.0, y: yy, w: 5.7, h: 0.92, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x: 7.0, y: yy, w: 0.08, h: 0.92, fill: { color: M3 } });
    s.addText(it[0], { x: 7.25, y: yy + 0.1, w: 5.2, h: 0.32, fontFace: BFONT, fontSize: 14, bold: true, color: NAVY, margin: 0 });
    s.addText(it[1], { x: 7.25, y: yy + 0.45, w: 5.3, h: 0.42, fontFace: "Consolas", fontSize: 11, color: SLATE, margin: 0 });
    yy += 1.04;
  });
  footer(s);
}

// ============================================================== SLIDE 6 — AGENTS 1-2
{
  const s = pres.addSlide();
  contentHeader(s, "Agents · planning brain (1/2)", "Requirement Analyzer & Benchmark Contract");
  const cards = [
    [M3, M3BG, "1 · Requirement Analyzer", "MiniMax-M3", [
      "Turns the raw task into structured requirements: scope, functional & non-functional needs, constraints, open assumptions.",
      "Strict role boundary: no code, ever — output feeds the Architect directly.",
      "Cheapest agent: one call per project, tiny input.",
    ]],
    [DET, DETBG, "2 · Benchmark Contract", "deterministic", [
      "Builds a compact machine-readable contract: required URLs, selectors, expected texts, output files, project type & stack.",
      "The ground truth every downstream agent must satisfy.",
    ]],
  ];
  cards.forEach((c, i) => {
    const cx = ML + i * 6.35, cw = 6.0, cy = 1.85, ch = 4.7;
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: ch, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: 0.95, fill: { color: c[1] } });
    s.addText(c[2], { x: cx + 0.3, y: cy + 0.18, w: cw - 0.6, h: 0.4, fontFace: BFONT, fontSize: 18, bold: true, color: NAVY, margin: 0 });
    s.addText(c[3], { x: cx + 0.3, y: cy + 0.58, w: cw - 0.6, h: 0.3, fontFace: "Consolas", fontSize: 11, bold: true, color: c[0], margin: 0 });
    s.addText(c[4].map((t) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: true, paraSpaceAfter: 8 } })),
      { x: cx + 0.35, y: cy + 1.15, w: cw - 0.7, h: ch - 1.3, fontFace: BFONT, fontSize: 13.5, color: SLATE, valign: "top", margin: 0, lineSpacingMultiple: 1.05 });
  });
  footer(s);
}

// ============================================================== SLIDE 7 — AGENTS 3-4 + planning loop
{
  const s = pres.addSlide();
  contentHeader(s, "Agents · planning brain (2/2)", "Architect & Planning Reviewer — the planning loop");
  const cards = [
    [M3, M3BG, "3 · Architect", "MiniMax-M3", [
      "Produces an implementation-ready plan: components, shared-state usage, routing, iteration & artifact strategy.",
      "Contract-aware: maps every URL/selector/text to a concrete path; optimizes for observability & stable transitions.",
      "Largest reasoning budget (up to 32k output).",
    ]],
    [M3, M3BG, "4 · Planning Reviewer", "MiniMax-M3", [
      "Reviews the plan against requirements BEFORE any code exists.",
      "Returns Approved / Changes requested; checks missing components, weak loops, contract-coverage gaps.",
      "Drives the planning loop until the cap.",
    ]],
  ];
  cards.forEach((c, i) => {
    const cx = ML + i * 6.35, cw = 6.0, cy = 1.85, ch = 3.85;
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: ch, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: 0.95, fill: { color: c[1] } });
    s.addText(c[2], { x: cx + 0.3, y: cy + 0.18, w: cw - 0.6, h: 0.4, fontFace: BFONT, fontSize: 18, bold: true, color: NAVY, margin: 0 });
    s.addText(c[3], { x: cx + 0.3, y: cy + 0.58, w: cw - 0.6, h: 0.3, fontFace: "Consolas", fontSize: 11, bold: true, color: c[0], margin: 0 });
    s.addText(c[4].map((t) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: true, paraSpaceAfter: 8 } })),
      { x: cx + 0.35, y: cy + 1.15, w: cw - 0.7, h: ch - 1.3, fontFace: BFONT, fontSize: 13.5, color: SLATE, valign: "top", margin: 0, lineSpacingMultiple: 1.05 });
  });
  // loop strip
  s.addShape(pres.shapes.RECTANGLE, { x: ML, y: 5.95, w: W - 2 * ML, h: 0.75, fill: { color: "FEF3C7" }, line: { color: ACCENT, width: 1 } });
  s.addText([
    { text: "Planning loop:  ", options: { bold: true, color: ACCENTD } },
    { text: "architect → planning_reviewer → (approved → coder) | (changes → architect),  bounded by max_planning_iterations.", options: { color: SLATE } },
  ], { x: ML + 0.2, y: 5.95, w: W - 2 * ML - 0.4, h: 0.75, fontFace: BFONT, fontSize: 13, valign: "middle", margin: 0 });
  footer(s);
}

// ============================================================== SLIDE 8 — CODER
{
  const s = pres.addSlide();
  contentHeader(s, "Agents · the engine", "Coder — generates & repairs the project");
  s.addShape(pres.shapes.RECTANGLE, { x: ML, y: 1.85, w: 6.0, h: 2.1, fill: { color: QWENBG }, line: { color: QWEN, width: 1.5 } });
  s.addText("Two execution modes", { x: ML + 0.3, y: 2.0, w: 5.4, h: 0.35, fontFace: BFONT, fontSize: 15, bold: true, color: "166534", margin: 0 });
  s.addText([
    { text: "Structured-JSON (default): ", options: { bold: true, breakLine: false } },
    { text: "returns {summary, delete_paths, files[]}; the system writes files.", options: { breakLine: true, paraSpaceAfter: 6 } },
    { text: "Agentic tool mode: ", options: { bold: true } },
    { text: "builds the project by calling tools in a ReAct loop (up to 50 steps).", options: {} },
  ], { x: ML + 0.3, y: 2.4, w: 5.5, h: 1.45, fontFace: BFONT, fontSize: 13, color: SLATE, margin: 0, lineSpacingMultiple: 1.05 });

  const pts = [
    ["First iteration", "writes a complete, runnable project."],
    ["Repair iterations", "patches only files implicated by the failure digest (focused subset) — a key cost saver."],
    ["Safety net", "system re-validates syntax + framework sanity after every write."],
    ["Robustness", "JSON-repair, retries, and a timeout-recovery path on slow providers."],
  ];
  let yy = 1.85;
  pts.forEach((p) => {
    s.addShape(pres.shapes.RECTANGLE, { x: 7.0, y: yy, w: 5.7, h: 1.02, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x: 7.0, y: yy, w: 0.08, h: 1.02, fill: { color: QWEN } });
    s.addText(p[0], { x: 7.25, y: yy + 0.1, w: 5.3, h: 0.3, fontFace: BFONT, fontSize: 14, bold: true, color: NAVY, margin: 0 });
    s.addText(p[1], { x: 7.25, y: yy + 0.42, w: 5.3, h: 0.55, fontFace: BFONT, fontSize: 12, color: SLATE, margin: 0, lineSpacingMultiple: 1.0 });
    yy += 1.14;
  });
  // tools strip
  s.addShape(pres.shapes.RECTANGLE, { x: ML, y: 4.25, w: 6.0, h: 2.45, fill: { color: WHITE }, line: { color: "E2E8F0", width: 1 } });
  s.addText("Tool registry (scoped to workspace)", { x: ML + 0.3, y: 4.4, w: 5.4, h: 0.35, fontFace: BFONT, fontSize: 14, bold: true, color: NAVY, margin: 0 });
  const tools = [["read_file · list_files · grep", "inspect"], ["write_file · delete_path", "build"], ["validate_python · django_check · run_pytest", "check"]];
  let ty = 4.85;
  tools.forEach((t) => {
    s.addText(t[1].toUpperCase(), { x: ML + 0.3, y: ty, w: 1.2, h: 0.3, fontFace: BFONT, fontSize: 10, bold: true, color: ACCENTD, margin: 0 });
    s.addText(t[0], { x: ML + 1.5, y: ty, w: 4.3, h: 0.3, fontFace: "Consolas", fontSize: 12, color: SLATE, margin: 0 });
    ty += 0.55;
  });
  s.addText("Results returned as compact JSON; output budgets keep context small.", { x: ML + 0.3, y: 6.25, w: 5.5, h: 0.35, fontFace: BFONT, fontSize: 11, italic: true, color: MUTED, margin: 0 });
  footer(s);
}

// ============================================================== SLIDE 9 — VERIFICATION LAYER
{
  const s = pres.addSlide();
  contentHeader(s, "Executable verification", "Static → dynamic → browser");
  const stages = [
    [DET, DETBG, "1 · Static analysis", "BLOCKING", ["analyze_generated_project()", "per-write syntax + framework sanity", "failure → Reviewer fix-advisor → Coder"]],
    [QWEN, QWENBG, "2 · Dynamic tests", "advisory", ["Test Writer generates a pytest suite", "smoke + behavior + route/selector contract", "Django: manage.py check + correct setup order"]],
    [QWEN, QWENBG, "3 · Browser tests", "advisory · websites", ["Selenium suite, 3–6 high-signal flows", "free runtime port, sys.executable, poll & clean", "skips (not fails) if Chrome unavailable"]],
  ];
  stages.forEach((st, i) => {
    const cx = ML + i * 4.18, cw = 3.9, cy = 1.85, ch = 3.6;
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: ch, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: 0.85, fill: { color: st[1] } });
    s.addText(st[2], { x: cx + 0.25, y: cy + 0.14, w: cw - 0.5, h: 0.35, fontFace: BFONT, fontSize: 16, bold: true, color: NAVY, margin: 0 });
    s.addText(st[3], { x: cx + 0.25, y: cy + 0.5, w: cw - 0.5, h: 0.3, fontFace: BFONT, fontSize: 10, bold: true, color: st[0], charSpacing: 1, margin: 0 });
    s.addText(st[4].map((t) => ({ text: t, options: { bullet: { indent: 12 }, breakLine: true, paraSpaceAfter: 7 } })),
      { x: cx + 0.3, y: cy + 1.0, w: cw - 0.6, h: ch - 1.15, fontFace: BFONT, fontSize: 12.5, color: SLATE, valign: "top", margin: 0, lineSpacingMultiple: 1.03 });
    if (i < 2) arrow(s, cx + cw, cy + 1.6, 0.26, 0, MUTED);
  });
  s.addShape(pres.shapes.RECTANGLE, { x: ML, y: 5.7, w: W - 2 * ML, h: 0.95, fill: { color: "FEF3C7" }, line: { color: ACCENT, width: 1 } });
  s.addText([
    { text: "Design decision:  ", options: { bold: true, color: ACCENTD } },
    { text: "only static analysis is blocking. Dynamic & Selenium tests are advisory — they are brittle and do not affect the official judge, so making them blocking wasted iterations fixing tests instead of the app.", options: { color: SLATE } },
  ], { x: ML + 0.25, y: 5.7, w: W - 2 * ML - 0.5, h: 0.95, fontFace: BFONT, fontSize: 13, valign: "middle", margin: 0, lineSpacingMultiple: 1.05 });
  footer(s);
}

// ============================================================== SLIDE 10 — REVIEWER
{
  const s = pres.addSlide();
  contentHeader(s, "Agents · quality gate", "Reviewer — two automatic modes");
  const cards = [
    [ACCENTD, "FEF3C7", "analysis_fix_advisor", "when lint / static analysis failed", [
      "Acts as a fix advisor — does not approve or reject.",
      "Returns ≤4 blocking items, ≤1200 chars: classification + file + cause + exact fix.",
      "Forces 'changes requested' → routes back to the Coder.",
    ]],
    [QWEN, QWENBG, "quality_review", "when analysis is clean", [
      "Concise correctness & completeness review.",
      "Contract-coverage gate: every page / selector / URL / expected-text / output file must be implemented.",
      "A project that merely runs but is incomplete is NOT approvable.",
    ]],
  ];
  cards.forEach((c, i) => {
    const cx = ML + i * 6.35, cw = 6.0, cy = 1.9, ch = 4.0;
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: ch, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: 0.95, fill: { color: c[1] } });
    s.addText(c[2], { x: cx + 0.3, y: cy + 0.16, w: cw - 0.6, h: 0.4, fontFace: "Consolas", fontSize: 17, bold: true, color: NAVY, margin: 0 });
    s.addText(c[3], { x: cx + 0.3, y: cy + 0.58, w: cw - 0.6, h: 0.3, fontFace: BFONT, fontSize: 12, italic: true, color: c[0], margin: 0 });
    s.addText(c[4].map((t) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: true, paraSpaceAfter: 9 } })),
      { x: cx + 0.35, y: cy + 1.15, w: cw - 0.7, h: ch - 1.3, fontFace: BFONT, fontSize: 13.5, color: SLATE, valign: "top", margin: 0, lineSpacingMultiple: 1.05 });
  });
  s.addText("Drives the coding / repair loop: changes_requested → Coder, until max_coding_iterations.", {
    x: ML, y: 6.1, w: W - 2 * ML, h: 0.5, fontFace: BFONT, fontSize: 13, italic: true, color: MUTED, align: "center", margin: 0,
  });
  footer(s);
}

// ============================================================== SLIDE 11 — MEMORY
{
  const s = pres.addSlide();
  contentHeader(s, "Memory & reproducibility", "Three layers of persistence");
  const layers = [
    [M3, "Conversation memory (in-state)", "Append-only messages log + traces of every model call (agent, model, usage, duration). Stale tool results pruned to control context."],
    [QWEN, "Workflow checkpoints", "Each node snapshots state before it runs, with a resume node — a crashed run resumes from the last completed node. The Coder also records a code-history snapshot per iteration."],
    [ACCENTD, "Agent transcripts (on disk)", "Every single model call is written to artifacts/agent_transcripts/ with full prompts, response, model and token usage — exactly what powers the token analysis."],
  ];
  let yy = 1.9;
  layers.forEach((l, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: ML, y: yy, w: W - 2 * ML, h: 1.4, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 }, shadow: mkShadow() });
    s.addShape(pres.shapes.OVAL, { x: ML + 0.3, y: yy + 0.42, w: 0.55, h: 0.55, fill: { color: l[0] } });
    s.addText(String(i + 1), { x: ML + 0.3, y: yy + 0.42, w: 0.55, h: 0.55, fontFace: BFONT, fontSize: 20, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0 });
    s.addText(l[1], { x: ML + 1.1, y: yy + 0.2, w: 10.8, h: 0.4, fontFace: BFONT, fontSize: 17, bold: true, color: NAVY, margin: 0 });
    s.addText(l[2], { x: ML + 1.1, y: yy + 0.62, w: 10.9, h: 0.7, fontFace: BFONT, fontSize: 13, color: SLATE, margin: 0, lineSpacingMultiple: 1.05 });
    yy += 1.6;
  });
  footer(s);
}

// ============================================================== SLIDE 12 — PROMPTS
{
  const s = pres.addSlide();
  contentHeader(s, "Prompt engineering", "Modular, contract-locked prompts");
  s.addText([
    { text: "Prompts are composed at runtime, not monolithic.", options: { bold: true, color: NAVY, breakLine: true } },
    { text: "Each model call sees only the rules relevant to its task type — focused prompts, fewer tokens.", options: {} },
  ], { x: ML, y: 1.7, w: 6.0, h: 1.3, fontFace: BFONT, fontSize: 15, color: SLATE, lineSpacingMultiple: 1.12, margin: 0 });

  const blocks = [
    ["Base role prompt", "coder.txt, reviewer.txt, architect.txt …"],
    ["+ stack modules", "coder_console / coder_web / coder_django (selected by project type)"],
    ["+ repair module", "added on repair iterations"],
    ["+ contract-lock block", "ProjectEval guardrails: unique HTML ids, seed data, safe ALLOWED_HOSTS, one canonical template…"],
    ["+ strict role boundary", "planners must not emit code"],
  ];
  let yy = 1.7;
  blocks.forEach((b, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: 7.0, y: yy, w: 5.7, h: 0.92, fill: { color: i === 3 ? "FEF3C7" : CARDBG }, line: { color: i === 3 ? ACCENT : "E2E8F0", width: 1 } });
    s.addText(b[0], { x: 7.2, y: yy + 0.09, w: 5.4, h: 0.32, fontFace: "Consolas", fontSize: 13, bold: true, color: NAVY, margin: 0 });
    s.addText(b[1], { x: 7.2, y: yy + 0.42, w: 5.4, h: 0.46, fontFace: BFONT, fontSize: 11.5, color: SLATE, margin: 0, lineSpacingMultiple: 1.0 });
    yy += 1.0;
  });
  s.addText("Result: prompts that adapt to console / web / Django tasks and stay aligned with the external judge contract.", {
    x: ML, y: 3.3, w: 6.0, h: 1.6, fontFace: BFONT, fontSize: 14, italic: true, color: MUTED, margin: 0, lineSpacingMultiple: 1.1,
  });
  footer(s);
}

// ============================================================== SLIDE 13 — EXPERIMENT DESIGN matrix
{
  const s = pres.addSlide();
  contentHeader(s, "Experimental design", "Three matched configurations");
  s.addText("Same architecture, prompts, tools, caps and 20 projects. Only the role → model mapping changes.", {
    x: ML, y: 1.6, w: 12, h: 0.4, fontFace: BFONT, fontSize: 14, color: SLATE, margin: 0,
  });
  const hdr = (t, c) => ({ text: t, options: { fill: { color: c }, color: WHITE, bold: true, align: "center", fontSize: 14 } });
  const cell = (t, c) => ({ text: t, options: { color: c === WHITE ? SLATE : WHITE, fill: { color: c }, align: "center", fontSize: 13, bold: c !== WHITE } });
  const rows = [
    [hdr("Role", NAVY), hdr("Qwen-only", QWEN), hdr("M3-only", M3), hdr("Mixed (contribution)", ACCENTD)],
    ...[
      ["requirement_analyzer", QWEN, M3, M3],
      ["architect", QWEN, M3, M3],
      ["planning_reviewer", QWEN, M3, M3],
      ["coder", QWEN, M3, QWEN],
      ["reviewer", QWEN, M3, QWEN],
      ["test_writer", QWEN, M3, QWEN],
      ["browser_test_writer", QWEN, M3, QWEN],
    ].map((r) => [
      { text: r[0], options: { fontFace: "Consolas", fontSize: 12.5, color: SLATE, align: "left", bold: true } },
      cell(r[1] === QWEN ? "Qwen3.6" : "M3", r[1]),
      cell(r[2] === QWEN ? "Qwen3.6" : "M3", r[2]),
      cell(r[3] === QWEN ? "Qwen3.6" : "M3", r[3]),
    ]),
  ];
  s.addTable(rows, {
    x: ML, y: 2.15, w: 12.1, colW: [3.7, 2.8, 2.8, 2.8], rowH: 0.55,
    border: { pt: 1, color: WHITE }, valign: "middle", fontFace: BFONT,
  });
  s.addText([
    { text: "The split:  ", options: { bold: true, color: ACCENTD } },
    { text: "MiniMax-M3 = the planning brain (requirements, architecture, plan review);  Qwen3.6-27B = the production line (coding, review, test authoring — most of the calls & tokens).", options: { color: SLATE } },
  ], { x: ML, y: 6.45, w: 12.1, h: 0.55, fontFace: BFONT, fontSize: 12.5, valign: "middle", margin: 0, lineSpacingMultiple: 1.0 });
  footer(s);
}

// ============================================================== SLIDE 14 — BENCHMARK
{
  const s = pres.addSlide();
  contentHeader(s, "Benchmark", "ProjectEval + external judge");
  const stats = [
    ["20", "real software projects (Level 2)"],
    ["284", "judge functions scored"],
    ["3", "matched runs (Qwen / M3 / Mixed)"],
  ];
  stats.forEach((st, i) => {
    const cx = ML + i * 4.18, cw = 3.9;
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: 1.85, w: cw, h: 1.7, fill: { color: NAVY } });
    s.addText(st[0], { x: cx, y: 1.95, w: cw, h: 0.95, fontFace: HFONT, fontSize: 48, bold: true, color: ACCENT, align: "center", margin: 0 });
    s.addText(st[1], { x: cx + 0.2, y: 2.9, w: cw - 0.4, h: 0.55, fontFace: BFONT, fontSize: 12.5, color: "CBD5E1", align: "center", margin: 0 });
  });
  const metrics = [
    ["official score", "external judge's function-level pass rate — the headline metric (out of 284)."],
    ["completion rate", "fraction of the 20 projects the system completed locally."],
    ["average_project_score", "mean per-project judge score."],
    ["Independent arbiter", "the contract is externally owned throughout — the system cannot game the judge."],
  ];
  let yy = 3.9;
  metrics.forEach((m) => {
    s.addShape(pres.shapes.RECTANGLE, { x: ML, y: yy, w: W - 2 * ML, h: 0.66, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 } });
    s.addText(m[0], { x: ML + 0.25, y: yy, w: 4.4, h: 0.66, fontFace: "Consolas", fontSize: 12.5, bold: true, color: M3, valign: "middle", margin: 0 });
    s.addText(m[1], { x: ML + 4.8, y: yy, w: 7.0, h: 0.66, fontFace: BFONT, fontSize: 12.5, color: SLATE, valign: "middle", margin: 0 });
    yy += 0.72;
  });
  footer(s);
}

// ============================================================== SLIDE 15 — RESULTS bar
{
  const s = pres.addSlide();
  contentHeader(s, "Results", "Quality — the mixture leads on every metric");
  s.addChart(pres.charts.BAR, [
    { name: "Official score", labels: ["Qwen-only", "M3-only", "Mixed"], values: [0.504, 0.518, 0.570] },
    { name: "Avg project score", labels: ["Qwen-only", "M3-only", "Mixed"], values: [0.589, 0.599, 0.658] },
  ], {
    x: ML, y: 1.75, w: 7.4, h: 4.9, barDir: "col",
    chartColors: [M3, ACCENT],
    showValue: true, dataLabelFormatCode: "0.000", dataLabelPosition: "outEnd", dataLabelColor: SLATE, dataLabelFontSize: 11, dataLabelFontBold: true,
    catAxisLabelColor: SLATE, catAxisLabelFontSize: 13, catAxisLabelFontBold: true,
    valAxisHidden: true, valAxisMaxVal: 0.75, valAxisMinVal: 0,
    valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "b", legendColor: SLATE, legendFontSize: 12,
    barGapWidthPct: 40,
  });
  const notes = [
    ["+6.6 pts", "official score vs Qwen-only (0.570 vs 0.504); +19 judge functions."],
    ["> M3 too", "beats M3-everywhere on avg project score (0.658 vs 0.599)."],
    ["162 / 284", "judge functions passed by Mixed — the most of the three runs."],
  ];
  let yy = 1.85;
  notes.forEach((n) => {
    s.addShape(pres.shapes.RECTANGLE, { x: 8.4, y: yy, w: 4.3, h: 1.4, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x: 8.4, y: yy, w: 0.09, h: 1.4, fill: { color: ACCENT } });
    s.addText(n[0], { x: 8.6, y: yy + 0.12, w: 4.0, h: 0.45, fontFace: HFONT, fontSize: 22, bold: true, color: ACCENTD, margin: 0 });
    s.addText(n[1], { x: 8.6, y: yy + 0.6, w: 4.0, h: 0.75, fontFace: BFONT, fontSize: 12, color: SLATE, margin: 0, lineSpacingMultiple: 1.03 });
    yy += 1.6;
  });
  footer(s);
}

// ============================================================== SLIDE 16 — RESULTS table + why
{
  const s = pres.addSlide();
  contentHeader(s, "Results", "Why the mixture wins");
  const H1 = (t, a = "center") => ({ text: t, options: { fill: { color: NAVY }, color: WHITE, bold: true, align: a, fontSize: 13 } });
  const td = (t, a = "center", bold = false, color = SLATE) => ({ text: t, options: { align: a, fontSize: 13, color, bold } });
  const rows = [
    [H1("Configuration", "left"), H1("Official score"), H1("Avg project score"), H1("Judge functions")],
    [td("Qwen3.6-27B (homogeneous)", "left"), td("0.504"), td("0.589"), td("143 / 284")],
    [td("MiniMax-M3 (homogeneous)", "left"), td("0.518"), td("0.599"), td("147 / 284")],
    [
      { text: "Mixed (M3 plan + Qwen code)", options: { align: "left", fontSize: 13, bold: true, color: WHITE } },
      td("0.570", "center", true, WHITE), td("0.658", "center", true, WHITE), td("162 / 284", "center", true, WHITE),
    ],
  ];
  // ensure mixed row cells have accent fill
  rows[3] = rows[3].map((c) => ({ text: c.text, options: { ...c.options, fill: { color: ACCENTD } } }));
  s.addTable(rows, { x: ML, y: 1.75, w: 12.1, colW: [4.9, 2.4, 2.4, 2.4], rowH: 0.58, border: { pt: 1, color: WHITE }, valign: "middle", fontFace: BFONT });

  const why = [
    ["Planning matters disproportionately", "the stronger reasoner on requirements + architecture + review yields better, more contract-complete plans — the Coder starts from a stronger spec."],
    ["The production line is volume-bound", "coding / review / testing are dominated by call count; the efficient code model handles them well and cheaply."],
    ["Best of both", "M3's reasoning where it counts, Qwen's efficiency where the volume is — the combination exceeds M3-everywhere."],
  ];
  let yy = 4.35;
  why.forEach((w2) => {
    s.addShape(pres.shapes.RECTANGLE, { x: ML, y: yy, w: W - 2 * ML, h: 0.74, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 } });
    s.addText(w2[0], { x: ML + 0.25, y: yy, w: 4.3, h: 0.74, fontFace: BFONT, fontSize: 13.5, bold: true, color: NAVY, valign: "middle", margin: 0 });
    s.addText(w2[1], { x: ML + 4.7, y: yy, w: 7.2, h: 0.74, fontFace: BFONT, fontSize: 12, color: SLATE, valign: "middle", margin: 0, lineSpacingMultiple: 1.0 });
    yy += 0.82;
  });
  footer(s);
}

// ============================================================== SLIDE 17 — TOKENS per agent (stacked)
{
  const s = pres.addSlide();
  contentHeader(s, "Token analysis", "Where the budget goes — the coder dominates");
  // percent-stacked: categories = configs, series = agents
  const agents = [
    ["coder", [6.59, 9.48, 6.60], "0E7490"],
    ["reviewer", [0.85, 2.04, 1.20], "0891B2"],
    ["test_writer", [0.93, 0.77, 1.16], "22D3EE"],
    ["browser_test_writer", [0.30, 0.32, 0.35], "67E8F9"],
    ["architect", [0.38, 0.35, 0.35], "2563EB"],
    ["planning_reviewer", [0.16, 0.17, 0.17], "60A5FA"],
    ["requirement_analyzer", [0.07, 0.05, 0.05], "BFDBFE"],
  ];
  const data = agents.map((a) => ({ name: a[0], labels: ["Qwen-only", "M3-only", "Mixed"], values: a[1] }));
  s.addChart(pres.charts.BAR, data, {
    x: ML, y: 1.8, w: 7.6, h: 4.8, barDir: "bar", barGrouping: "percentStacked",
    chartColors: agents.map((a) => a[2]),
    catAxisLabelColor: SLATE, catAxisLabelFontSize: 12, catAxisLabelFontBold: true,
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "b", legendColor: SLATE, legendFontSize: 9,
  });
  s.addShape(pres.shapes.RECTANGLE, { x: 8.5, y: 1.9, w: 4.25, h: 2.2, fill: { color: NAVY } });
  s.addText("~67–72%", { x: 8.5, y: 2.05, w: 4.25, h: 0.85, fontFace: HFONT, fontSize: 42, bold: true, color: ACCENT, align: "center", margin: 0 });
  s.addText("of all tokens are spent by the Coder, in every configuration.", { x: 8.7, y: 2.95, w: 3.85, h: 1.0, fontFace: BFONT, fontSize: 14, color: "CBD5E1", align: "center", margin: 0, lineSpacingMultiple: 1.05 });
  s.addShape(pres.shapes.RECTANGLE, { x: 8.5, y: 4.35, w: 4.25, h: 2.25, fill: { color: "FEF3C7" }, line: { color: ACCENT, width: 1 } });
  s.addText([
    { text: "Planning agents = only ~3.5–7% of tokens.", options: { bold: true, color: ACCENTD, breakLine: true, paraSpaceAfter: 6 } },
    { text: "→ Upgrading them to MiniMax-M3 is almost free in token terms, yet it lifts quality. This is the quantitative backbone of the mixture argument.", options: { color: SLATE } },
  ], { x: 8.7, y: 4.5, w: 3.9, h: 2.0, fontFace: BFONT, fontSize: 12.5, valign: "top", margin: 0, lineSpacingMultiple: 1.06 });
  footer(s);
}

// ============================================================== SLIDE 18 — COST vs QUALITY (custom scatter)
{
  const s = pres.addSlide();
  contentHeader(s, "Token analysis", "Cost vs quality — the efficient frontier");
  // plot area
  const px = 1.6, py = 2.1, pw = 7.4, ph = 4.0;
  s.addShape(pres.shapes.RECTANGLE, { x: px, y: py, w: pw, h: ph, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 } });
  // axes
  s.addShape(pres.shapes.LINE, { x: px, y: py + ph, w: pw, h: 0, line: { color: MUTED, width: 1.5 } });
  s.addShape(pres.shapes.LINE, { x: px, y: py, w: 0, h: ph, line: { color: MUTED, width: 1.5 } });
  s.addText("Total tokens (M) →", { x: px + pw - 2.6, y: py + ph + 0.08, w: 2.6, h: 0.3, fontFace: BFONT, fontSize: 11, color: MUTED, align: "right", margin: 0 });
  s.addText("Official score →", { x: px - 1.4, y: py + 0.0, w: 1.3, h: 0.3, fontFace: BFONT, fontSize: 11, color: MUTED, align: "left", rotate: 270, margin: 0 });
  // map: x tokens 8..17 ; y score 0.47..0.59 (headroom so Mixed=0.570 sits inside the box)
  const xmin = 8, xmax = 17, ymin = 0.47, ymax = 0.59;
  const X = (v) => px + ((v - xmin) / (xmax - xmin)) * pw;
  const Y = (v) => py + ph - ((v - ymin) / (ymax - ymin)) * ph;
  const pts = [
    ["Qwen-only", 9.30, 0.504, QWEN],
    ["M3-only", 13.19, 0.518, M3],
    ["Mixed", 9.88, 0.570, ACCENT],
  ];
  pts.forEach((p) => {
    const cx = X(p[1]), cy = Y(p[2]);
    s.addShape(pres.shapes.OVAL, { x: cx - 0.16, y: cy - 0.16, w: 0.32, h: 0.32, fill: { color: p[3] }, line: { color: WHITE, width: 2 }, shadow: mkShadow() });
    s.addText([
      { text: p[0], options: { bold: true, color: NAVY, breakLine: true } },
      { text: `${p[1]}M · ${p[2]}`, options: { color: MUTED, fontSize: 10 } },
    ], { x: cx - 1.0, y: cy + 0.2, w: 2.0, h: 0.6, fontFace: BFONT, fontSize: 12, align: "center", margin: 0 });
  });
  // takeaways
  const tk = [
    ["Mixed dominates M3", "higher score AND fewer tokens (up-and-left of M3)."],
    ["Qwen is cheapest", "most token-efficient per point, but lowest absolute quality."],
    ["Quality goal → Mixed", "the efficient-frontier point: best score for less than all-strong cost."],
  ];
  let yy = 2.1;
  tk.forEach((t) => {
    s.addShape(pres.shapes.RECTANGLE, { x: 9.4, y: yy, w: 3.35, h: 1.35, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x: 9.4, y: yy, w: 0.08, h: 1.35, fill: { color: ACCENT } });
    s.addText(t[0], { x: 9.6, y: yy + 0.12, w: 3.05, h: 0.4, fontFace: BFONT, fontSize: 13.5, bold: true, color: NAVY, margin: 0 });
    s.addText(t[1], { x: 9.6, y: yy + 0.55, w: 3.05, h: 0.75, fontFace: BFONT, fontSize: 11.5, color: SLATE, margin: 0, lineSpacingMultiple: 1.03 });
    yy += 1.5;
  });
  footer(s);
}

// ============================================================== SLIDE 19 — CONCLUSIONS
{
  const s = pres.addSlide();
  s.background = { color: NAVY };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.22, h: H, fill: { color: M3 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.22, y: 0, w: 0.22, h: H, fill: { color: QWEN } });
  s.addText("CONCLUSIONS", { x: 1.1, y: 0.7, w: 11, h: 0.4, fontFace: BFONT, fontSize: 14, bold: true, color: ACCENT, charSpacing: 3, margin: 0 });
  s.addText("Three things to remember", { x: 1.1, y: 1.1, w: 11.5, h: 0.8, fontFace: HFONT, fontSize: 34, bold: true, color: WHITE, margin: 0 });
  const tk = [
    ["Separation of concerns + executable verification", "Specialized agents in a stateful graph, with static analysis and test execution in the loop, make LLM code generation reliable on a hard external benchmark."],
    ["Model choice is a per-role decision", "Not a global one. The mixture — M3 on planning, Qwen on coding/testing — beats either homogeneous baseline on the official judge."],
    ["The coder loop dominates cost", "~67–72% of tokens. Upgrading the cheap-but-high-leverage planning roles is nearly free, so the mix buys quality without the all-strong-model cost."],
  ];
  let yy = 2.2;
  tk.forEach((t, i) => {
    s.addShape(pres.shapes.OVAL, { x: 1.1, y: yy, w: 0.6, h: 0.6, fill: { color: ACCENT } });
    s.addText(String(i + 1), { x: 1.1, y: yy, w: 0.6, h: 0.6, fontFace: HFONT, fontSize: 24, bold: true, color: NAVY, align: "center", valign: "middle", margin: 0 });
    s.addText(t[0], { x: 1.95, y: yy - 0.05, w: 10.5, h: 0.45, fontFace: BFONT, fontSize: 19, bold: true, color: WHITE, margin: 0 });
    s.addText(t[1], { x: 1.95, y: yy + 0.42, w: 10.7, h: 0.85, fontFace: BFONT, fontSize: 13.5, color: "94A3B8", margin: 0, lineSpacingMultiple: 1.08 });
    yy += 1.5;
  });
  s.addText("Thank you — questions welcome.", { x: 1.1, y: 6.75, w: 9, h: 0.4, fontFace: HFONT, fontSize: 16, italic: true, color: "CBD5E1", margin: 0 });
}

// ============================================================== SLIDE 20 — BACKUP tokens table
{
  const s = pres.addSlide();
  contentHeader(s, "Backup", "Token usage — full breakdown");
  const Hd = (t, a = "center") => ({ text: t, options: { fill: { color: NAVY }, color: WHITE, bold: true, align: a, fontSize: 12 } });
  const td = (t, a = "center", b = false) => ({ text: t, options: { align: a, fontSize: 11.5, color: SLATE, bold: b } });
  const rows = [
    [Hd("Agent / total", "left"), Hd("Qwen-only"), Hd("M3-only"), Hd("Mixed")],
    [td("coder", "left", true), td("6.59M (285)"), td("9.48M (421)"), td("6.60M (288)")],
    [td("reviewer", "left", true), td("0.85M (69)"), td("2.04M (123)"), td("1.20M (77)")],
    [td("test_writer", "left", true), td("0.93M (43)"), td("0.77M (36)"), td("1.16M (45)")],
    [td("browser_test_writer", "left", true), td("0.30M (16)"), td("0.32M (16)"), td("0.35M (16)")],
    [td("architect", "left", true), td("0.38M (37)"), td("0.35M (31)"), td("0.35M (32)")],
    [td("planning_reviewer", "left", true), td("0.16M (20)"), td("0.17M (20)"), td("0.17M (20)")],
    [td("requirement_analyzer", "left", true), td("0.07M (20)"), td("0.05M (20)"), td("0.05M (20)")],
    [
      { text: "TOTAL", options: { align: "left", bold: true, color: WHITE, fill: { color: ACCENTD }, fontSize: 12 } },
      { text: "9.30M (490)", options: { align: "center", bold: true, color: WHITE, fill: { color: ACCENTD }, fontSize: 12 } },
      { text: "13.19M (667)", options: { align: "center", bold: true, color: WHITE, fill: { color: ACCENTD }, fontSize: 12 } },
      { text: "9.88M (498)", options: { align: "center", bold: true, color: WHITE, fill: { color: ACCENTD }, fontSize: 12 } },
    ],
  ];
  s.addTable(rows, { x: ML, y: 1.8, w: 12.1, colW: [4.0, 2.7, 2.7, 2.7], rowH: 0.46, border: { pt: 1, color: "E2E8F0" }, valign: "middle", fontFace: BFONT });
  s.addText("Total tokens (model calls). Recomputed uniformly from on-disk agent transcripts, 2026-06-22.", {
    x: ML, y: 6.45, w: 12, h: 0.4, fontFace: BFONT, fontSize: 11, italic: true, color: MUTED, margin: 0,
  });
  footer(s);
}

// ============================================================== SLIDE 21 — BACKUP caveats
{
  const s = pres.addSlide();
  contentHeader(s, "Backup", "Caveats & threats to validity");
  const cav = [
    ["Incomplete projects", "4–6 of 20 projects remained pending under the iteration caps in all three runs (completed: Mixed 16, M3 16, Qwen 14)."],
    ["Modest top-end margin", "Mixed vs M3-only is +1.4 pts on official score; the decisive gap is against Qwen-only (+4.5 pts). The margin is consistent across metrics."],
    ["Single benchmark", "results are on ProjectEval Level 2; generalization to other benchmarks is future work."],
    ["Serving asymmetry", "M3 served via HF router (slow, long timeouts); Qwen local vLLM. Token counts are comparable; wall-clock is not."],
  ];
  let yy = 1.9;
  cav.forEach((c) => {
    s.addShape(pres.shapes.RECTANGLE, { x: ML, y: yy, w: W - 2 * ML, h: 1.05, fill: { color: CARDBG }, line: { color: "E2E8F0", width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x: ML, y: yy, w: 0.08, h: 1.05, fill: { color: ACCENT } });
    s.addText(c[0], { x: ML + 0.3, y: yy + 0.14, w: 11.5, h: 0.35, fontFace: BFONT, fontSize: 15, bold: true, color: NAVY, margin: 0 });
    s.addText(c[1], { x: ML + 0.3, y: yy + 0.5, w: 11.6, h: 0.5, fontFace: BFONT, fontSize: 12.5, color: SLATE, margin: 0, lineSpacingMultiple: 1.0 });
    yy += 1.17;
  });
  footer(s);
}

pres.writeFile({ fileName: "MASS_presentation.pptx" }).then((f) => console.log("WROTE", f));
