from __future__ import annotations
import hashlib
import json
import re
from collections import Counter
from typing import Any
SELECTOR_SUFFIXES = ('_id', '_field', '_input', '_input_id', '_input_box_id', '_select_id', '_dropdown_id', '_button_id', '_btn_id', '_link_id', '_form_id', '_class', '_class_name', '_css_selector', '_xpath')
RISK_KEYWORDS = {'auth': ('login', 'log in', 'signup', 'sign up', 'password', 'username', 'logout'), 'admin': ('admin', '/admin', 'administrator', 'superuser'), 'crud': ('add', 'create', 'edit', 'update', 'delete', 'submit', 'save'), 'download': ('download', 'export', 'file', 'upload'), 'database': ('dashboard', 'claim', 'transaction', 'profile', 'record', 'model'), 'batch_io': ('input file', 'output file', 'xlsx', 'csv', 'histogram', 'image_name')}

def build_benchmark_contract(*, project_id: str='', project_type: str='', technical_stack: str='', level: int | None=None, mode: str='', testcode: list[dict[str, Any]] | None=None, nl_checklist: list[dict[str, Any]] | None=None) -> dict[str, Any]:
    """Build a compact deterministic contract from ProjectEval metadata."""
    raw_testcode = testcode or []
    pages: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    urls: list[str] = []
    expected_texts: list[str] = []
    testcode_signals = extract_testcode_signals(raw_testcode)
    selectors_by_kind: dict[str, list[dict[str, str]]] = {'id': [], 'name': [], 'class': [], 'css': [], 'xpath': [], 'url': [], 'file': [], 'text': [], 'value': [], 'other': []}
    risk_counter: Counter[str] = Counter()
    for page in raw_testcode:
        page_name = str(page.get('page') or page.get('name') or '')
        functions = []
        for fn in page.get('function', []) or []:
            function_name = str(fn.get('function') or fn.get('name') or '')
            function_parameters = []
            combined_text = f'{page_name} {function_name}'.lower()
            for risk, needles in RISK_KEYWORDS.items():
                if any((needle in combined_text for needle in needles)):
                    risk_counter[risk] += 1
            for param in fn.get('parameter', []) or []:
                if not isinstance(param, dict):
                    continue
                name = str(param.get('name', '')).strip()
                answer = str(param.get('answer', '')).strip()
                description = str(param.get('description', '')).strip()
                kind = classify_parameter(name, answer, description)
                record = {'page': page_name, 'function': function_name, 'name': name, 'answer': answer, 'kind': kind}
                if description:
                    record['description'] = description
                parameters.append(record)
                function_parameters.append(record)
                selectors_by_kind.setdefault(kind, selectors_by_kind['other']).append({'page': page_name, 'function': function_name, 'name': name, 'answer': answer})
                if kind == 'url' and answer:
                    urls.append(answer)
                elif kind == 'text' and answer:
                    expected_texts.append(answer)
            functions.append({'name': function_name, 'parameter_count': len(function_parameters), 'parameters': [{'name': item['name'], 'kind': item['kind'], 'answer': item.get('answer', '')} for item in function_parameters]})
        pages.append({'name': page_name, 'functions': functions})
    checklist_items = summarize_checklist(nl_checklist or [])
    risks = sorted(risk_counter)
    contract = {'project_id': str(project_id), 'project_type': str(project_type), 'technical_stack': str(technical_stack), 'level': level, 'mode': str(mode), 'page_count': len(pages), 'function_count': sum((len(page['functions']) for page in pages)), 'parameter_count': len(parameters), 'pages': pages, 'selectors': {key: value for key, value in selectors_by_kind.items() if value}, 'urls': sorted(set(urls)), 'expected_texts': dedupe_keep_order(expected_texts)[:40], 'testcode_signals': testcode_signals, 'risks': risks, 'checklist': checklist_items, 'summary': render_contract_summary(project_id=project_id, project_type=project_type, technical_stack=technical_stack, page_count=len(pages), function_count=sum((len(page['functions']) for page in pages)), parameter_count=len(parameters), risks=risks)}
    contract['hash'] = stable_hash(contract)
    return contract

def classify_parameter(name: str, answer: str='', description: str='') -> str:
    lowered = name.lower()
    haystack = f'{lowered} {description.lower()} {answer.lower()}'
    if 'xpath' in lowered:
        return 'xpath'
    if 'css_selector' in lowered or lowered.endswith('_selector'):
        return 'css'
    if lowered.endswith('_class_name') or lowered.endswith('_class') or 'class_name' in lowered:
        return 'class'
    if lowered.endswith('_id') or '_id_' in lowered or lowered in {'id', 'button', 'login_button', 'save_button'} or any((token in lowered for token in ('button_id', 'link_id', 'form_id'))):
        return 'id'
    if lowered.endswith('_name') or lowered.endswith('_field') or 'input_name' in lowered:
        return 'name'
    if lowered.endswith('_url') or lowered == 'test_url' or 'url' in lowered:
        return 'url'
    if any((token in lowered for token in ('path', 'file', 'filename', 'image_name'))):
        return 'file'
    if any((token in lowered for token in ('text', 'message', 'output', 'title'))):
        return 'text'
    if 'value' in haystack or lowered.endswith('_command'):
        return 'value'
    return 'other'

