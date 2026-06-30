from __future__ import annotations
import argparse
import csv
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import yaml
from app.agents.single_agent import SingleAgent
from app.analysis.static_analyzer import analyze_generated_project
from app.benchmark.contract import build_benchmark_contract, classify_parameter, compact_contract_for_prompt
from app.graph.checkpoint import checkpoint_summary, load_checkpoint
from app.graph.state import append_message, build_initial_state
from app.llm.base_client import BaseLLMClient, ChatMessage
from app.llm.factory import create_llm_registry
from app.llm.model_config import load_model_configs, load_system_config
from app.tools.file_tools import FileTool
from app.workflow import run_workflow
logger = logging.getLogger(__name__)
PROJECTEVAL_FIXED_TEST_TOTAL = 284
AGENT_EVENT_STDOUT_PREFIX = '__MASS_AGENT_EVENT__ '
PROJECTEVAL_WEBSITE_PORT = 8000

@dataclass(slots=True)
class ProjectEvalMission:
    project_id: str
    project_type: str
    technical_stack: str
    nl_prompt: str
    nl_checklist: list[dict[str, Any]]
    skeleton: list[dict[str, Any]]
    testcode: list[dict[str, Any]]

def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(name)s | %(message)s')

def emit_benchmark_agent_event(event: Any, *, project_id: str, level: int, mode: str) -> None:
    if hasattr(event, 'to_dict'):
        payload = event.to_dict()
    elif isinstance(event, dict):
        payload = dict(event)
    else:
        return
    metadata = payload.get('metadata')
    if not isinstance(metadata, dict):
        metadata = {}
    payload['metadata'] = {**metadata, 'project_id': str(project_id), 'level': int(level), 'mode': mode}
    print(AGENT_EVENT_STDOUT_PREFIX + json.dumps(payload, ensure_ascii=True, separators=(',', ':')), flush=True)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the MAS system on ProjectEval and compute Pass@1.')
    parser.add_argument('--config', default=None)
    parser.add_argument('--projecteval-root', default='external/ProjectEval')
    parser.add_argument('--models-config', default='configs/models_production.yaml')
    parser.add_argument('--system-config', default='configs/system.yaml')
    parser.add_argument('--level', type=int, choices=[1, 2, 3], default=1)
    parser.add_argument('--mode', choices=['direct', 'cascade'], default='direct')
    parser.add_argument('--project-ids', default='all', help="Comma-separated ids or 'all'.")
    parser.add_argument('--workspace-root', default='benchmark_runs/projecteval')
    parser.add_argument('--model-label', default='gemini-mas-qwen-coder')
    parser.add_argument('--parameter-role', default='parameter_solver')
    parser.add_argument('--parameter-repair-role', default='parameter_repairer')
    parser.add_argument('--run-judge', action='store_true')
    parser.add_argument('--run-indicators', action='store_true')
    parser.add_argument('--experiment-date', default=None)
    parser.add_argument('--archive-root', default='benchmark_archives/projecteval')
    parser.add_argument('--archive-threshold', type=float, default=0.5)
    parser.add_argument('--scoreboard-path', default='benchmark_archives/projecteval/projecteval_scoreboard.csv')
    parser.add_argument('--scoreboard-system-name', default=None)
    parser.add_argument('--reuse-completed-workspaces', action='store_true', help='Include already generated project workspaces from the same workspace root in the final export/judge run.')
    parser.add_argument('--resume-interrupted-workspaces', action='store_true', help='Resume interrupted multi-agent workspaces from workflow_checkpoint.json when available.')
    parser.add_argument('--post-core-only', action='store_true', help='Only reuse an existing generated workspace for parameter generation/export/judge; never regenerate the core project.')
    parser.add_argument('--regenerate-parameters', action='store_true', help='Regenerate ProjectEval parameter values even when a cached projecteval_parameter_values.json exists.')
    parser.add_argument('--core-mode', choices=['multi_agent', 'single_agent', 'opencode'], default='multi_agent')
    parser.add_argument('--single-agent-iterations', type=int, default=4)
    parser.add_argument('--opencode-model', default='local-minimax//mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7')
    parser.add_argument('--opencode-cli-path', default='opencode')
    parser.add_argument('--opencode-timeout-seconds', type=int, default=600)
    return parser.parse_args()

def load_runner_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with Path(path).open('r', encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}

def load_projecteval_dataset(dataset_path: Path) -> dict[str, ProjectEvalMission]:
    raw = json.loads(dataset_path.read_text(encoding='utf-8'))
    missions: dict[str, ProjectEvalMission] = {}
    for item in raw:
        technical_stack = item['framework_technical_stack'][0]['technical_stack']
        missions[item['project_id']] = ProjectEvalMission(project_id=item['project_id'], project_type=item['project_type'], technical_stack=technical_stack, nl_prompt=item['nl_prompt'], nl_checklist=item['nl_checklist'], skeleton=item['skeleton'], testcode=item['testcode'])
    return missions

def parse_project_ids(value: str, available_ids: list[str]) -> list[str]:
    if value == 'all':
        return available_ids
    parsed = [item.strip() for item in value.split(',') if item.strip()]
    missing = sorted(set(parsed).difference(available_ids))
    if missing:
        raise ValueError(f"Unknown ProjectEval project ids: {', '.join(missing)}")
    return parsed

def build_level_task(mission: ProjectEvalMission, level: int) -> str:
    if level == 1:
        body = mission.nl_prompt
    elif level == 2:
        body = json.dumps(mission.nl_checklist, indent=2, ensure_ascii=True)
    else:
        body = json.dumps(mission.skeleton, indent=2, ensure_ascii=True)
    return f'ProjectEval project_id={mission.project_id}\nProject type: {mission.project_type}\nTechnical stack: {mission.technical_stack}\nInput level: {level}\nGenerate a runnable project that satisfies the provided ProjectEval task.\nImportant constraints:\n- Respect the requested technical stack exactly.\n- Do not generate self-authored benchmark tests unless the task explicitly requires application-owned tests.\n- External evaluation will be performed by ProjectEval, so prioritize application behavior, routes, entrypoints, and stable element ids/selectors.\n- For website tasks, ensure the homepage loads and required pages are reachable.\nStatic benchmark-oriented guardrails:\n- Prefer predictable structure over cleverness: use stable routes, stable entrypoints, and explicit file organization.\n- For websites, prefer multi-page flows and server-rendered UI over hidden client-side state for core interactions.\n- Keep critical interactive elements present in the DOM in a deterministic way, with stable identifiers when the task suggests externally observable UI elements.\n- For batch/CLI projects, provide an obvious runnable entrypoint and consistent output paths or filenames.\n- Avoid placeholder implementations, random identifiers, and fragile startup assumptions.\n\n{body}\n\nUse the task description, technical stack, and static project guardrails as the implementation source of truth.'
_ELEMENT_TYPE_HINTS: list[tuple[str, str]] = [('_input_id', '<input> field — put the id directly on the <input> tag, NOT on a wrapper <div>'), ('_select_id', '<select> dropdown — put the id directly on the <select> tag'), ('_button_id', '<button> or <a> (must be clickable) — put the id directly on the element'), ('_link_id', '<a> link — put the id directly on the <a> tag'), ('_result_id', 'result/output container — render as placeholder on initial GET, not only after POST'), ('_display_id', 'display container — render as placeholder on initial GET, not only after POST'), ('_box_id', 'output container — render as placeholder on initial GET, not only after POST'), ('_element_id', 'main section/container of this page'), ('_id', 'interactive or display element')]
_INPUT_KEYWORD_OVERRIDE = 'input'
_NAVIGATION_FUNCTIONS: frozenset[str] = frozenset({'Navigation to', 'Navigate to', 'Go to', 'Link to', 'Open'})

def _infer_element_type(name: str) -> str:
    lowered = name.lower()
    if _INPUT_KEYWORD_OVERRIDE in lowered and (not lowered.endswith('_input_id')):
        if lowered.endswith('_box_id') or lowered.endswith('_id'):
            return '<input> field — put the id directly on the <input> tag, NOT on a wrapper <div>'
    for suffix, hint in _ELEMENT_TYPE_HINTS:
        if name.endswith(suffix):
            return hint
    return 'element'

def _is_navigation_destination(fn: str, name: str, page_ids: list[str]) -> bool:
    """Return True if this ID is likely the destination-page marker for a navigation function."""
    fn_lower = fn.lower()
    is_nav = any((kw.lower() in fn_lower for kw in _NAVIGATION_FUNCTIONS))
    if not is_nav:
        return False
    return page_ids.index(name) > 0
_OPENCODE_DEDICATED_KINDS: frozenset[str] = frozenset({'id', 'url'})
_OTHER_SELECTOR_HINTS: dict[str, str] = {'name': 'located by the name= attribute — put name="…" on the actual form element', 'class': 'located by CSS class — the element must carry this exact class', 'css': 'located by this CSS selector — keep the matching structure/class/tag', 'xpath': 'located by this XPath — preserve the targeted tag and structure', 'text': 'exact visible text that must appear in the rendered output', 'value': 'exact input value or command the judge sends / checks', 'file': 'exact file path or filename the judge reads or writes', 'other': 'judge-facing value — reproduce it exactly as named'}

def _render_other_selectors(contract: dict[str, Any]) -> list[str]:
    """Render every judge-facing selector kind that is NOT an id/url, grouped by page."""
    selectors = contract.get('selectors') or {}
    by_page: dict[str, list[tuple[str, str, str, str]]] = {}
    for kind, items in selectors.items():
        if kind in _OPENCODE_DEDICATED_KINDS or not isinstance(items, list):
            continue
        for sel in items:
            if not isinstance(sel, dict):
                continue
            page = sel.get('page', '')
            by_page.setdefault(page, []).append((kind, sel.get('name', ''), sel.get('function', ''), str(sel.get('answer', '')).strip()))
    if not by_page:
        return []
    lines: list[str] = ['', 'OTHER JUDGE-FACING LOCATORS — besides element ids, the judge also matches by', 'name attribute, CSS class, CSS selector, XPath, exact visible text, command', 'value, and filename. Implement EVERY one exactly; do not rename or omit any.']
    present = {kind for entries in by_page.values() for kind, *_rest in entries}
    for kind in sorted(present):
        hint = _OTHER_SELECTOR_HINTS.get(kind)
        if hint:
            lines.append(f'  [{kind}] {hint}')
    seen: set[tuple[str, str, str]] = set()
    for page, entries in by_page.items():
        lines.append(f'\n  Page: {page}')
        for kind, name, fn, answer in entries:
            key = (page, kind, name)
            if key in seen:
                continue
            seen.add(key)
            answer_note = f'  = "{answer}"' if answer else ''
            fn_note = f'  →  {fn}' if fn else ''
            lines.append(f'    [{kind}] {name}{answer_note}{fn_note}')
    return lines

def _build_url_map(contract: dict[str, Any]) -> dict[str, str]:
    """Map page names to their test URLs using the url-type selectors in the contract."""
    url_map: dict[str, str] = {}
    for sel in (contract.get('selectors') or {}).get('url', []):
        page = sel.get('page', '')
        answer = sel.get('answer', '').strip()
        if page and answer and (page not in url_map):
            url_map[page] = answer
    return url_map

def _django_guardrails() -> str:
    return 'DJANGO BENCHMARK GUARDRAILS — apply to every file you generate:\n\nStartup (blocking — manage.py check must pass):\n- manage.py must be at the project root (never inside a package directory)\n- SECRET_KEY = "projecteval-local-secret-key"  (non-empty literal, not from env)\n- ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]\n- Include migrations/__init__.py + valid 0001_initial.py for every app with models\n- For flat layouts (settings.py at root): BASE_DIR = Path(__file__).resolve().parent\n\nTemplates:\n- Every template using {% static %} MUST have {% load static %} at the very top of that file\n- Each page template MUST override {% block title %} (base template must define {% block title %})\n- Never call Python functions with args inside {{ ... }} — use {% url \'name\' %} for links\n- If TEMPLATES["DIRS"] includes root templates/, root templates shadow app templates — keep only one\n\nSelectors & DOM (critical for judge score):\n- result/display/box/output containers MUST be present in DOM on initial GET as empty placeholders\n  — do NOT hide them inside {% if result %} or render only after POST\n- Every mapped URL must return HTTP 200 on direct GET with all its required IDs present\n- Never protect a mapped URL with @login_required unless the contract explicitly requires auth\n- For navigation functions: the destination-page marker ID must be in the destination template,\n  not in the source template as a second navigation link\n\nForms & models:\n- Never include auto_now=True / auto_now_add=True / editable=False fields in ModelForm.Meta.fields\n- Use ChoiceField with literal choices for static dropdowns (not ModelChoiceField on empty DB)\n- Wrap homepage/dashboard model queries in try/except OperationalError for fresh-DB safety'

def _console_guardrails() -> str:
    return 'CONSOLE / BATCH BENCHMARK GUARDRAILS — apply to every file you generate:\n\nLanguage & entrypoint (blocking):\n- Implement in the language of the requested technical stack. When the stack is None/unspecified, use Python with a root-level main.py.\n- NEVER infer the language from the task\'s theme or name: a game called "Bash Crawl" or "Shell Quest" is still a Python program, not a Bash/shell project.\n- Provide ONE obvious runnable entrypoint at the project root (main.py unless the contract names another). The judge runs this entrypoint directly; if it is missing or implemented as shell/Make/non-entrypoint files, the project scores ~0.\n- Keep it simple and centralized: prefer one entrypoint file over many modules — extra modularization adds import/entrypoint failure surface with no judge-facing value.\n\nI/O contract (critical for score):\n- The program is driven via stdin/stdout. Implement exactly the menu options, commands, prompts, and expected output texts in the contract; match command keywords and expected texts literally. Do NOT invent a richer or alternative command interface.\n- Keep required input and output filenames EXACT. A fresh run must CREATE the expected output file itself, with the exact contract filename, in the current working directory — never inside a subfolder and never assuming it already exists.\n- Distinguish the current working directory from the source-file directory when resolving paths.\n- Keep exit codes and stdout error messages deterministic.\n\nStack specifics:\n- Matplotlib / charting: save each required figure with savefig using the EXACT filename, format and location from the contract; run headless (never plt.show()); produce one file per required chart.\n- Statistical / data stacks (Statsmodels, pandas, numpy): emit the exact expected values, in the exact format and with the exact labels the contract specifies; no decorative wrapper text the judge does not expect.'