def summarize_checklist(items: list[dict[str, Any]]) -> list[str]:
    rendered: list[str] = []
    for item in items[:30]:
        if isinstance(item, dict):
            text = item.get('description') or item.get('name') or item.get('requirement') or item.get('content')
        else:
            text = str(item)
        if text:
            rendered.append(str(text).strip())
    return rendered

def render_contract_summary(*, project_id: str, project_type: str, technical_stack: str, page_count: int, function_count: int, parameter_count: int, risks: list[str]) -> str:
    risk_text = ', '.join(risks) if risks else 'none'
    return f'ProjectEval contract project={project_id}, type={project_type}, stack={technical_stack}. Pages={page_count}, functions={function_count}, parameters={parameter_count}. Detected risks: {risk_text}.'

def compact_contract_for_prompt(contract: dict[str, Any] | None, *, max_items_per_kind: int=80) -> dict[str, Any]:
    """Return a prompt-sized view that preserves contract signal without raw testcode bloat."""
    if not isinstance(contract, dict) or not contract:
        return {}
    selectors = {}
    for kind, items in (contract.get('selectors') or {}).items():
        if not isinstance(items, list):
            continue
        selectors[kind] = [{'page': item.get('page', ''), 'function': item.get('function', ''), 'name': item.get('name', ''), 'answer': item.get('answer', '')} for item in items[:max_items_per_kind] if isinstance(item, dict)]
    return {'project_id': contract.get('project_id'), 'project_type': contract.get('project_type'), 'technical_stack': contract.get('technical_stack'), 'summary': contract.get('summary'), 'risks': contract.get('risks', []), 'urls': contract.get('urls', [])[:60], 'selectors': selectors, 'expected_texts': contract.get('expected_texts', [])[:60], 'testcode_signals': compact_testcode_signals(contract.get('testcode_signals') or {}), 'checklist': contract.get('checklist', [])[:40], 'hash': contract.get('hash')}

def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

def extract_testcode_signals(testcode: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract literal external-judge probes from ProjectEval test snippets."""
    signals: dict[str, list[str]] = {'ids': [], 'names': [], 'classes': [], 'css_selectors': [], 'xpaths': [], 'tags': [], 'expected_texts': []}
    for page in testcode:
        if not isinstance(page, dict):
            continue
        for fn in page.get('function', []) or []:
            if not isinstance(fn, dict):
                continue
            source = str(fn.get('test') or '')
            if not source:
                continue
            _extend(signals['ids'], _extract_by_literals(source, 'ID'))
            _extend(signals['names'], _extract_by_literals(source, 'NAME'))
            _extend(signals['classes'], _extract_by_literals(source, 'CLASS_NAME'))
            _extend(signals['css_selectors'], _extract_by_literals(source, 'CSS_SELECTOR'))
            _extend(signals['xpaths'], _extract_by_literals(source, 'XPATH'))
            _extend(signals['tags'], _extract_by_literals(source, 'TAG_NAME'))
            _extend(signals['expected_texts'], _extract_expected_text_literals(source))
    return {key: dedupe_keep_order(values) for key, values in signals.items() if values}

def compact_testcode_signals(signals: dict[str, Any], *, max_items_per_kind: int=20) -> dict[str, list[str]]:
    compact: dict[str, list[str]] = {}
    for key in ('ids', 'names', 'classes', 'css_selectors', 'xpaths', 'tags', 'expected_texts'):
        values = signals.get(key)
        if not isinstance(values, list):
            continue
        compact[key] = [str(value) for value in values if str(value).strip()][:max_items_per_kind]
    return {key: value for key, value in compact.items() if value}

def _extract_by_literals(source: str, by_name: str) -> list[str]:
    pattern = re.compile(f"""By\\.{re.escape(by_name)}\\s*,\\s*([\\"'])(?P<value>.+?)\\1""", flags=re.DOTALL)
    return [match.group('value').strip() for match in pattern.finditer(source) if match.group('value').strip()]

def _extract_expected_text_literals(source: str) -> list[str]:
    candidates: list[str] = []
    for literal in re.findall('([\\"\'])(?P<value>[A-Za-z][A-Za-z0-9 _!?.-]{2,})\\1', source):
        value = literal[1].strip()
        lowered = value.lower()
        if lowered.startswith(('http://', 'https://')):
            continue
        if lowered in {'id', 'class', 'name', 'button', 'a', 'div', 'span', 'input'}:
            continue
        candidates.append(value)
    return candidates

def _extend(target: list[str], values: list[str]) -> None:
    for value in values:
        if value:
            target.append(value)

def stable_hash(payload: dict[str, Any]) -> str:
    payload_without_hash = {key: value for key, value in payload.items() if key != 'hash'}
    text = json.dumps(payload_without_hash, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]

def extract_literal_url_candidates(contract: dict[str, Any] | None) -> list[str]:
    if not isinstance(contract, dict):
        return []
    urls = [str(url) for url in contract.get('urls', []) if str(url).strip()]
    normalized: list[str] = []
    for url in urls:
        if url.startswith('http://example.com'):
            normalized.append(url.replace('http://example.com', 'http://127.0.0.1:8000', 1))
        elif url.startswith('/'):
            normalized.append(f'http://127.0.0.1:8000{url}')
        else:
            normalized.append(url)
    return dedupe_keep_order(normalized)

def looks_like_selector_parameter(name: str) -> bool:
    lowered = name.lower()
    return any((token in lowered for token in SELECTOR_SUFFIXES))