def build_opencode_prompt(user_task: str, contract: dict[str, Any], project_type: str='') -> str:
    """Enrich the base task prompt with benchmark contract details for opencode."""
    lines: list[str] = [user_task]
    lines += ['', '=' * 60, 'BENCHMARK CONTRACT — READ THIS CAREFULLY', '=' * 60]
    id_selectors: list[dict[str, Any]] = (contract.get('selectors') or {}).get('id', [])
    url_map = _build_url_map(contract)
    if id_selectors:
        lines.append('')
        lines.append('The external judge locates HTML elements by EXACT id attributes.\nRules:\n  • Each id must be on the template/page listed — NOT on a different page\n  • DESTINATION markers (tagged below) must be in the DESTINATION page template,\n    NOT on the source/link page — the test navigates to the destination first\n  • <input> and <select> ids must be on the actual <input>/<select> tag,\n    NOT on a wrapper <div> — the judge does send_keys() directly on the element\n  • result/display/box containers must exist in the DOM on initial GET (empty placeholder)\n  • Do NOT rename or omit any id')
        by_page: dict[str, list[dict[str, Any]]] = {}
        for sel in id_selectors:
            by_page.setdefault(sel.get('page', ''), []).append(sel)
        for page, sels in by_page.items():
            url_hint = f'  →  URL: {url_map[page]}' if page in url_map else ''
            lines.append(f'\n  Page: {page}{url_hint}')
            fn_ids: dict[str, list[str]] = {}
            for sel in sels:
                fn = sel.get('function', '')
                name = sel.get('name', '')
                fn_ids.setdefault(fn, []).append(name)
            seen: set[str] = set()
            for sel in sels:
                name = sel.get('name', '')
                fn = sel.get('function', '')
                if name in seen:
                    continue
                seen.add(name)
                elem_type = _infer_element_type(name)
                is_dest = _is_navigation_destination(fn, name, fn_ids.get(fn, [name]))
                if is_dest:
                    dest_pages = [p for p in by_page if p != page]
                    dest_url_hint = ''
                    for dp in dest_pages:
                        if dp in url_map:
                            dest_url_hint = f' (put in template for {dp}, URL: {url_map[dp]})'
                            break
                    dest_tag = f'  ← DESTINATION MARKER: must be in the DESTINATION template, NOT this page{dest_url_hint}'
                else:
                    dest_tag = ''
                lines.append(f'    id="{name}"  [{elem_type}]  →  {fn}{dest_tag}')
    urls: list[str] = contract.get('urls') or []
    if urls:
        lines.append('')
        lines.append('URL routes that must be accessible via direct GET (HTTP 200):')
        for url in urls[:15]:
            lines.append(f'  {url}')
    expected_texts: list[str] = (contract.get('testcode_signals') or {}).get('expected_texts', [])
    filtered_texts = [t for t in expected_texts if t and t != 'value']
    if filtered_texts:
        lines.append('')
        lines.append('Text values that must appear in the rendered UI:')
        for text in filtered_texts[:20]:
            lines.append(f'  "{text}"')
    lines += _render_other_selectors(contract)
    lines += ['', '=' * 60]
    if project_type == 'website':
        lines += ['', _django_guardrails(), '']
    elif project_type in ('console', 'batch'):
        lines += ['', _console_guardrails(), '']
    lines.append('Implement ALL element IDs and locators above exactly as listed. Apply all guardrails.')
    return '\n'.join(lines)

def run_single_agent_projecteval_workflow(*, mission: ProjectEvalMission, level: int, mode: str, workspace: Path, models_config_path: str | Path, system_config_path: str | Path, max_iterations: int, run_static_analysis: bool, event_callback: Any | None=None) -> dict[str, Any]:
    """Run the single-agent baseline core while preserving MASS post-core."""
    models_config = load_model_configs(models_config_path)
    system_config = load_system_config(system_config_path)
    llm_registry = create_llm_registry(models_config)
    file_tool = FileTool(workspace)
    agent = SingleAgent(llm=llm_registry['coder'], prompt_path=Path('app/prompts/single_agent.txt'), file_tool=file_tool)
    user_task = build_level_task(mission, level)
    state = build_initial_state(user_task=user_task, workspace=workspace.resolve(), system_config=system_config)
    benchmark_context = {'project_id': mission.project_id, 'project_type': mission.project_type, 'technical_stack': mission.technical_stack, 'level': level, 'mode': mode}
    contract = build_benchmark_contract(project_id=mission.project_id, project_type=mission.project_type, technical_stack=mission.technical_stack, level=level, mode=mode, testcode=mission.testcode, nl_checklist=mission.nl_checklist)
    state.update({'benchmark_name': 'projecteval', 'benchmark_context': benchmark_context, 'benchmark_testcode': mission.testcode, 'benchmark_checklist': mission.nl_checklist, 'benchmark_contract': contract, 'benchmark_contract_compact': compact_contract_for_prompt(contract), 'max_coding_iterations': max(1, int(max_iterations)), 'event_callback': event_callback})
    workspace.mkdir(parents=True, exist_ok=True)
    artifact_dir = workspace / 'artifacts'
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / 'benchmark_contract.json').write_text(json.dumps(contract, indent=2), encoding='utf-8')
    static_analysis_results: dict[str, Any] = {}
    final_status = 'running'
    test_status = 'not_run'
    for _ in range(max(1, int(max_iterations))):
        update = agent.run(state)
        state.update(update)
        generated_root_value = state.get('artifacts', {}).get('generated_root')
        if run_static_analysis and generated_root_value:
            static_analysis_results = analyze_generated_project(Path(generated_root_value), benchmark_contract=state.get('benchmark_contract', {}))
            state['static_analysis_results'] = static_analysis_results
            state['messages'] = append_message(state, 'static_analysis', str(static_analysis_results.get('summary') or 'Static analysis completed.'))
        lint_success = bool(state.get('lint_results', {}).get('success', True))
        static_success = bool(static_analysis_results.get('success', True)) if static_analysis_results else True
        if lint_success and static_success:
            final_status = 'completed'
            test_status = 'passed'
            break
        test_status = 'failed_validation' if not static_success else 'failed_bug'
    if final_status != 'completed':
        final_status = 'incomplete'
    generated_root = state.get('artifacts', {}).get('generated_root')
    report_path = artifact_dir / 'final_report.json'
    report_payload = {'user_task': user_task, 'requirements': 'Single-agent baseline: requirements, planning, coding, and review are handled inside one agent.', 'architecture_plan': 'Single-agent baseline: no separate architecture agent was used.', 'implementation_summary': state.get('implementation_summary', ''), 'review_status': 'single_agent_completed' if final_status == 'completed' else 'single_agent_incomplete', 'validation_results': {}, 'validation_status': 'not_run', 'static_analysis_results': static_analysis_results, 'dynamic_test_results': {}, 'browser_test_results': {}, 'test_status': test_status, 'final_status': final_status, 'iterations': {'planning': 0, 'coding': state.get('coding_iteration', 0), 'global': 1}, 'test_results': {'command': [], 'returncode': 0 if final_status == 'completed' else 1, 'success': final_status == 'completed', 'stdout': '', 'stderr': str(static_analysis_results.get('summary', '')) if static_analysis_results else '', 'note': 'Single-agent baseline uses deterministic syntax/framework/static validation; no LLM test-writer agents.'}, 'test_writer_summary': 'Not run in single-agent baseline.', 'browser_test_summary': 'Not run in single-agent baseline.', 'generated_root': generated_root, 'traces': state.get('traces', []), 'benchmark_summary': {'core_mode': 'single_agent', 'total_traces': len(state.get('traces', [])), 'static_analysis_blocked_tests': bool(static_analysis_results) and (not static_analysis_results.get('success', True)), 'dynamic_tests_ran': False, 'browser_tests_ran': False, 'benchmark_contract_hash': contract.get('hash'), 'benchmark_contract_summary': contract.get('summary')}}
    report_path.write_text(json.dumps(report_payload, indent=2), encoding='utf-8')
    return {**state, 'final_status': final_status, 'test_status': test_status, 'final_output_path': str(report_path), 'artifacts': {**state.get('artifacts', {}), 'final_report': str(report_path), 'benchmark_contract': str(artifact_dir / 'benchmark_contract.json')}}

def build_opencode_review_prompt(contract: dict[str, Any]) -> str:
    """Build the contract-compliance review prompt for the opencode review pass."""
    url_map = _build_url_map(contract)
    id_selectors: list[dict[str, Any]] = (contract.get('selectors') or {}).get('id', [])
    name_selectors: list[dict[str, Any]] = (contract.get('selectors') or {}).get('name', [])
    by_page: dict[str, list[dict[str, Any]]] = {}
    for sel in id_selectors:
        by_page.setdefault(sel.get('page', ''), []).append(sel)
    name_by_page: dict[str, list[str]] = {}
    for sel in name_selectors:
        nm = sel.get('name', '')
        if nm:
            name_by_page.setdefault(sel.get('page', ''), []).append(nm)
    page_id_lines: dict[str, list[str]] = {}
    for page, sels in by_page.items():
        seen: set[str] = set()
        rows: list[str] = []
        for sel in sels:
            name = sel.get('name', '')
            if name in seen:
                continue
            seen.add(name)
            elem_type = _infer_element_type(name)
            rows.append(f'    id="{name}"  [{elem_type}]')
        page_id_lines[page] = rows
    lines: list[str] = ['CONTRACT COMPLIANCE REVIEW — do NOT regenerate the project.', '', 'The project was already generated in the current directory.', 'Work through the four phases below IN ORDER. Fix only what is wrong.', 'Do NOT rename, restructure, or add features.', '']
    lines += ['=' * 60, 'PHASE 1 — MAP PAGES TO TEMPLATE FILES', '=' * 60, '', 'Run:', "  find . -type f \\( -name '*.html' -o -name '*.htm' \\) | sort", '', 'For each page in the contract, identify which template file serves it.', 'Use the URL hints below to match templates to pages:', '']
    for page in by_page:
        url_hint = url_map.get(page, '')
        url_note = f'  (URL: {url_hint})' if url_hint else ''
        lines.append(f'  Page: {page}{url_note}')
    lines.append('')
    lines += ['=' * 60, 'PHASE 2 — STATIC TEMPLATE VERIFICATION', '=' * 60, '', 'For each page, read its template file and verify:', '  a) Every required id= attribute is present in THAT file (not another template)', '  b) The element type matches the semantic expectation:', '       *_input_id  -> must be on an <input> tag', '       *_select_id -> must be on a <select> tag', '       *_button_id -> must be on a <button> or <a> tag', '       *_link_id   -> must be on an <a> tag', '       *_result_id / *_display_id / *_box_id -> must be present as an empty', '                     placeholder on initial GET (NOT inside {% if result %})', '  c) DESTINATION markers must be in the destination template, NOT the source', '', 'Required IDs per page:', '']
    for page, rows in page_id_lines.items():
        url_hint = url_map.get(page, '')
        url_note = f'  (URL: {url_hint})' if url_hint else ''
        lines.append(f'  Page: {page}{url_note}')
        lines.extend(rows)
        lines.append('')
    lines += ['For each missing or misplaced id: READ the template, locate the correct', 'element (or add a new one if needed), add the id= attribute, and SAVE.', '']
    other_locator_lines = _render_other_selectors(contract)
    if other_locator_lines:
        lines += ['=' * 60, 'PHASE 2b — OTHER JUDGE-FACING LOCATORS', '=' * 60, '', 'The judge also matches by name attribute, CSS class/selector, XPath, exact', 'visible text, command value, and filename. For each locator below, verify it', "is present on the correct page/template (or in the program's output for", 'console/batch projects) and fix anything missing or renamed. Do NOT rename', 'or omit any.']
        lines += other_locator_lines
        lines.append('')
    result_ids = [sel.get('name', '') for sel in id_selectors if any((sel.get('name', '').endswith(s) for s in ('_result_id', '_display_id', '_box_id')))]
    if result_ids:
        lines += ['=' * 60, 'PHASE 3 — RESULT/DISPLAY CONTAINER VISIBILITY', '=' * 60, '', 'These IDs must be present in the DOM on the initial GET request', '(as an empty placeholder — NOT hidden inside {% if result %}):', '']
        for rid in result_ids:
            lines.append(f'  id="{rid}"')
        lines += ['', 'Check each template: if the container is wrapped in a conditional that', 'hides it on initial load, move it outside the conditional (keep the', 'conditional only on the content/text inside the container).', 'Example fix:', '  WRONG:  {% if result %}<div id="bmi_result_id">{{ result }}</div>{% endif %}', '  RIGHT:  <div id="bmi_result_id">{% if result %}{{ result }}{% endif %}</div>', '']
    else:
        lines += ['', 'PHASE 3 — skipped (no result/display containers in contract)', '']
    project_type = str(contract.get('project_type') or '').strip().lower()
    if project_type in ('console', 'batch'):
        expected_texts = [t for t in (contract.get('testcode_signals') or {}).get('expected_texts', []) if t and t != 'value']
        file_answers = [str(sel.get('answer', '')).strip() for sel in (contract.get('selectors') or {}).get('file', []) if str(sel.get('answer', '')).strip()]
        lines += ['=' * 60, 'PHASE 4 — RUNTIME VERIFICATION (run the program)', '=' * 60, '', 'This is a console/batch program — there is NO web server. Verify it runs from', "the project root and reproduces the contract's stdout text and output files.", '', 'Step 4a — confirm a runnable Python entrypoint exists at the root:', "  test -f main.py || echo 'MISSING root entrypoint main.py'", "  ls *.sh Makefile 2>/dev/null && echo 'WARNING: shell/Make files present — the judge runs a Python entrypoint, not shell scripts'", '', 'Step 4b — install requirements if present:', '  if [ -f requirements.txt ]; then pip install -q -r requirements.txt; fi', '', 'Step 4c — run a fresh invocation and capture stdout (feed documented commands', 'via stdin if the program is interactive):', "  printf '\\n' | python main.py > /tmp/run_out.txt 2>&1 || echo 'PROGRAM CRASHED'", '']
        if expected_texts:
            lines.append('Step 4d — verify each expected text appears in stdout:')
            for text in expected_texts[:20]:
                safe = text.replace("'", "'\\''")
                lines.append(f"  grep -qF '{safe}' /tmp/run_out.txt || echo 'MISSING expected text: {text}'")
            lines.append('')
        if file_answers:
            lines.append('Step 4e — verify each required output file is created in the CWD with the exact name:')
            for fn in file_answers[:20]:
                safe_fn = fn.replace("'", "'\\''")
                lines.append(f"  test -f '{safe_fn}' || echo 'MISSING output file: {fn}'")
            lines.append('')
        else:
            lines += ['Step 4e — if the task produces an output file, run the program and confirm the', 'file is created in the current directory with the EXACT contract filename.', '']
        lines += ['Step 4f — for every MISSING item above, fix the entrypoint, the printed text, or', 'the output path/filename, then re-run until all checks pass.', '', '=' * 60, 'When all phases are complete, summarise what was missing and how you fixed it.']
        return '\n'.join(lines)
    lines += ['=' * 60, 'PHASE 4 — RUNTIME VERIFICATION (curl live server)', '=' * 60, '', 'Run the following shell commands to verify IDs are present in actual', 'HTTP responses. Fix any IDs that are missing from the live HTML.', '', 'Step 4a — kill any server already on port 8000:', '  fuser -k 8000/tcp 2>/dev/null || true', '', 'Step 4b — install requirements and run migrations (if Django):', '  if [ -f requirements.txt ]; then pip install -q -r requirements.txt; fi', '  if [ -f manage.py ]; then', '    python manage.py makemigrations --run-syncdb 2>/dev/null || true', '    python manage.py migrate --run-syncdb 2>/dev/null || true', '  fi', '', 'Step 4c — start the server in the background:', '  if [ -f manage.py ]; then', '    python manage.py runserver 8000 &', '  else', '    python main.py &', '  fi', '  SERVER_PID=$!', '  sleep 4', '', 'Step 4d — curl each page and grep for required IDs:', '']
    for page, rows in page_id_lines.items():
        url = url_map.get(page, 'http://127.0.0.1:8000/')
        lines.append(f'  # Page: {page}')
        lines.append(f"  curl -sf '{url}' > /tmp/page_check.html || echo 'CURL FAILED for {url}'")
        for row in rows:
            id_match = re.search('id="([^"]+)"', row)
            if id_match:
                id_val = id_match.group(1)
                lines.append(f"""  grep -q 'id="{id_val}"' /tmp/page_check.html || echo 'MISSING id="{id_val}" on page: {page}'""")
        for nm in dict.fromkeys(name_by_page.get(page, [])):
            lines.append(f"""  grep -q 'name="{nm}"' /tmp/page_check.html || echo 'MISSING name="{nm}" on page: {page}'""")
        lines.append('')
    lines += ['Step 4e — stop the server:', '  kill $SERVER_PID 2>/dev/null || true', '', 'Step 4f — for every MISSING id reported above, go back to Phase 2 and fix it.', '', '=' * 60, 'When all four phases are complete, summarise:', '  - which IDs were missing and where you added them', '  - which result containers were hidden and how you fixed them', '  - which curl checks passed/failed and what you fixed']
    return '\n'.join(lines)

def run_opencode_projecteval_workflow(*, mission: ProjectEvalMission, level: int, mode: str, workspace: Path, opencode_model: str, opencode_cli_path: str, opencode_timeout_seconds: int, run_static_analysis: bool, event_callback: Any | None=None) -> dict[str, Any]:
    """Run opencode as core generation step, then hand off to the standard MASS post-core pipeline."""
    from app.benchmark.opencode_runner import export_opencode_session, run_opencode_for_project
    user_task = build_level_task(mission, level)
    workspace.mkdir(parents=True, exist_ok=True)
    artifact_dir = workspace / 'artifacts'
    artifact_dir.mkdir(parents=True, exist_ok=True)
    generated_project_dir = workspace / 'generated_project'
    contract = build_benchmark_contract(project_id=mission.project_id, project_type=mission.project_type, technical_stack=mission.technical_stack, level=level, mode=mode, testcode=mission.testcode, nl_checklist=mission.nl_checklist)
    (artifact_dir / 'benchmark_contract.json').write_text(json.dumps(contract, indent=2), encoding='utf-8')
    enriched_prompt = build_opencode_prompt(user_task, contract, project_type=mission.project_type)
    result = run_opencode_for_project(prompt=enriched_prompt, generated_project_dir=generated_project_dir, model=opencode_model, cli_path=opencode_cli_path, timeout_seconds=opencode_timeout_seconds, event_callback=event_callback)
    run_summary = result.get('run_summary') or {}
    if run_summary:
        (artifact_dir / 'opencode_run_summary.json').write_text(json.dumps(run_summary, indent=2), encoding='utf-8')
    session_id = result.get('session_id')
    if session_id:
        export_opencode_session(session_id, cli_path=opencode_cli_path, artifacts_dir=artifact_dir)
    review_result: dict[str, Any] = {}
    id_selectors = (contract.get('selectors') or {}).get('id', [])
    if result['status'] == 'ok' and id_selectors and generated_project_dir.exists():
        review_prompt = build_opencode_review_prompt(contract)
        logger.info('OpenCode contract review pass starting for project %s', mission.project_id)
        if event_callback:
            event_callback({'agent_name': 'OpenCodeAgent', 'event_type': 'log', 'content': '[opencode review] contract compliance review pass starting...', 'timestamp': __import__('time').strftime('%Y-%m-%dT%H:%M:%SZ', __import__('time').gmtime()), 'metadata': {}})
        review_result = run_opencode_for_project(prompt=review_prompt, generated_project_dir=generated_project_dir, model=opencode_model, cli_path=opencode_cli_path, timeout_seconds=min(opencode_timeout_seconds, 1200), event_callback=event_callback)
        review_summary = review_result.get('run_summary') or {}
        if review_summary:
            (artifact_dir / 'opencode_review_summary.json').write_text(json.dumps(review_summary, indent=2), encoding='utf-8')
        review_session_id = review_result.get('session_id')
        if review_session_id:
            export_opencode_session(review_session_id, cli_path=opencode_cli_path, artifacts_dir=artifact_dir / 'review_transcript')
        logger.info('OpenCode review pass finished — status=%s steps=%s', review_result.get('status'), (review_result.get('run_summary') or {}).get('steps', '?'))
    if result['status'] == 'ok':
        final_status = 'completed'
        test_status = 'passed'
    elif result['status'] == 'timeout':
        final_status = 'incomplete'
        test_status = 'failed_timeout'
    else:
        final_status = 'workflow_failed'
        test_status = 'workflow_failed'
    static_analysis_results: dict[str, Any] = {}
    if run_static_analysis and generated_project_dir.exists():
        static_analysis_results = analyze_generated_project(generated_project_dir, benchmark_contract=contract)
        if not static_analysis_results.get('success', True):
            test_status = 'failed_validation'
    elapsed = result.get('elapsed_seconds', 0)
    files_written = run_summary.get('files_written', [])
    steps = run_summary.get('steps', 0)
    total_tokens = run_summary.get('total_tokens', {})
    report_path = artifact_dir / 'final_report.json'
    report_payload = {'user_task': user_task, 'requirements': 'OpenCode agent: handled internally by opencode.', 'architecture_plan': 'OpenCode agent: handled internally by opencode.', 'implementation_summary': f"Generated by opencode ({opencode_model}) in {elapsed:.1f}s — {steps} steps, {len(files_written)} files written, tokens: {total_tokens.get('total', '?')}. Status: {result['status']}.", 'review_status': f"opencode_{result['status']}", 'validation_results': {}, 'validation_status': 'not_run', 'static_analysis_results': static_analysis_results, 'dynamic_test_results': {}, 'browser_test_results': {}, 'test_status': test_status, 'final_status': final_status, 'iterations': {'planning': 0, 'coding': steps or 1, 'global': 1}, 'test_results': {'command': [], 'returncode': 0 if final_status == 'completed' else 1, 'success': final_status == 'completed', 'stdout': '', 'stderr': result.get('error', ''), 'note': 'OpenCode agent: no LLM test-writer agents are used.'}, 'test_writer_summary': 'Not run in opencode mode.', 'browser_test_summary': 'Not run in opencode mode.', 'generated_root': str(generated_project_dir), 'traces': [], 'benchmark_summary': {'core_mode': 'opencode', 'opencode_model': opencode_model, 'opencode_session_id': session_id, 'opencode_elapsed_seconds': elapsed, 'opencode_status': result['status'], 'opencode_steps': steps, 'opencode_files_written': files_written, 'opencode_bash_commands': run_summary.get('bash_commands', []), 'opencode_total_tokens': total_tokens, 'opencode_transcript_path': str(artifact_dir / 'opencode_session_transcript.json'), 'opencode_run_summary_path': str(artifact_dir / 'opencode_run_summary.json'), 'opencode_review_status': review_result.get('status') if review_result else 'skipped', 'opencode_review_steps': (review_result.get('run_summary') or {}).get('steps') if review_result else None, 'opencode_review_summary_path': str(artifact_dir / 'opencode_review_summary.json') if review_result else None, 'total_traces': 0, 'static_analysis_blocked_tests': bool(static_analysis_results) and (not static_analysis_results.get('success', True)), 'dynamic_tests_ran': False, 'browser_tests_ran': False, 'benchmark_contract_hash': contract.get('hash'), 'benchmark_contract_summary': contract.get('summary')}}
    report_path.write_text(json.dumps(report_payload, indent=2), encoding='utf-8')
    return {'artifacts': {'generated_root': str(generated_project_dir), 'final_report': str(report_path), 'benchmark_contract': str(artifact_dir / 'benchmark_contract.json')}, 'final_status': final_status, 'test_status': test_status, 'final_output_path': str(report_path), 'traces': []}
_EXCLUDED_DIRS = {'venv', '.venv', 'env', '__pycache__', 'node_modules', '.git', '.tox', 'dist', 'build', '.eggs'}
_EXCLUDED_SUFFIXES = {'.sqlite3', '.log', '.pyc', '.pyo', '.so', '.dylib', '.dll', '.exe', '.bin', '.db'}

def project_to_json(project_root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(project_root.rglob('*')):
        if path.is_dir():
            continue
        relative = path.relative_to(project_root)
        if any((part in _EXCLUDED_DIRS for part in relative.parts)):
            continue
        if path.suffix in _EXCLUDED_SUFFIXES:
            continue
        try:
            code = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        files.append({'file': path.name, 'path': relative.as_posix(), 'code': code})
    return files

def filter_projecteval_export_files(mission: ProjectEvalMission, answer_project: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if mission.project_type == 'website':
        return [normalize_projecteval_website_export_file(item) for item in answer_project if not item['path'].startswith('tests/')]
    return answer_project

def normalize_projecteval_website_export_file(item: dict[str, Any]) -> dict[str, Any]:
    path = str(item.get('path', ''))
    code = item.get('code')
    if not path.endswith('settings.py') or not isinstance(code, str):
        return item
    if 'django.contrib.staticfiles' not in code or re.search('(?m)^\\s*STATIC_URL\\s*=', code):
        return item
    normalized = dict(item)
    normalized['code'] = code.rstrip() + "\n\nSTATIC_URL = '/static/'\n"
    return normalized

def strip_code_fences(text: str) -> str:
    content = text.strip()
    if not content.startswith('```'):
        return content
    lines = content.splitlines()
    if lines and lines[0].startswith('```'):
        lines = lines[1:]
    if lines and lines[-1].startswith('```'):
        lines = lines[:-1]
    return '\n'.join(lines).strip()

def extract_json_payload(text: str) -> str:
    content = strip_code_fences(text)
    for opening, closing in (('[', ']'), ('{', '}')):
        start = content.find(opening)
        end = content.rfind(closing)
        if start != -1 and end != -1 and (end > start):
            candidate = content[start:end + 1].strip()
            if candidate:
                return candidate
    return content

def parse_json_response_text(text: str) -> Any:
    payload = extract_json_payload(text)
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        repaired = repair_json_payload(payload)
        return json.loads(repaired)

def repair_json_payload(text: str) -> str:
    repaired = extract_json_payload(text)
    repaired = re.sub(',(\\s*[\\]}])', '\\1', repaired)
    repaired = re.sub('^\\s*json\\s*', '', repaired, flags=re.IGNORECASE)
    repaired = re.sub('```(?:json)?', '', repaired, flags=re.IGNORECASE)
    repaired = repaired.strip()
    repaired = _balance_json_brackets(repaired)
    return repaired

def _balance_json_brackets(text: str) -> str:
    repaired = text
    open_curly = repaired.count('{')
    close_curly = repaired.count('}')
    if close_curly < open_curly:
        repaired = repaired + '}' * (open_curly - close_curly)
    open_square = repaired.count('[')
    close_square = repaired.count(']')
    if close_square < open_square:
        repaired = repaired + ']' * (open_square - close_square)
    return repaired

def generate_json_response(*, client: BaseLLMClient, system_prompt: str, user_prompt: str) -> Any:
    response_format = None
    if client.capabilities.supports_json:
        response_format = {'type': 'json_object', 'mime_type': 'application/json'}
    response = client.generate(messages=[ChatMessage(role='system', content=system_prompt), ChatMessage(role='user', content=user_prompt)], response_format=response_format)
    return parse_json_response_text(response.text)

def save_parameter_solver_attempt(artifacts_dir: Path | None, mission: ProjectEvalMission, attempt: int, text: str, *, stage: str='solver') -> None:
    if artifacts_dir is None:
        return
    target_dir = artifacts_dir / 'parameter_solver'
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f'project_{mission.project_id}_attempt_{attempt}_{stage}.txt'
    target_path.write_text(text, encoding='utf-8')

def save_parameter_solver_metadata(artifacts_dir: Path | None, mission: ProjectEvalMission, attempt: int, *, stage: str, parse_error: str) -> None:
    if artifacts_dir is None:
        return
    target_dir = artifacts_dir / 'parameter_solver'
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f'project_{mission.project_id}_attempt_{attempt}_{stage}_error.json'
    target_path.write_text(json.dumps({'project_id': mission.project_id, 'attempt': attempt, 'stage': stage, 'parse_error': parse_error}, indent=2), encoding='utf-8')

def unwrap_parameter_response(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        direct_pages = result.get('page')
        if isinstance(direct_pages, list):
            return direct_pages
        for key in ('result', 'results', 'pages', 'parameters'):
            candidate = result.get(key)
            if isinstance(candidate, list):
                return candidate
    raise ValueError('Parameter solver must return a JSON list.')

def build_parameter_response_schema() -> str:
    return '{"parameters":[{"page":"...","function":[{"function":"...","parameter":[{"name":"...","answer":"..."}]}]}]}'

def build_parameter_solver_system_prompt() -> str:
    return f"You extract and solve technical parameters for system verification from generated code.\nReturn valid JSON only as an object with this exact top-level shape:\n{build_parameter_response_schema()}\nConstraints:\n- `*_xpath` parameters must be valid XPath selectors starting with `//` or `/html`. NEVER return a URL or file path.\n- `*_id` parameters must be the raw literal `id` attribute value only.\n- `*_class_name` parameters must be a single CSS class token (no spaces, no dots).\n- `test_url` and `*_url` parameters must be fully qualified absolute URLs (e.g., `http://127.0.0.1:8000/path/`).\n- CRITICAL: Test variables with generic names like `link_id` or `submit_button_id` often appear multiple times across different tests. They refer to DIFFERENT elements based on their specific `page` and `function` context. You must resolve them to the specific, unique HTML IDs implemented in the generated project for that exact workflow step.\n- NEVER return the literal string of the parameter name (e.g., answer 'link_id' for name 'link_id') unless it perfectly matches a real HTML id in the target component.\nDo not change keys. Fill every parameter answer. The top-level value must be an object."

def build_parameter_solver_user_prompt(*, mission: ProjectEvalMission, answer_project: list[dict[str, Any]]) -> str:
    return f'Technical stack: {mission.technical_stack}\nGenerated project JSON:\n{json.dumps(answer_project, indent=2, ensure_ascii=True)}\n\nParameter required descriptions:\n{json.dumps(mission.testcode, indent=2, ensure_ascii=True)}'

def repair_parameter_response(*, client: BaseLLMClient, mission: ProjectEvalMission, answer_project: list[dict[str, Any]], raw_response: str, parse_error: str) -> str:
    system_prompt = f'You repair malformed ProjectEval parameter-answer JSON.\nReturn valid JSON only.\nPreserve the original intended content as much as possible, but prefer correctness over copying malformed text.\nIf the raw output is structurally broken, reconstruct the JSON from the provided requirements and generated project.\nReturn a JSON object with this exact top-level shape:\n{build_parameter_response_schema()}\nDo not add commentary, markdown, or code fences.\nThe top-level JSON value must be an object, not a bare list.'
    user_prompt = f'ProjectEval project_id={mission.project_id}\nParse error:\n{parse_error}\n\nJSON snippet near failure:\n{build_parse_error_snippet(raw_response, parse_error)}\n\nGenerated project JSON:\n{json.dumps(answer_project, indent=2, ensure_ascii=True)}\n\nRequired parameter descriptions:\n{json.dumps(mission.testcode, indent=2, ensure_ascii=True)}\n\nMalformed raw output to repair:\n{raw_response}'
    response_format = None
    if client.capabilities.supports_json:
        response_format = {'type': 'json_object', 'mime_type': 'application/json'}
    response = client.generate(messages=[ChatMessage(role='system', content=system_prompt), ChatMessage(role='user', content=user_prompt)], response_format=response_format)
    return response.text

def solve_parameters(*, client: BaseLLMClient, repair_client: BaseLLMClient | None, mission: ProjectEvalMission, answer_project: list[dict[str, Any]], artifacts_dir: Path | None=None, max_attempts: int=5) -> list[dict[str, Any]]:
    system_prompt = build_parameter_solver_system_prompt()
    user_prompt = build_parameter_solver_user_prompt(mission=mission, answer_project=answer_project)
    response_format = None
    if client.capabilities.supports_json:
        response_format = {'type': 'json_object', 'mime_type': 'application/json'}
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        response = client.generate(messages=[ChatMessage(role='system', content=system_prompt), ChatMessage(role='user', content=user_prompt)], response_format=response_format)
        save_parameter_solver_attempt(artifacts_dir, mission, attempt, response.text, stage='solver')
        try:
            parsed = parse_json_response_text(response.text)
            return normalize_parameter_answers(unwrap_parameter_response(parsed), answer_project)
        except Exception as exc:
            last_error = exc
            save_parameter_solver_metadata(artifacts_dir, mission, attempt, stage='solver', parse_error=str(exc))
            logger.warning('Parameter solving parse failed for project %s on attempt %s/%s: %s', mission.project_id, attempt, max_attempts, exc)
            try:
                locally_repaired = repair_json_payload(response.text)
                parsed = parse_json_response_text(locally_repaired)
                save_parameter_solver_attempt(artifacts_dir, mission, attempt, locally_repaired, stage='local_repair')
                return normalize_parameter_answers(unwrap_parameter_response(parsed), answer_project)
            except Exception:
                pass
            if repair_client is not None:
                try:
                    repaired_text = repair_parameter_response(client=repair_client, mission=mission, answer_project=answer_project, raw_response=response.text, parse_error=str(exc))
                    save_parameter_solver_attempt(artifacts_dir, mission, attempt, repaired_text, stage='repair')
                    parsed = parse_json_response_text(repaired_text)
                    return normalize_parameter_answers(unwrap_parameter_response(parsed), answer_project)
                except Exception as repair_exc:
                    last_error = repair_exc
                    save_parameter_solver_metadata(artifacts_dir, mission, attempt, stage='repair', parse_error=str(repair_exc))
                    logger.warning('Parameter repair failed for project %s on attempt %s/%s: %s', mission.project_id, attempt, max_attempts, repair_exc)
            if attempt < max_attempts:
                time.sleep(min(2 * attempt, 8))
    raise ValueError(f'Parameter solving failed for project {mission.project_id} after {max_attempts} attempts: {last_error}')

def build_parse_error_snippet(raw_response: str, parse_error: str) -> str:
    match = re.search('char (\\d+)', parse_error)
    if not match:
        return extract_json_payload(raw_response)[:800]
    index = int(match.group(1))
    payload = extract_json_payload(raw_response)
    start = max(0, index - 300)
    end = min(len(payload), index + 300)
    return payload[start:end]

def build_mock_parameter_answers(mission: ProjectEvalMission) -> list[dict[str, Any]]:

    def answer_for(name: str) -> str:
        lowered = name.lower()
        if 'url' in lowered:
            return 'http://localhost:8000/'
        if lowered.endswith('_id'):
            return lowered.removesuffix('_id')
        if 'xpath' in lowered:
            return '//*'
        if 'class' in lowered:
            return 'generated-class'
        if 'path' in lowered:
            return 'main.py'
        if 'button' in lowered:
            return 'submit'
        if 'field' in lowered or 'input' in lowered:
            return 'input'
        return 'generated'
    pages: list[dict[str, Any]] = []
    for page in mission.testcode:
        functions: list[dict[str, Any]] = []
        for fn in page.get('function', []):
            functions.append({'function': fn.get('function', ''), 'parameter': [{'name': param.get('name', ''), 'answer': answer_for(param.get('name', ''))} for param in fn.get('parameter', [])]})
        pages.append({'page': page.get('page', ''), 'function': functions})
    return pages

def collect_html_ids(answer_project: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in answer_project:
        code = item.get('code')
        if not isinstance(code, str):
            continue
        for match in re.findall('id=["\\\']([^"\\\']+)["\\\']', code):
            if match not in seen:
                seen.add(match)
                ordered.append(match)
    return ordered

def collect_html_attrs(answer_project: list[dict[str, Any]], attr: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in answer_project:
        code = item.get('code')
        if not isinstance(code, str):
            continue
        for match in re.findall(f"""\\b{re.escape(attr)}=["\\']([^"\\']+)["\\']""", code):
            values = match.split() if attr == 'class' else [match]
            for value in values:
                if value and value not in seen:
                    seen.add(value)
                    ordered.append(value)
    return ordered

def score_parameter_candidate(name: str, description: str, candidate: str) -> float:
    target_tokens = set(normalize_text_tokens(f'{name} {description}'))
    candidate_tokens = set(normalize_text_tokens(candidate.replace('_', ' ').replace('-', ' ')))
    if not target_tokens or not candidate_tokens:
        return 0.0
    overlap = len(target_tokens.intersection(candidate_tokens))
    score = overlap / max(len(target_tokens), len(candidate_tokens))
    if candidate.lower() in f'{name} {description}'.lower():
        score += 0.35
    return score

def choose_best_parameter_candidate(name: str, description: str, candidates: list[str]) -> str | None:
    preferred = preferred_parameter_candidates(name)
    for candidate in preferred:
        if candidate in candidates:
            return candidate
    best: tuple[float, str] | None = None
    for candidate in candidates:
        score = score_parameter_candidate(name, description, candidate)
        if best is None or score > best[0]:
            best = (score, candidate)
    if best and best[0] >= 0.32:
        return best[1]
    return candidates[0] if len(candidates) == 1 else None

def preferred_parameter_candidates(name: str) -> list[str]:
    lowered = name.lower()
    preferred_ids = {'introduction': ['welcome-message', 'welcome-header', 'introduction', 'page-introduction', 'product-overview'], 'navigate': ['nav-to-calculator', 'nav-to-generator', 'navigate-button', 'calculator-link'], 'calculator': ['calculator-form', 'submit-btn', 'calculate-btn', 'height-input'], 'height': ['height-input', 'height', 'id_height'], 'weight': ['weight-input', 'weight', 'id_weight'], 'submit': ['submit-btn', 'submit-button', 'calculate-btn', 'convert-btn'], 'reset': ['reset-btn', 'reset-button'], 'result': ['bmi-result', 'conversion-result', 'result', 'html-output'], 'category': ['bmi-category', 'category', 'id_category'], 'interpretation': ['interpretation', 'bmi-interpretation'], 'advice': ['health-advice', 'advice'], 'username': ['id_username', 'username', 'login-username', 'register-username'], 'password1': ['id_password1', 'password1', 'register-password1'], 'password2': ['id_password2', 'password2', 'register-password2'], 'password': ['id_password', 'password', 'login-password'], 'email': ['id_email', 'email', 'register-email']}
    matches: list[str] = []
    for token, candidates in preferred_ids.items():
        if token in lowered:
            matches.extend(candidates)
    return matches

def build_deterministic_parameter_answers(mission: ProjectEvalMission, answer_project: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = collect_html_ids(answer_project)
    names = collect_html_attrs(answer_project, 'name')
    classes = collect_html_attrs(answer_project, 'class')
    anchor_texts = collect_tag_texts(answer_project, 'a')
    button_texts = collect_tag_texts(answer_project, 'button')
    pages: list[dict[str, Any]] = []
    for page in mission.testcode:
        functions: list[dict[str, Any]] = []
        page_name = str(page.get('page', ''))
        for fn in page.get('function', []) or []:
            params: list[dict[str, str]] = []
            function_name = str(fn.get('function', ''))
            test_source = str(fn.get('test', ''))
            for param in fn.get('parameter', []) or []:
                if not isinstance(param, dict):
                    continue
                name = str(param.get('name', ''))
                description = str(param.get('description', ''))
                kind = classify_parameter(name, str(param.get('answer', '')), description)
                answer = str(param.get('answer', '')).strip()
                if not answer:
                    if kind == 'url':
                        answer = infer_test_url_for_function(page_name, function_name, test_source)
                    elif kind == 'id':
                        answer = choose_best_parameter_candidate(name, description, ids) or ''
                    elif kind == 'name':
                        answer = choose_best_parameter_candidate(name, description, names + ids) or ''
                    elif kind == 'class':
                        answer = choose_best_parameter_candidate(name, description, classes) or ''
                    elif kind == 'xpath':
                        text_candidate = choose_best_text_candidate(f'{name} {description}', anchor_texts + button_texts)
                        if text_candidate in anchor_texts:
                            answer = f"//a[text()='{text_candidate}']"
                        elif text_candidate in button_texts:
                            answer = f"//button[text()='{text_candidate}']"
                    elif kind == 'file':
                        answer = infer_file_parameter_answer(name, description, answer_project)
                params.append({'name': name, 'answer': answer})
            functions.append({'function': function_name, 'parameter': params})
        pages.append({'page': page_name, 'function': functions})
    return normalize_parameter_answers(pages, answer_project)

def infer_test_url_for_function(page_name: str, function_name: str, test_source: str) -> str:
    if is_navigation_source_function(function_name):
        return infer_test_url_for_page(page_name)
    page_url = infer_test_url_for_page(page_name)
    if page_url != 'http://127.0.0.1:8000/':
        return page_url
    combined = f'{page_name} {function_name} {test_source}'.lower()
    route_hints = [('admin', '/admin/'), ('login', '/login/'), ('signup', '/signup/'), ('register', '/signup/'), ('dashboard', '/dashboard/'), ('calendar', '/calendar/'), ('generate', '/generate/'), ('converter', '/convert/'), ('convert', '/convert/'), ('calculator', '/calculator/'), ('about', '/about/'), ('pricing', '/pricing/'), ('features', '/features/'), ('support', '/support/'), ('customer', '/customers/'), ('claim', '/claims/'), ('helloworld', '/helloworld/'), ('hello world', '/helloworld/'), ('task', '/tasks/'), ('list', '/lists/')]
    for token, path in route_hints:
        if token in combined:
            return f'http://127.0.0.1:8000{path}'
    return 'http://127.0.0.1:8000/'

def infer_test_url_for_page(page_name: str) -> str:
    normalized = normalize_route_hint_text(page_name)
    if not normalized or normalized in {'home', 'homepage', 'home page', 'index', 'main'}:
        return 'http://127.0.0.1:8000/'
    route_hints = [('admin', '/admin/'), ('login', '/login/'), ('signup', '/signup/'), ('register', '/signup/'), ('dashboard', '/dashboard/'), ('calendar', '/calendar/'), ('password', '/generator/'), ('generator', '/generator/'), ('generate', '/generate/'), ('converter', '/convert/'), ('convert', '/convert/'), ('calculator', '/calculator/'), ('bmi calculator', '/calculator/'), ('helloworld', '/helloworld/'), ('hello world', '/helloworld/'), ('about', '/about/'), ('pricing', '/pricing/'), ('features', '/features/'), ('support', '/support/'), ('customer', '/customers/'), ('claim', '/claims/'), ('task', '/tasks/'), ('todo list', '/todolist/'), ('list', '/lists/')]
    for token, path in route_hints:
        if token in normalized:
            return f'http://127.0.0.1:8000{path}'
    slug = re.sub('[^a-z0-9]+', '-', normalized).strip('-')
    return f'http://127.0.0.1:8000/{slug}/' if slug else 'http://127.0.0.1:8000/'

def normalize_route_hint_text(value: str) -> str:
    value = re.sub('([a-z])([A-Z])', '\\1 \\2', value or '')
    value = value.replace('_', ' ').replace('-', ' ')
    value = re.sub('\\bpage\\b', '', value, flags=re.IGNORECASE)
    return re.sub('\\s+', ' ', value).strip().lower()

def is_navigation_source_function(function_name: str) -> bool:
    lowered = normalize_route_hint_text(function_name)
    navigation_tokens = ('button to', 'navigate to', 'navigation to', 'link to', 'access', 'quick access', 'go to', 'open')
    return any((token in lowered for token in navigation_tokens))

def infer_file_parameter_answer(name: str, description: str, answer_project: list[dict[str, Any]]) -> str:
    lowered = f'{name} {description}'.lower()
    paths = [str(item.get('path', '')) for item in answer_project if isinstance(item, dict)]
    if 'entry' in lowered:
        for candidate in ('manage.py', 'main.py', 'app.py'):
            if candidate in paths:
                return candidate
    if 'download' in lowered or 'image' in lowered or 'file' in lowered:
        return infer_download_filename(answer_project)
    return ''

def merge_parameter_answers(preferred: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fallback_lookup: dict[tuple[str, str, str], str] = {}
    for page in fallback:
        page_name = str(page.get('page', ''))
        for fn in page.get('function', []) or []:
            fn_name = str(fn.get('function', ''))
            for param in fn.get('parameter', []) or []:
                fallback_lookup[page_name, fn_name, str(param.get('name', ''))] = str(param.get('answer', ''))
    merged: list[dict[str, Any]] = []
    for page in preferred:
        page_name = str(page.get('page', ''))
        functions = []
        for fn in page.get('function', []) or []:
            fn_name = str(fn.get('function', ''))
            params = []
            for param in fn.get('parameter', []) or []:
                name = str(param.get('name', ''))
                answer = str(param.get('answer', '')).strip()
                fallback_answer = fallback_lookup.get((page_name, fn_name, name), '')
                if not answer or answer.lower() in {'none', 'null', 'n/a'}:
                    answer = fallback_answer
                elif should_prefer_deterministic_parameter(page_name, fn_name, name, answer, fallback_answer):
                    answer = fallback_answer
                elif _parameter_answer_impossible(name, answer):
                    answer = fallback_answer or answer
                params.append({'name': name, 'answer': answer})
            functions.append({'function': fn_name, 'parameter': params})
        merged.append({'page': page_name, 'function': functions})
    return merged

def should_prefer_deterministic_parameter(page_name: str, function_name: str, name: str, answer: str, fallback_answer: str) -> bool:
    if not fallback_answer:
        return False
    lowered_name = name.lower()
    if lowered_name != 'test_url':
        return False
    if not is_navigation_source_function(function_name):
        return False
    return _url_to_path_for_compare(answer) != _url_to_path_for_compare(fallback_answer)

def _url_to_path_for_compare(value: str) -> str:
    value = value.strip()
    if value.startswith('http://') or value.startswith('https://'):
        match = re.match('https?://[^/]+(/.*)?$', value)
        value = match.group(1) or '/' if match else value
    if not value.startswith('/'):
        value = f'/{value}'
    if not value.endswith('/'):
        value = f'{value}/'
    return value

def _parameter_answer_impossible(name: str, answer: str) -> bool:
    lowered = name.lower()
    if 'xpath' in lowered and answer and (not answer.startswith(('//', '/html'))):
        return True
    if lowered.endswith('_class_name') and (' ' in answer or answer.startswith('.')):
        return True
    if (lowered.endswith('_url') or lowered == 'test_url') and answer.startswith('http://example.com'):
        return True
    return False

def validate_parameter_answers(parameter_values: list[dict[str, Any]], answer_project: list[dict[str, Any]]) -> dict[str, Any]:
    ids = set(collect_html_ids(answer_project))
    names = set(collect_html_attrs(answer_project, 'name'))
    classes = set(collect_html_attrs(answer_project, 'class'))
    issues: list[dict[str, str]] = []
    total = 0
    valid = 0
    for page in parameter_values:
        for fn in page.get('function', []) or []:
            for param in fn.get('parameter', []) or []:
                total += 1
                name = str(param.get('name', ''))
                answer = str(param.get('answer', '')).strip()
                lowered = name.lower()
                issue = ''
                if not answer:
                    issue = 'empty_answer'
                elif 'xpath' in lowered and (not answer.startswith(('//', '/html'))):
                    issue = 'invalid_xpath_shape'
                elif lowered.endswith('_id') and answer not in ids:
                    issue = 'id_not_found_in_exported_html'
                elif (lowered.endswith('_field') or lowered.endswith('_name')) and answer not in names and (answer not in ids):
                    issue = 'name_or_id_not_found_in_exported_html'
                elif lowered.endswith('_class_name') and answer not in classes:
                    issue = 'class_not_found_in_exported_html'
                elif (lowered.endswith('_url') or lowered == 'test_url') and answer.startswith('http://example.com'):
                    issue = 'example_url_not_normalized'
                if issue:
                    issues.append({'page': str(page.get('page', '')), 'function': str(fn.get('function', '')), 'name': name, 'answer': answer, 'issue': issue})
                else:
                    valid += 1
    return {'total': total, 'valid': valid, 'invalid': len(issues), 'confidence': valid / total if total else 1.0, 'issues': issues[:50]}

def project_export_hash(answer_project: list[dict[str, Any]]) -> str:
    payload = json.dumps(answer_project, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    return uuid.uuid5(uuid.NAMESPACE_URL, payload).hex

def infer_download_filename(answer_project: list[dict[str, Any]]) -> str:
    for item in answer_project:
        code = item.get('code')
        if not isinstance(code, str) or 'download' not in code.lower():
            continue
        for match in re.finditer('href=["\\\']([^"\\\']+)["\\\']', code, flags=re.IGNORECASE):
            href = match.group(1)
            if '{{' in href or '}}' in href:
                continue
            candidate = Path(href).name
            if candidate and '.' in candidate:
                return candidate
    return 'qr_code.png'

def collect_tag_texts(answer_project: list[dict[str, Any]], tag: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    pattern = re.compile(f'<{tag}\\b[^>]*>(.*?)</{tag}>', flags=re.IGNORECASE | re.DOTALL)
    for item in answer_project:
        code = item.get('code')
        if not isinstance(code, str):
            continue
        for raw_text in pattern.findall(code):
            text = re.sub('<[^>]+>', ' ', raw_text)
            text = ' '.join(text.replace('&nbsp;', ' ').split())
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
    return ordered

def normalize_text_tokens(value: str) -> list[str]:
    lowered = re.sub('[^a-z0-9]+', ' ', value.lower())
    stopwords = {'the', 'a', 'an', 'new', 'manage', 'panel'}
    return [token for token in lowered.split() if token and token not in stopwords]

def choose_best_text_candidate(target: str, candidates: list[str]) -> str | None:
    if not target or not candidates:
        return None
    target_tokens = normalize_text_tokens(target)
    if not target_tokens:
        return None
    best_candidate: str | None = None
    best_score = 0.0
    target_set = set(target_tokens)
    for candidate in candidates:
        candidate_tokens = normalize_text_tokens(candidate)
        if not candidate_tokens:
            continue
        candidate_set = set(candidate_tokens)
        overlap = len(target_set.intersection(candidate_set))
        if overlap == 0:
            continue
        score = overlap / max(len(target_set), len(candidate_set))
        if target_set.issubset(candidate_set) or candidate_set.issubset(target_set):
            score += 0.25
        if score > best_score:
            best_score = score
            best_candidate = candidate
    if best_score < 0.5:
        return None
    return best_candidate

def normalize_xpath_answer(answer: str, *, anchor_texts: list[str], button_texts: list[str]) -> str:
    value = answer.strip()
    if not value:
        return value
    if '://' in value:
        value = re.sub('^https?://[^/]+', '', value, flags=re.IGNORECASE)
    exact_text_match = re.fullmatch('//(a|button)\\[text\\(\\)=[\'\\"](.+?)[\'\\"]\\]', value)
    if not exact_text_match:
        return value
    tag, target_text = exact_text_match.groups()
    candidate_pool = anchor_texts if tag.lower() == 'a' else button_texts
    if target_text in candidate_pool:
        return value
    replacement = choose_best_text_candidate(target_text, candidate_pool)
    if not replacement:
        return value
    return f"//{tag}[text()='{replacement}']"

def normalize_parameter_answers(parameter_values: list[dict[str, Any]], answer_project: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known_ids = collect_html_ids(answer_project)
    inferred_download_filename = infer_download_filename(answer_project)
    anchor_texts = collect_tag_texts(answer_project, 'a')
    button_texts = collect_tag_texts(answer_project, 'button')
    preferred_ids = {'introduction_element_id': ['page-introduction', 'introduction', 'page-title', 'calculate-btn', 'weight'], 'navigate_button_id': ['navigate-button', 'calculator-link', 'calculate-btn'], 'calculator_element_id': ['calculate-btn', 'weight', 'height'], 'height_input_box_id': ['height'], 'weight_input_box_id': ['weight'], 'submit_button_id': ['calculate-btn', 'submit-button'], 'bmi_result_id': ['bmi-result'], 'bmi_category_id': ['bmi-category'], 'interpretation_id': ['interpretation', 'bmi-category', 'bmi-result'], 'reset_button_id': ['reset-btn', 'reset-button', 'calculate-btn'], 'health_advice_id': ['health-advice', 'bmi-category', 'bmi-result']}

    def fallback_id(name: str) -> str:
        for candidate in preferred_ids.get(name, []):
            if candidate in known_ids:
                return candidate
        for candidate in preferred_parameter_candidates(name):
            if candidate in known_ids:
                return candidate
        return ''
    normalized_pages: list[dict[str, Any]] = []
    for page in parameter_values:
        normalized_functions: list[dict[str, Any]] = []
        for fn in page.get('function', []):
            normalized_parameters: list[dict[str, str]] = []
            for param in fn.get('parameter', []):
                name = str(param.get('name', ''))
                answer = str(param.get('answer', '')).strip()
                lowered = answer.lower()
                normalized_name = name.lower()
                if normalized_name.endswith('_url') or normalized_name == 'homepage_url':
                    if not answer or answer == '/':
                        answer = 'http://127.0.0.1:8000/'
                    elif answer.startswith('/'):
                        answer = f'http://127.0.0.1:8000{answer}'
                elif 'xpath' in normalized_name:
                    answer = normalize_xpath_answer(answer, anchor_texts=anchor_texts, button_texts=button_texts)
                elif name == 'default_download_path':
                    if not answer or answer.endswith('\\') or answer.endswith('/'):
                        answer = str(Path('C:\\Users\\Public\\Downloads') / inferred_download_filename)
                elif name.endswith('_id') and (not answer or lowered in {'null', 'none', 'n/a'}):
                    answer = fallback_id(name)
                normalized_parameters.append({'name': name, 'answer': answer})
            normalized_functions.append({'function': str(fn.get('function', '')), 'parameter': normalized_parameters})
        normalized_pages.append({'page': str(page.get('page', '')), 'function': normalized_functions})
    return normalized_pages

def infer_startfile(answer_project: list[dict[str, Any]]) -> str | None:
    preferred = ['manage.py', 'src/main.py', 'main.py', 'app.py']
    available_paths = [item['path'] for item in answer_project if isinstance(item, dict) and 'path' in item]
    for candidate in preferred:
        for path in available_paths:
            if path == candidate or path.endswith('/' + candidate):
                return path
    python_files = [path for path in available_paths if path.endswith('.py')]
    return python_files[0] if python_files else None

def infer_information(mission: ProjectEvalMission, answer_project: list[dict[str, Any]], startfile: str | None) -> dict[str, Any]:
    requirements: list[str] = []
    for item in answer_project:
        if item.get('path') == 'requirements.txt':
            requirements = [line.strip() for line in item['code'].splitlines() if line.strip()]
            break
    if not requirements:
        stack = mission.technical_stack.lower()
        if 'django' in stack:
            requirements = ['Django']
        elif 'flask' in stack:
            requirements = ['Flask']
    if startfile and startfile.endswith('manage.py'):
        initiate_commands = [[sys.executable, startfile, 'makemigrations'], [sys.executable, startfile, 'migrate'], [sys.executable, startfile, 'runserver']]
    elif startfile:
        initiate_commands = [[sys.executable, startfile]]
    else:
        initiate_commands = []
    info: dict[str, Any] = {'initiate_commands': initiate_commands, 'requirements': requirements}
    if mission.project_type == 'website':
        info['homepage_url'] = '/'
    return info

def write_workspace_cache(workspace: Path, name: str, payload: Any) -> str:
    artifacts_dir = workspace / 'artifacts'
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    target_path = artifacts_dir / name
    target_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return str(target_path)

def resolve_generated_root(workspace: Path, final_report: dict[str, Any] | None=None) -> Path:
    final_report = final_report or {}
    generated_root_value = final_report.get('generated_root')
    if generated_root_value:
        generated_root = Path(generated_root_value)
        if generated_root.exists():
            return generated_root
    return workspace / 'generated_project'

def backup_existing_workspace(workspace: Path) -> Path:
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    backup_path = workspace.with_name(f'{workspace.name}_regeneration_backup_{timestamp}')
    suffix = 1
    while backup_path.exists():
        backup_path = workspace.with_name(f'{workspace.name}_regeneration_backup_{timestamp}_{suffix}')
        suffix += 1
    shutil.move(str(workspace), str(backup_path))
    return backup_path

def load_workspace_exports(*, mission: ProjectEvalMission, workspace: Path, parameter_client: BaseLLMClient, parameter_repair_client: BaseLLMClient | None, regenerate_parameters: bool=False) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str | None]:
    final_report = read_json_if_exists(workspace / 'artifacts' / 'final_report.json') or {}
    generated_root = resolve_generated_root(workspace, final_report)
    if not generated_root.exists():
        raise FileNotFoundError(f'Generated project root not found for workspace {workspace}')
    answer_project = filter_projecteval_export_files(mission, project_to_json(generated_root))
    export_hash = project_export_hash(answer_project)
    parameter_metadata = read_json_if_exists(workspace / 'artifacts' / 'projecteval_parameter_metadata.json') or {}
    cached_parameter_values = None
    if not regenerate_parameters:
        if parameter_metadata.get('project_hash') == export_hash:
            cached_parameter_values = read_json_if_exists(workspace / 'artifacts' / 'projecteval_parameter_values.json')
    if cached_parameter_values is None:
        deterministic_values = build_deterministic_parameter_answers(mission, answer_project)
        if getattr(getattr(parameter_client, 'config', None), 'provider', None) == 'mock':
            cached_parameter_values = deterministic_values or build_mock_parameter_answers(mission)
        else:
            llm_values = solve_parameters(client=parameter_client, repair_client=parameter_repair_client, mission=mission, answer_project=answer_project, artifacts_dir=workspace / 'artifacts')
            cached_parameter_values = merge_parameter_answers(llm_values, deterministic_values)
        cached_parameter_values = normalize_parameter_answers(cached_parameter_values, answer_project)
        write_workspace_cache(workspace, 'projecteval_parameter_values.json', cached_parameter_values)
        validation = validate_parameter_answers(cached_parameter_values, answer_project)
        write_workspace_cache(workspace, 'projecteval_parameter_metadata.json', {'project_hash': export_hash, 'validation': validation, 'generated_at': datetime.now().isoformat()})
    else:
        validation = validate_parameter_answers(cached_parameter_values, answer_project)
        write_workspace_cache(workspace, 'projecteval_parameter_metadata.json', {'project_hash': export_hash, 'validation': validation, 'generated_at': parameter_metadata.get('generated_at') or datetime.now().isoformat(), 'cache_reused': True})
    cached_information = read_json_if_exists(workspace / 'artifacts' / 'projecteval_information.json')
    cached_startfile_text = read_text_if_exists(workspace / 'artifacts' / 'projecteval_startfile.txt')
    startfile = cached_startfile_text.strip() if cached_startfile_text else None
    if cached_information is None:
        startfile = infer_startfile(answer_project)
        cached_information = infer_information(mission, answer_project, startfile)
        write_workspace_cache(workspace, 'projecteval_information.json', cached_information)
        (workspace / 'artifacts' / 'projecteval_startfile.txt').write_text(startfile or '', encoding='utf-8')
    return (answer_project, cached_parameter_values, cached_information, startfile)

def try_load_reusable_workspace_result(*, mission: ProjectEvalMission, workspace: Path, parameter_client: BaseLLMClient, parameter_repair_client: BaseLLMClient | None, regenerate_parameters: bool=False, expected_core_mode: str='multi_agent') -> dict[str, Any] | None:
    final_report_path = workspace / 'artifacts' / 'final_report.json'
    final_report = read_json_if_exists(final_report_path) or {}
    if not isinstance(final_report, dict):
        return None
    report_core_mode = (final_report.get('benchmark_summary') or {}).get('core_mode') or 'multi_agent'
    if report_core_mode != expected_core_mode:
        return None
    generated_root = resolve_generated_root(workspace, final_report)
    if not generated_root.exists():
        return None
    answer_project, parameter_values, information, startfile = load_workspace_exports(mission=mission, workspace=workspace, parameter_client=parameter_client, parameter_repair_client=parameter_repair_client, regenerate_parameters=regenerate_parameters)
    per_project_result = {'final_status': final_report.get('final_status') or 'reused_generated_workspace', 'test_status': final_report.get('test_status'), 'workspace': str(workspace), 'generated_root': str(generated_root), 'final_report': str(final_report_path), 'traces': final_report.get('traces', []), 'core_mode': report_core_mode}
    per_project_result['execution_summary'] = summarize_project_execution(per_project_result)
    return {'answer_project': answer_project, 'parameter_values': parameter_values, 'information': information, 'startfile': startfile, 'per_project_result': per_project_result}

def export_projecteval_experiment(*, projecteval_root: Path, experiment_date: str, model_label: str, mode: str, level: int, answer_code: dict[str, list[dict[str, Any]]], answer_parameter: dict[str, list[dict[str, Any]]], answer_information: dict[str, dict[str, Any]], answer_startfile: dict[str, str], run_metadata: dict[str, Any]) -> dict[str, Any]:
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    mode_dir = projecteval_root / 'experiments' / experiment_date / model_label / mode
    run_slug = f"run_{timestamp}_projects_{'-'.join(run_metadata.get('project_ids', [])) or 'none'}"
    run_dir = mode_dir / 'runs' / run_slug
    exports_dir = run_dir / 'exports'
    summary_dir = run_dir / 'summary'
    judge_dir = run_dir / 'judge'
    exports_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)
    judge_dir.mkdir(parents=True, exist_ok=True)
    answer_code_path = exports_dir / 'answer_code.json'
    answer_parameter_path = exports_dir / 'answer_parameter.json'
    answer_information_path = exports_dir / 'answer_information.json'
    answer_startfile_path = exports_dir / 'answer_startfile.json'
    run_manifest_path = summary_dir / 'run_manifest.json'
    answer_code_path.write_text(json.dumps(answer_code, indent=2), encoding='utf-8')
    answer_parameter_path.write_text(json.dumps(answer_parameter, indent=2), encoding='utf-8')
    answer_information_path.write_text(json.dumps(answer_information, indent=2), encoding='utf-8')
    answer_startfile_path.write_text(json.dumps(answer_startfile, indent=2), encoding='utf-8')
    run_manifest = {'run_id': run_slug, 'timestamp': timestamp, 'experiment_date': experiment_date, 'model_label': model_label, 'mode': mode, 'level': level, 'project_ids': list(run_metadata.get('project_ids', [])), 'selected_project_ids': list(run_metadata.get('selected_project_ids', [])), 'answer_code_path': str(answer_code_path), 'answer_parameter_path': str(answer_parameter_path), 'answer_information_path': str(answer_information_path), 'answer_startfile_path': str(answer_startfile_path)}
    run_manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding='utf-8')
    (summary_dir / 'run_metadata.json').write_text(json.dumps(run_metadata, indent=2), encoding='utf-8')
    return {'mode_dir': mode_dir, 'run_dir': run_dir, 'run_id': run_slug, 'timestamp': timestamp, 'answer_code_path': answer_code_path, 'answer_parameter_path': answer_parameter_path, 'answer_information_path': answer_information_path, 'answer_startfile_path': answer_startfile_path, 'run_manifest_path': run_manifest_path, 'judge_dir': judge_dir, 'summary_dir': summary_dir}

def maybe_run_projecteval_script(*, projecteval_root: Path, script_name: str, experiment_date: str, group_paths: list[str] | None=None, result_csv_path: str | None=None, test_root: str | None=None) -> subprocess.CompletedProcess[str] | None:
    if script_name == 'run_judge.py':
        driver_candidates = list(projecteval_root.glob('*driver*'))
        drivers = [d for d in driver_candidates if d.is_file() and (not d.name.endswith('.py'))]
        if not drivers:
            logger.warning('Skipping ProjectEval run_judge.py because no browser driver executable was found.')
            return None
        ensure_projecteval_website_port_free(PROJECTEVAL_WEBSITE_PORT)
    command = [sys.executable, script_name, '-r', json.dumps([experiment_date])]
    if group_paths:
        command.extend(['--group-paths', json.dumps(group_paths)])
    if result_csv_path:
        command.extend(['--result-csv', result_csv_path])
    env = os.environ.copy()
    if test_root:
        env['PROJECT_EVAL_TEST_ROOT'] = test_root
    return subprocess.run(command, cwd=projecteval_root, capture_output=True, text=True, check=False, env=env)

def is_projecteval_managed_runserver(command: str) -> bool:
    normalized = command.lower()
    return 'manage.py' in normalized and 'runserver' in normalized

def listening_pids_on_port(port: int) -> list[int]:
    if os.name == 'nt':
        return []
    try:
        result = subprocess.run(['lsof', '-tiTCP:%d' % port, '-sTCP:LISTEN'], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []
    pids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pids.append(int(line))
        except ValueError:
            continue
    return sorted(set(pids))

def process_command(pid: int) -> str:
    try:
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return ''
    return result.stdout.strip()

def wait_until_port_free(port: int, *, timeout_seconds: float=5.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not listening_pids_on_port(port):
            return True
        time.sleep(0.2)
    return not listening_pids_on_port(port)

def ensure_projecteval_website_port_free(port: int) -> None:
    pids = listening_pids_on_port(port)
    if not pids:
        return
    unsafe: list[tuple[int, str]] = []
    terminated: list[int] = []
    for pid in pids:
        command = process_command(pid)
        if not is_projecteval_managed_runserver(command):
            unsafe.append((pid, command))
            continue
        logger.warning('Terminating stale Django runserver on port %s before ProjectEval judge: pid=%s', port, pid)
        try:
            os.kill(pid, signal.SIGTERM)
            terminated.append(pid)
        except ProcessLookupError:
            continue
    if unsafe:
        details = '; '.join((f'pid={pid} command={command!r}' for pid, command in unsafe))
        raise RuntimeError(f'ProjectEval judge needs localhost:{port}, but the port is occupied by a non-MASS process: {details}')
    if terminated and (not wait_until_port_free(port)):
        for pid in terminated:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if not wait_until_port_free(port):
            raise RuntimeError(f'ProjectEval judge needs localhost:{port}, but stale runserver processes did not exit.')

def latest_csv(root: Path, pattern: str) -> Path | None:
    candidates = sorted(root.glob(pattern), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None

def extract_official_scores(*, csv_path: Path, experiment_date: str, model_label: str, mode: str, level: int, run_id: str | None=None) -> dict[str, Any] | None:
    import csv
    with csv_path.open('r', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            if row.get('date') == experiment_date and row.get('model') == model_label and (row.get('mode') == mode) and (row.get('level') == str(level)) and (run_id is None or row.get('run_id', row.get('timestamp')) == run_id):
                return dict(row)
    return None

def _coerce_int(value: Any) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None

def _coerce_float(value: Any) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None

def compute_fixed_pass_at_1(*, judge_score_row: dict[str, Any] | None, judge_function_details: dict[str, dict[str, Any]], judge_project_scores: dict[str, float], selected_project_ids: list[str]) -> dict[str, Any]:
    """Compute thesis pass@1 as total passed judge checks over ProjectEval's fixed denominator."""
    passed_from_row = _coerce_int((judge_score_row or {}).get('passed'))
    if passed_from_row is not None:
        passed = passed_from_row
    else:
        passed = 0
        for project_id in selected_project_ids:
            details = judge_function_details.get(str(project_id), {})
            counts = details.get('counts') if isinstance(details, dict) else {}
            function_passed = _coerce_int((counts or {}).get('passed')) or 0
            project_score = _coerce_float(details.get('score') if isinstance(details, dict) else None)
            if project_score is None:
                project_score = _coerce_float(judge_project_scores.get(str(project_id)))
            runnable_passed = 1 if project_score and project_score > 0 else 0
            passed += function_passed + runnable_passed
    score = passed / PROJECTEVAL_FIXED_TEST_TOTAL
    return {'passed': passed, 'denominator': PROJECTEVAL_FIXED_TEST_TOTAL, 'score': score}

def compute_fixed_pass_at_1_from_projects(projects: dict[str, Any]) -> dict[str, Any]:
    passed = 0
    has_counts = False
    for project in projects.values():
        if not isinstance(project, dict):
            continue
        details = project.get('judge_details') if isinstance(project.get('judge_details'), dict) else {}
        counts = details.get('counts') if isinstance(details, dict) else project.get('counts')
        if not isinstance(counts, dict):
            continue
        has_counts = True
        function_passed = _coerce_int(counts.get('passed')) or 0
        project_score = _coerce_float(project.get('judge_score'))
        if project_score is None:
            project_score = _coerce_float(details.get('score'))
        runnable_passed = 1 if project_score and project_score > 0 else 0
        passed += function_passed + runnable_passed
    if not has_counts:
        return {'passed': None, 'denominator': PROJECTEVAL_FIXED_TEST_TOTAL, 'score': None}
    return {'passed': passed, 'denominator': PROJECTEVAL_FIXED_TEST_TOTAL, 'score': passed / PROJECTEVAL_FIXED_TEST_TOTAL}

def update_session_experiment_index(*, projecteval_root: Path, experiment_date: str, model_label: str, mode: str, export_bundle: dict[str, Any], summary: dict[str, Any]) -> dict[str, Path]:
    session_root = projecteval_root / 'experiments' / experiment_date / model_label / mode
    session_root.mkdir(parents=True, exist_ok=True)
    index_path = session_root / 'session_index.json'
    aggregate_path = session_root / 'session_aggregate.json'
    index_payload = read_json_if_exists(index_path) or {'experiment_date': experiment_date, 'model_label': model_label, 'mode': mode, 'runs': [], 'latest_run_id': None}
    run_id = str(export_bundle['run_id'])
    run_dir = Path(export_bundle['run_dir'])
    per_project_results = summary.get('per_project_results') or {}
    official_scores = summary.get('official_scores') or {}
    judge_project_scores = official_scores.get('judge_project_scores') or {}
    fixed_pass_at_1 = official_scores.get('fixed_pass_at_1') or {}
    run_entry = {'run_id': run_id, 'run_dir': str(run_dir), 'summary_path': str(Path(export_bundle['summary_dir']) / 'run_summary.json'), 'per_project_results_path': str(Path(export_bundle['judge_dir']) / 'per_project_results.json'), 'judge_stdout_path': str(Path(export_bundle['judge_dir']) / 'judge_stdout.txt'), 'judge_stderr_path': str(Path(export_bundle['judge_dir']) / 'judge_stderr.txt'), 'selected_project_ids': list(summary.get('selected_project_ids') or []), 'project_ids': list((summary.get('per_project_results') or {}).keys()), 'official_score': fixed_pass_at_1.get('score') or (official_scores.get('judge_score_row') or {}).get('score'), 'fixed_pass_at_1': fixed_pass_at_1, 'judge_project_scores': judge_project_scores, 'updated_at': datetime.now().isoformat()}
    runs = [item for item in index_payload.get('runs', []) if item.get('run_id') != run_id]
    runs.append(run_entry)
    runs.sort(key=lambda item: str(item.get('updated_at', '')))
    index_payload['runs'] = runs
    index_payload['latest_run_id'] = run_id
    index_path.write_text(json.dumps(index_payload, indent=2), encoding='utf-8')
    aggregate_payload = read_json_if_exists(aggregate_path) or {'experiment_date': experiment_date, 'model_label': model_label, 'mode': mode, 'latest_run_id': run_id, 'projects': {}}
    aggregate_payload['latest_run_id'] = run_id
    aggregate_projects = aggregate_payload.setdefault('projects', {})
    for project_id, project_result in per_project_results.items():
        merged_result = dict(project_result)
        merged_result['judge_score'] = judge_project_scores.get(project_id, merged_result.get('judge_score'))
        merged_result['source_run_id'] = run_id
        merged_result['updated_at'] = datetime.now().isoformat()
        aggregate_projects[str(project_id)] = merged_result
    aggregate_fixed_pass_at_1 = compute_fixed_pass_at_1_from_projects(aggregate_projects)
    if aggregate_fixed_pass_at_1.get('score') is not None:
        aggregate_payload['fixed_pass_at_1'] = aggregate_fixed_pass_at_1
    elif fixed_pass_at_1:
        aggregate_payload['fixed_pass_at_1'] = fixed_pass_at_1
    aggregate_path.write_text(json.dumps(aggregate_payload, indent=2), encoding='utf-8')
    return {'index_path': index_path, 'aggregate_path': aggregate_path}

def extract_project_scores_from_judge_output(*outputs: str | None) -> dict[str, float]:
    scores: dict[str, float] = {}
    for output in outputs:
        if not output:
            continue
        for project_id, raw_score in re.findall('Project id\\s+(\\d+)\\s+scored\\s+([0-9]+(?:\\.[0-9]+)?\\.?)', output, flags=re.IGNORECASE):
            try:
                scores[project_id] = float(raw_score.rstrip('.'))
            except ValueError:
                continue
    return scores

def parse_judge_function_details(*outputs: str | None) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    current_project_id: str | None = None
    current_function_id: str | None = None
    project_re = re.compile('Evaluating project id\\s+(\\d+)', flags=re.IGNORECASE)
    function_re = re.compile('Evaluating function\\s+(\\d+_\\d+)\\s*(.*)', flags=re.IGNORECASE)
    passed_re = re.compile('Function\\s+(\\d+_\\d+)\\s+passed\\.', flags=re.IGNORECASE)
    failed_re = re.compile('Function\\s+(\\d+_\\d+)\\s+failed\\.', flags=re.IGNORECASE)
    warning_re = re.compile('(\\d+_\\d+):\\s+(.*)', flags=re.IGNORECASE)
    for output in outputs:
        if not output:
            continue
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            project_match = project_re.search(line)
            if project_match:
                current_project_id = project_match.group(1)
                details.setdefault(current_project_id, {'project_id': current_project_id, 'functions': {}, 'score': None})
                continue
            function_match = function_re.search(line)
            if function_match:
                function_id = function_match.group(1)
                title = function_match.group(2).strip()
                project_id = function_id.split('_', 1)[0]
                current_project_id = project_id
                current_function_id = function_id
                project_entry = details.setdefault(project_id, {'project_id': project_id, 'functions': {}, 'score': None})
                function_entry = project_entry['functions'].setdefault(function_id, {'function_id': function_id, 'title': title, 'status': 'running', 'messages': []})
                if title and (not function_entry.get('title')):
                    function_entry['title'] = title
                continue
            passed_match = passed_re.search(line)
            if passed_match:
                function_id = passed_match.group(1)
                project_id = function_id.split('_', 1)[0]
                project_entry = details.setdefault(project_id, {'project_id': project_id, 'functions': {}, 'score': None})
                function_entry = project_entry['functions'].setdefault(function_id, {'function_id': function_id, 'title': '', 'messages': []})
                function_entry['status'] = 'passed'
                continue
            failed_match = failed_re.search(line)
            if failed_match:
                function_id = failed_match.group(1)
                project_id = function_id.split('_', 1)[0]
                project_entry = details.setdefault(project_id, {'project_id': project_id, 'functions': {}, 'score': None})
                function_entry = project_entry['functions'].setdefault(function_id, {'function_id': function_id, 'title': '', 'messages': []})
                function_entry['status'] = 'failed'
                continue
            warning_match = warning_re.search(line)
            if warning_match:
                function_id = warning_match.group(1)
                message = warning_match.group(2).strip()
                project_id = function_id.split('_', 1)[0]
                project_entry = details.setdefault(project_id, {'project_id': project_id, 'functions': {}, 'score': None})
                function_entry = project_entry['functions'].setdefault(function_id, {'function_id': function_id, 'title': '', 'messages': []})
                function_entry.setdefault('messages', []).append(message)
                if 'failed' not in function_entry.get('status', ''):
                    function_entry['status'] = 'warning'
                continue
            project_score_match = re.search('Project id\\s+(\\d+)\\s+scored\\s+([0-9]+(?:\\.[0-9]+)?\\.?)', line, flags=re.IGNORECASE)
            if project_score_match:
                project_id, raw_score = project_score_match.groups()
                project_entry = details.setdefault(project_id, {'project_id': project_id, 'functions': {}, 'score': None})
                try:
                    project_entry['score'] = float(raw_score.rstrip('.'))
                except ValueError:
                    project_entry['score'] = raw_score
                continue
            if current_project_id and current_function_id and ('runtime exception' in line.lower() or 'wrong answer' in line.lower()):
                project_entry = details.setdefault(current_project_id, {'project_id': current_project_id, 'functions': {}, 'score': None})
                function_entry = project_entry['functions'].setdefault(current_function_id, {'function_id': current_function_id, 'title': '', 'messages': []})
                function_entry.setdefault('messages', []).append(line)
    for project_entry in details.values():
        functions = project_entry.get('functions', {})
        passed = 0
        failed = 0
        warning = 0
        for function_entry in functions.values():
            status = function_entry.get('status')
            if status == 'passed':
                passed += 1
            elif status == 'failed':
                failed += 1
            else:
                warning += 1
        project_entry['counts'] = {'passed': passed, 'failed': failed, 'warning_or_unknown': warning, 'total': len(functions)}
        project_entry['passed_functions'] = sorted((function_id for function_id, function_entry in functions.items() if function_entry.get('status') == 'passed'))
        project_entry['failed_functions'] = sorted((function_id for function_id, function_entry in functions.items() if function_entry.get('status') != 'passed'))
    return details

def summarize_project_execution(result: dict[str, Any]) -> dict[str, Any]:
    traces = list(result.get('traces') or [])
    total_duration_ms = 0.0
    total_usage: dict[str, float] = {}
    by_agent: dict[str, dict[str, Any]] = {}

    def coerce_number(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None
    for trace in traces:
        duration_ms = coerce_number(trace.get('duration_ms')) or 0.0
        total_duration_ms += duration_ms
        usage = trace.get('usage') or {}
        agent_name = str(trace.get('agent', 'unknown'))
        agent_entry = by_agent.setdefault(agent_name, {'count': 0, 'duration_ms': 0.0, 'usage': {}, 'roles': [], 'transcript_paths': []})
        agent_entry['count'] += 1
        agent_entry['duration_ms'] += duration_ms
        role = trace.get('role')
        if role and role not in agent_entry['roles']:
            agent_entry['roles'].append(role)
        transcript_path = trace.get('transcript_path')
        if transcript_path:
            agent_entry['transcript_paths'].append(transcript_path)
        for key, value in usage.items():
            numeric_value = coerce_number(value)
            if numeric_value is None:
                continue
            total_usage[key] = total_usage.get(key, 0.0) + numeric_value
            agent_usage = agent_entry['usage']
            agent_usage[key] = agent_usage.get(key, 0.0) + numeric_value
    return {'trace_count': len(traces), 'total_duration_ms': round(total_duration_ms, 2), 'total_usage': total_usage, 'by_agent': by_agent}

def sanitize_system_token(value: str) -> str:
    cleaned = re.sub('[^A-Za-z0-9.]+', '', value)
    return cleaned or 'MAS'

def derive_scoreboard_system_name(*, explicit_name: str | None, level: int, model_label: str, model_configs: dict[str, Any]) -> str:
    if explicit_name:
        base_name = explicit_name
    else:
        role_models = {str(getattr(config, 'model', '')) for config in model_configs.values()}
        if len(role_models) == 1:
            only_model = next(iter(role_models))
            model_tail = only_model.split('/')[-1]
            base_name = f'{sanitize_system_token(model_tail)}MAS'
        else:
            base_name = sanitize_system_token(model_label)
    if re.search('_l[123]$', base_name):
        return base_name
    return f'{base_name}_l{level}'

def update_projecteval_scoreboard(*, scoreboard_path: Path, system_name: str, level: int, selected_ids: list[str], summary: dict[str, Any], run_metadata: dict[str, Any], all_project_ids: list[str]) -> Path:
    scoreboard_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ['system_name', 'level', 'updated_at', 'pass_at_1', 'average_score', *[f'project_{project_id}' for project_id in all_project_ids]]
    rows: list[dict[str, str]] = []
    if scoreboard_path.exists():
        with scoreboard_path.open('r', encoding='utf-8', newline='') as handle:
            rows = list(csv.DictReader(handle))
    row_by_name = {row.get('system_name', ''): row for row in rows}
    target_row = row_by_name.get(system_name, {field: '' for field in fieldnames})
    target_row['system_name'] = system_name
    target_row['level'] = str(level)
    target_row['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    official_scores = summary.get('official_scores', {})
    fixed_pass_at_1 = official_scores.get('fixed_pass_at_1') or {}
    if fixed_pass_at_1.get('score') is not None:
        target_row['pass_at_1'] = f"{float(fixed_pass_at_1['score']):.6f}".rstrip('0').rstrip('.')
    project_scores = dict(official_scores.get('judge_project_scores') or {})
    if not project_scores:
        project_scores = extract_project_scores_from_judge_output(official_scores.get('judge_stdout'), official_scores.get('judge_stderr'))
    for project_id in selected_ids:
        score_value = project_scores.get(project_id)
        if score_value is None:
            result = (run_metadata.get('per_project_results') or {}).get(project_id, {})
            if result.get('final_status') == 'completed' and (not official_scores):
                score_value = 1.0
        if score_value is not None:
            target_row[f'project_{project_id}'] = f'{float(score_value):.6f}'.rstrip('0').rstrip('.')
    available_scores: list[float] = []
    for project_id in all_project_ids:
        raw_value = target_row.get(f'project_{project_id}', '').strip()
        if not raw_value:
            continue
        try:
            available_scores.append(float(raw_value))
        except ValueError:
            continue
    if available_scores:
        average_score = sum(available_scores) / len(all_project_ids)
        target_row['average_score'] = f'{average_score:.6f}'.rstrip('0').rstrip('.')
    row_by_name[system_name] = target_row
    ordered_rows = sorted(row_by_name.values(), key=lambda row: row.get('system_name', ''))
    with scoreboard_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ordered_rows)
    return scoreboard_path

def read_text_if_exists(path: str | Path) -> str | None:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate.read_text(encoding='utf-8')

def read_json_if_exists(path: str | Path) -> Any | None:
    raw = read_text_if_exists(path)
    if raw is None:
        return None
    return json.loads(raw)

def write_text_creating_parent(path: str | Path, text: str) -> None:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(text, encoding='utf-8')

def write_json_creating_parent(path: str | Path, payload: Any) -> None:
    write_text_creating_parent(path, json.dumps(payload, indent=2))

def ensure_export_bundle_dirs(export_bundle: dict[str, Any]) -> None:
    for key in ('run_dir', 'judge_dir', 'summary_dir'):
        Path(export_bundle[key]).mkdir(parents=True, exist_ok=True)

def safe_copy_file(source: str | Path, destination_dir: Path, destination_name: str | None=None) -> str | None:
    source_path = Path(source)
    if not source_path.exists() or not source_path.is_file():
        return None
    destination_dir.mkdir(parents=True, exist_ok=True)
    target_path = destination_dir / (destination_name or source_path.name)
    shutil.copy2(source_path, target_path)
    return str(target_path)

def safe_copy_tree(source: str | Path, destination_dir: Path) -> str | None:
    source_path = Path(source)
    if not source_path.exists() or not source_path.is_dir():
        return None
    target_path = destination_dir / source_path.name
    if target_path.exists():
        shutil.rmtree(target_path)
    shutil.copytree(source_path, target_path)
    return str(target_path)

def git_snapshot(root: Path) -> dict[str, Any]:

    def run_git(*args: str) -> str | None:
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    return {'branch': run_git('branch', '--show-current'), 'head_commit': run_git('rev-parse', 'HEAD'), 'status': run_git('status', '--short')}

def archive_successful_run(*, archive_root: Path, threshold: float, experiment_date: str, model_label: str, level: int, mode: str, models_config_path: str, system_config_path: str, export_dir: Path, summary: dict[str, Any], run_metadata: dict[str, Any]) -> Path | None:
    official_row = summary.get('official_scores', {}).get('judge_score_row') or {}
    official_project_scores = summary.get('official_scores', {}).get('judge_project_scores') or {}
    fixed_pass_at_1 = summary.get('official_scores', {}).get('fixed_pass_at_1') or {}
    fixed_score_value = _coerce_float(fixed_pass_at_1.get('score'))
    official_score = official_row.get('score')
    try:
        official_score_value = float(official_score) if official_score is not None else None
    except (TypeError, ValueError):
        official_score_value = None
    local_score_value = float(summary.get('local_pass_at_1', 0.0))
    selected_ids = [str(item) for item in run_metadata.get('project_ids', [])]
    selected_project_scores: list[float] = []
    for project_id in selected_ids:
        raw_project_score = official_project_scores.get(project_id)
        try:
            if raw_project_score is not None:
                selected_project_scores.append(float(raw_project_score))
        except (TypeError, ValueError):
            continue
    selected_project_average = sum(selected_project_scores) / len(selected_project_scores) if selected_project_scores else None
    single_project_score: float | None = None
    if len(selected_ids) == 1:
        raw_project_score = official_project_scores.get(selected_ids[0])
        try:
            single_project_score = float(raw_project_score) if raw_project_score is not None else None
        except (TypeError, ValueError):
            single_project_score = None
    effective_score = fixed_score_value if fixed_score_value is not None else single_project_score if single_project_score is not None else selected_project_average if selected_project_average is not None else official_score_value if official_score_value is not None else local_score_value
    if effective_score < threshold:
        return None
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    archive_id = f'{timestamp}_{uuid.uuid4().hex[:8]}'
    archive_dir = archive_root / experiment_date / f'{model_label}_level_{level}_{mode}_{archive_id}'
    archive_dir.mkdir(parents=True, exist_ok=True)
    configs_dir = archive_dir / 'configs'
    prompts_dir = archive_dir / 'prompts'
    exports_dir = archive_dir / 'projecteval_export'
    workspaces_dir = archive_dir / 'workspaces'
    reports_dir = archive_dir / 'reports'
    judge_dir = archive_dir / 'judge'
    safe_copy_file(models_config_path, configs_dir, 'models_config.yaml')
    safe_copy_file(system_config_path, configs_dir, 'system_config.yaml')
    prompt_root = Path('app/prompts')
    if prompt_root.exists():
        for prompt_file in sorted(prompt_root.glob('*.txt')):
            safe_copy_file(prompt_file, prompts_dir)
    if export_dir.exists():
        safe_copy_tree(export_dir, exports_dir)
    official_scores = summary.get('official_scores', {})
    if official_scores.get('judge_stdout'):
        (judge_dir / 'judge_stdout.txt').parent.mkdir(parents=True, exist_ok=True)
        (judge_dir / 'judge_stdout.txt').write_text(str(official_scores.get('judge_stdout') or ''), encoding='utf-8')
    if official_scores.get('judge_stderr'):
        (judge_dir / 'judge_stderr.txt').parent.mkdir(parents=True, exist_ok=True)
        (judge_dir / 'judge_stderr.txt').write_text(str(official_scores.get('judge_stderr') or ''), encoding='utf-8')
    archived_projects: dict[str, Any] = {}
    for project_id, result in run_metadata.get('per_project_results', {}).items():
        project_dir = workspaces_dir / str(project_id)
        copied_root = safe_copy_tree(result.get('generated_root', ''), project_dir)
        copied_report = safe_copy_file(result.get('final_report', ''), reports_dir, f'{project_id}_final_report.json')
        copied_workspace = safe_copy_tree(result.get('workspace', ''), project_dir)
        archived_projects[str(project_id)] = {'generated_root': copied_root, 'workspace': copied_workspace, 'final_report': copied_report, 'final_status': result.get('final_status'), 'test_status': result.get('test_status'), 'execution_summary': result.get('execution_summary'), 'judge_details': result.get('judge_details')}
    manifest = {'archive_id': archive_id, 'created_at': timestamp, 'threshold': threshold, 'effective_score': effective_score, 'single_project_score': single_project_score, 'selected_project_average': selected_project_average, 'official_score': official_score_value, 'local_pass_at_1': local_score_value, 'experiment_date': experiment_date, 'model_label': model_label, 'level': level, 'mode': mode, 'models_config_path': str(Path(models_config_path).resolve()), 'system_config_path': str(Path(system_config_path).resolve()), 'models_config_content': read_text_if_exists(models_config_path), 'system_config_content': read_text_if_exists(system_config_path), 'prompt_files': sorted((path.name for path in prompt_root.glob('*.txt'))) if prompt_root.exists() else [], 'git': git_snapshot(Path.cwd()), 'summary': summary, 'run_metadata': run_metadata, 'archived_projects': archived_projects}
    (archive_dir / 'archive_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return archive_dir

def main() -> None:
    configure_logging()
    args = parse_args()
    config = load_runner_config(args.config)
    projecteval_root_value = config.get('projecteval_root', args.projecteval_root)
    models_config_value = config.get('models_config', args.models_config)
    system_config_value = config.get('system_config', args.system_config)
    level_value = int(config.get('level', args.level))
    mode_value = config.get('mode', args.mode)
    project_ids_value = ','.join(config['project_ids']) if isinstance(config.get('project_ids'), list) else config.get('project_ids', args.project_ids)
    workspace_root_value = config.get('workspace_root', args.workspace_root)
    model_label_value = config.get('model_label', args.model_label)
    parameter_role_value = config.get('parameter_role', args.parameter_role)
    parameter_repair_role_value = config.get('parameter_repair_role', args.parameter_repair_role)
    run_judge_value = bool(config.get('run_judge', args.run_judge))
    run_indicators_value = bool(config.get('run_indicators', args.run_indicators))
    run_static_analysis_value = bool(config.get('run_static_analysis', True))
    run_dynamic_analysis_value = bool(config.get('run_dynamic_analysis', True))
    use_agentic_tools_value = bool(config.get('use_agentic_tools', False))
    compaction_value = config.get('agentic_context_compaction', None)
    if compaction_value is not None:
        from app.agents.base_agent import BaseAgent
        BaseAgent.AGENTIC_CONTEXT_COMPACTION = bool(compaction_value)
        logging.getLogger(__name__).info('Agentic context compaction set to %s (from runner config).', bool(compaction_value))
    experiment_date_value = config.get('experiment_date', args.experiment_date)
    archive_root_value = config.get('archive_root', args.archive_root)
    archive_threshold_value = float(config.get('archive_threshold', args.archive_threshold))
    scoreboard_path_value = config.get('scoreboard_path', args.scoreboard_path)
    scoreboard_system_name_value = config.get('scoreboard_system_name', args.scoreboard_system_name)
    reuse_completed_workspaces_value = bool(config.get('reuse_completed_workspaces', args.reuse_completed_workspaces))
    resume_interrupted_workspaces_value = bool(config.get('resume_interrupted_workspaces', args.resume_interrupted_workspaces))
    post_core_only_value = bool(config.get('post_core_only', args.post_core_only))
    regenerate_parameters_value = bool(config.get('regenerate_parameters', args.regenerate_parameters))
    core_mode_value = str(config.get('core_mode', args.core_mode))
    single_agent_iterations_value = int(config.get('single_agent_iterations', args.single_agent_iterations))
    opencode_model_value = str(config.get('opencode_model', args.opencode_model))
    opencode_cli_path_value = str(config.get('opencode_cli_path', args.opencode_cli_path))
    opencode_timeout_seconds_value = int(config.get('opencode_timeout_seconds', args.opencode_timeout_seconds))
    if core_mode_value not in {'multi_agent', 'single_agent', 'opencode'}:
        raise ValueError(f'Unsupported core_mode: {core_mode_value}')
    projecteval_root = Path(projecteval_root_value).resolve()
    dataset = load_projecteval_dataset(projecteval_root / 'data' / 'project_eval_project.json')
    selected_ids = parse_project_ids(project_ids_value, sorted(dataset.keys(), key=int))
    experiment_date = experiment_date_value or datetime.now().strftime('%Y%m%d-pass1')
    workspaces_root = Path(workspace_root_value).resolve() / experiment_date / f'level_{level_value}'
    workspaces_root.mkdir(parents=True, exist_ok=True)
    model_configs = load_model_configs(models_config_value)
    llm_registry = create_llm_registry(model_configs)
    parameter_client = llm_registry[parameter_role_value]
    parameter_repair_client = llm_registry.get(parameter_repair_role_value)
    answer_code: dict[str, list[dict[str, Any]]] = {}
    answer_parameter: dict[str, list[dict[str, Any]]] = {}
    answer_information: dict[str, dict[str, Any]] = {}
    answer_startfile: dict[str, str] = {}
    per_project_results: dict[str, Any] = {}
    for project_id in selected_ids:
        mission = dataset[project_id]
        workspace = workspaces_root / project_id
        checkpoint_payload = load_checkpoint(workspace) if workspace.exists() else None
        can_resume_checkpoint = core_mode_value == 'multi_agent' and resume_interrupted_workspaces_value and isinstance(checkpoint_payload, dict) and (checkpoint_payload.get('status') != 'completed')
        if (reuse_completed_workspaces_value or post_core_only_value) and workspace.exists() and (not can_resume_checkpoint):
            try:
                reused = try_load_reusable_workspace_result(mission=mission, workspace=workspace, parameter_client=parameter_client, parameter_repair_client=parameter_repair_client, regenerate_parameters=regenerate_parameters_value, expected_core_mode=core_mode_value)
                if reused:
                    logger.info('Project %s already has a reusable workspace (final_status=%s). Reusing workspace.', project_id, reused['per_project_result'].get('final_status'))
                    answer_code[project_id] = reused['answer_project']
                    answer_parameter[project_id] = reused['parameter_values']
                    answer_information[project_id] = reused['information']
                    if reused['startfile'] is not None:
                        answer_startfile[project_id] = reused['startfile']
                    per_project_results[project_id] = reused['per_project_result']
                    continue
                logger.info('Project %s has an existing workspace, but no generated project could be reused. Will regenerate.', project_id)
            except Exception as exc:
                logger.warning('Could not reuse workspace for project %s: %s. Will regenerate.', project_id, exc)
        if post_core_only_value:
            logger.error('Post-core-only requested for project %s, but no reusable generated workspace was found. Skipping regeneration.', project_id)
            per_project_results[project_id] = {'workspace': str(workspace), 'generated_root': None, 'final_report': None, 'final_status': 'post_core_reuse_failed', 'test_status': 'post_core_reuse_failed', 'workflow_error': 'Post-core-only mode requires an existing generated_project and final_report.json.', 'traces': [], 'execution_summary': summarize_project_execution({'traces': []})}
            continue
        if workspace.exists() and (not can_resume_checkpoint):
            if reuse_completed_workspaces_value:
                backup_path = backup_existing_workspace(workspace)
                logger.warning('Preserved existing workspace for project %s at %s before regeneration.', project_id, backup_path)
            else:
                shutil.rmtree(workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        logger.info('Running %s workflow for ProjectEval project %s level %s', core_mode_value, project_id, level_value)
        if can_resume_checkpoint:
            logger.info('Resuming ProjectEval project %s from checkpoint: %s', project_id, checkpoint_summary(checkpoint_payload))
        try:
            event_callback = lambda event, pid=project_id, lvl=level_value, mode=mode_value: emit_benchmark_agent_event(event, project_id=pid, level=lvl, mode=mode)
            if core_mode_value == 'single_agent':
                final_state = run_single_agent_projecteval_workflow(mission=mission, level=level_value, mode=mode_value, workspace=workspace, models_config_path=models_config_value, system_config_path=system_config_value, max_iterations=single_agent_iterations_value, run_static_analysis=run_static_analysis_value, event_callback=event_callback)
            elif core_mode_value == 'opencode':
                final_state = run_opencode_projecteval_workflow(mission=mission, level=level_value, mode=mode_value, workspace=workspace, opencode_model=opencode_model_value, opencode_cli_path=opencode_cli_path_value, opencode_timeout_seconds=opencode_timeout_seconds_value, run_static_analysis=run_static_analysis_value, event_callback=event_callback)
            else:
                final_state = run_workflow(user_task=build_level_task(mission, level_value), workspace=workspace, models_config_path=models_config_value, system_config_path=system_config_value, resume_from_checkpoint=can_resume_checkpoint, initial_overrides={'benchmark_name': 'projecteval', 'benchmark_context': {'project_id': mission.project_id, 'project_type': mission.project_type, 'technical_stack': mission.technical_stack, 'level': level_value, 'mode': mode_value}, 'benchmark_testcode': mission.testcode, 'benchmark_checklist': mission.nl_checklist, 'skip_internal_tests': True, 'run_static_analysis': run_static_analysis_value, 'run_dynamic_analysis': run_dynamic_analysis_value, 'use_agentic_tools': use_agentic_tools_value, 'event_callback': event_callback})
        except Exception as exc:
            logger.exception('Workflow failed for project %s', project_id)
            failed_checkpoint = load_checkpoint(workspace)
            failed_checkpoint_summary = checkpoint_summary(failed_checkpoint) if isinstance(failed_checkpoint, dict) else None
            failed_checkpoint_state = failed_checkpoint.get('state') if isinstance(failed_checkpoint, dict) and isinstance(failed_checkpoint.get('state'), dict) else {}
            failed_traces = list(failed_checkpoint_state.get('traces', [])) if isinstance(failed_checkpoint_state, dict) else []
            per_project_results[project_id] = {'workspace': str(workspace), 'generated_root': None, 'final_report': None, 'final_status': 'interrupted_resumable' if failed_checkpoint_summary else 'workflow_failed', 'test_status': 'workflow_failed', 'workflow_error': str(exc), 'workflow_checkpoint': failed_checkpoint_summary, 'traces': failed_traces, 'execution_summary': summarize_project_execution({'traces': failed_traces})}
            continue
        generated_root = final_state.get('artifacts', {}).get('generated_root')
        if not generated_root:
            logger.error('Workflow for project %s did not produce a generated project.', project_id)
            per_project_results[project_id] = {'workspace': str(workspace), 'generated_root': None, 'final_report': final_state.get('final_output_path'), 'final_status': 'missing_generated_root', 'test_status': final_state.get('test_status'), 'workflow_error': 'Generated project root missing after workflow completion.', 'traces': list(final_state.get('traces', [])), 'execution_summary': summarize_project_execution({'traces': final_state.get('traces', [])})}
            continue
        answer_project = filter_projecteval_export_files(mission, project_to_json(Path(generated_root)))
        answer_code[project_id] = answer_project
        per_project_result = {'final_status': final_state.get('final_status'), 'test_status': final_state.get('test_status'), 'workspace': str(workspace), 'generated_root': generated_root, 'final_report': final_state.get('final_output_path'), 'traces': final_state.get('traces', []), 'core_mode': core_mode_value}
        per_project_result['execution_summary'] = summarize_project_execution(per_project_result)
        try:
            deterministic_values = build_deterministic_parameter_answers(mission, answer_project)
            if getattr(getattr(parameter_client, 'config', None), 'provider', None) == 'mock':
                parameter_values = deterministic_values or build_mock_parameter_answers(mission)
            else:
                llm_values = solve_parameters(client=parameter_client, repair_client=parameter_repair_client, mission=mission, answer_project=answer_project, artifacts_dir=workspace / 'artifacts')
                parameter_values = merge_parameter_answers(llm_values, deterministic_values)
            parameter_values = normalize_parameter_answers(parameter_values, answer_project)
            startfile = infer_startfile(answer_project)
            answer_parameter[project_id] = parameter_values
            if startfile is not None:
                answer_startfile[project_id] = startfile
            answer_information[project_id] = infer_information(mission, answer_project, startfile)
            write_workspace_cache(workspace, 'projecteval_parameter_values.json', parameter_values)
            write_workspace_cache(workspace, 'projecteval_parameter_metadata.json', {'project_hash': project_export_hash(answer_project), 'validation': validate_parameter_answers(parameter_values, answer_project), 'generated_at': datetime.now().isoformat()})
            write_workspace_cache(workspace, 'projecteval_information.json', answer_information[project_id])
            (workspace / 'artifacts' / 'projecteval_startfile.txt').write_text(startfile or '', encoding='utf-8')
        except Exception as exc:
            per_project_result['parameter_error'] = str(exc)
            per_project_result['final_status'] = 'parameter_failed'
            logger.exception('Parameter solving failed for project %s', project_id)
        per_project_results[project_id] = per_project_result
    included_ids = [project_id for project_id in selected_ids if project_id in per_project_results]
    local_pass_count = sum((1 for result in per_project_results.values() if result['final_status'] == 'completed'))
    local_pass_at_1 = local_pass_count / len(included_ids) if included_ids else 0.0
    run_metadata = {'project_ids': selected_ids, 'selected_project_ids': selected_ids, 'included_project_ids': included_ids, 'level': level_value, 'mode': mode_value, 'models_config': models_config_value, 'system_config': system_config_value, 'parameter_role': parameter_role_value, 'parameter_repair_role': parameter_repair_role_value, 'core_mode': core_mode_value, 'single_agent_iterations': single_agent_iterations_value if core_mode_value == 'single_agent' else None, 'reuse_completed_workspaces': reuse_completed_workspaces_value, 'post_core_only': post_core_only_value, 'regenerate_parameters': regenerate_parameters_value, 'local_pass_at_1': local_pass_at_1, 'local_pass_count': local_pass_count, 'total_projects': len(included_ids), 'per_project_results': per_project_results}
    export_bundle = export_projecteval_experiment(projecteval_root=projecteval_root, experiment_date=experiment_date, model_label=model_label_value, mode=mode_value, level=level_value, answer_code=answer_code, answer_parameter=answer_parameter, answer_information=answer_information, answer_startfile=answer_startfile, run_metadata=run_metadata)
    ensure_export_bundle_dirs(export_bundle)
    official_scores: dict[str, Any] = {}
    if run_judge_value:
        result_csv_path = str(Path(export_bundle['judge_dir']) / 'judge_results.csv')
        judge_result = maybe_run_projecteval_script(projecteval_root=projecteval_root, script_name='run_judge.py', experiment_date=experiment_date, group_paths=[str(export_bundle['answer_code_path'])], result_csv_path=result_csv_path, test_root=str(Path(export_bundle['run_dir']) / 'test_workspace'))
        official_scores['judge_stdout'] = judge_result.stdout if judge_result else None
        official_scores['judge_stderr'] = judge_result.stderr if judge_result else None
        official_scores['judge_returncode'] = judge_result.returncode if judge_result else None
        official_scores['judge_project_scores'] = extract_project_scores_from_judge_output(judge_result.stdout if judge_result else None, judge_result.stderr if judge_result else None)
        official_scores['judge_function_details'] = parse_judge_function_details(judge_result.stdout if judge_result else None, judge_result.stderr if judge_result else None)
        csv_path = Path(result_csv_path)
        if csv_path.exists():
            official_scores['judge_csv'] = str(csv_path)
            official_scores['judge_score_row'] = extract_official_scores(csv_path=csv_path, experiment_date=experiment_date, model_label=model_label_value, mode=mode_value, level=level_value, run_id=str(export_bundle['run_id']))
        if judge_result is not None or csv_path.exists():
            official_scores['fixed_pass_at_1'] = compute_fixed_pass_at_1(judge_score_row=official_scores.get('judge_score_row'), judge_function_details=official_scores.get('judge_function_details', {}) or {}, judge_project_scores=official_scores.get('judge_project_scores', {}) or {}, selected_project_ids=selected_ids)
        for project_id, project_result in per_project_results.items():
            project_result['judge_score'] = official_scores['judge_project_scores'].get(project_id)
            project_result['judge_details'] = (official_scores.get('judge_function_details', {}) or {}).get(project_id)
    if run_indicators_value:
        indicators_result = maybe_run_projecteval_script(projecteval_root=projecteval_root, script_name='run_indicators.py', experiment_date=experiment_date)
        official_scores['indicators_stdout'] = indicators_result.stdout if indicators_result else None
        official_scores['indicators_stderr'] = indicators_result.stderr if indicators_result else None
        official_scores['indicators_returncode'] = indicators_result.returncode if indicators_result else None
    summary = {'experiment_date': experiment_date, 'export_dir': str(export_bundle['run_dir']), 'selected_project_ids': selected_ids, 'run_id': str(export_bundle['run_id']), 'local_pass_at_1': local_pass_at_1, 'official_scores': official_scores, 'per_project_results': per_project_results}
    if official_scores.get('judge_stdout') is not None:
        write_text_creating_parent(Path(export_bundle['judge_dir']) / 'judge_stdout.txt', str(official_scores.get('judge_stdout') or ''))
    if official_scores.get('judge_stderr') is not None:
        write_text_creating_parent(Path(export_bundle['judge_dir']) / 'judge_stderr.txt', str(official_scores.get('judge_stderr') or ''))
    write_json_creating_parent(Path(export_bundle['judge_dir']) / 'per_project_results.json', per_project_results)
    index_paths = update_session_experiment_index(projecteval_root=projecteval_root, experiment_date=experiment_date, model_label=model_label_value, mode=mode_value, export_bundle=export_bundle, summary=summary)
    summary['session_index_path'] = str(index_paths['index_path'])
    summary['session_aggregate_path'] = str(index_paths['aggregate_path'])
    archived_run_dir = archive_successful_run(archive_root=Path(archive_root_value).resolve(), threshold=archive_threshold_value, experiment_date=experiment_date, model_label=model_label_value, level=level_value, mode=mode_value, models_config_path=models_config_value, system_config_path=system_config_value, export_dir=Path(export_bundle['run_dir']), summary=summary, run_metadata=run_metadata)
    if archived_run_dir is not None:
        summary['archived_run_dir'] = str(archived_run_dir)
    scoreboard_system_name = derive_scoreboard_system_name(explicit_name=scoreboard_system_name_value, level=level_value, model_label=model_label_value, model_configs=model_configs)
    scoreboard_path = update_projecteval_scoreboard(scoreboard_path=Path(scoreboard_path_value).resolve(), system_name=scoreboard_system_name, level=level_value, selected_ids=selected_ids, summary=summary, run_metadata=run_metadata, all_project_ids=sorted(dataset.keys(), key=int))
    summary['scoreboard_path'] = str(scoreboard_path)
    summary['scoreboard_system_name'] = scoreboard_system_name
    summary_path = Path(export_bundle['summary_dir']) / 'run_summary.json'
    ensure_export_bundle_dirs(export_bundle)
    write_json_creating_parent(summary_path, summary)
    print(json.dumps(summary, indent=2))
if __name__ == '__main__':
    main()