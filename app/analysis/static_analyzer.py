from __future__ import annotations
import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from app.benchmark.contract import classify_parameter
IGNORED_DIR_NAMES = {'.git', '.hg', '.svn', '.venv', 'venv', 'env', '__pycache__', 'node_modules', '.pytest_cache'}

@dataclass(slots=True)
class StaticIssue:
    severity: str
    code: str
    message: str
    file: str | None = None

def analyze_generated_project(project_root: Path, benchmark_contract: dict[str, Any] | None=None) -> dict[str, Any]:
    """Run benchmark-agnostic static checks over the generated project."""
    if not project_root.exists():
        return _result([StaticIssue(severity='error', code='missing_generated_root', message='Generated project root does not exist.')])
    files = _iter_project_files(project_root)
    text_files = [path for path in files if path.suffix.lower() in {'.py', '.html', '.css', '.js', '.txt', '.md', '.json'}]
    py_files = [path for path in files if path.suffix == '.py']
    html_files = [path for path in files if path.suffix.lower() in {'.html', '.htm'}]
    issues: list[StaticIssue] = []
    issues.extend(_validate_project_presence(project_root, files, py_files, html_files))
    issues.extend(_validate_python_ast(project_root, py_files))
    issues.extend(_validate_django_modelform_fields(project_root, py_files))
    issues.extend(_validate_placeholder_density(project_root, text_files))
    issues.extend(_validate_html_structure(project_root, html_files))
    issues.extend(_validate_django_shape(project_root))
    if benchmark_contract:
        issues.extend(_validate_benchmark_contract(project_root, files, html_files, benchmark_contract))
    return _result(issues)

def _validate_project_presence(project_root: Path, files: list[Path], py_files: list[Path], html_files: list[Path]) -> list[StaticIssue]:
    if not files:
        return [StaticIssue(severity='error', code='empty_project', message='Generated project root contains no files.')]
    if not py_files and (not html_files):
        return [StaticIssue(severity='warning', code='no_common_entry_sources', message='No Python or HTML sources were found; verify that the project has a runnable entrypoint.', file=str(project_root))]
    return []

def _validate_python_ast(project_root: Path, py_files: list[Path]) -> list[StaticIssue]:
    issues: list[StaticIssue] = []
    for path in py_files:
        rel = _rel(project_root, path)
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except SyntaxError as exc:
            issues.append(StaticIssue(severity='error', code='python_syntax_error', file=rel, message=f'Python syntax error: {exc.msg} at line {exc.lineno}.'))
            continue
        if rel.endswith('/__init__.py') or rel == '__init__.py':
            continue
        executable_nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If, ast.For, ast.While, ast.Try))]
        only_trivial_body = not executable_nodes and len(tree.body) <= 2
        if only_trivial_body and path.stat().st_size < 120:
            issues.append(StaticIssue(severity='warning', code='thin_python_file', file=rel, message='Python file appears very small; verify it is not a placeholder.'))
    return issues

def _validate_django_modelform_fields(project_root: Path, py_files: list[Path]) -> list[StaticIssue]:
    model_noneditable_fields: dict[str, set[str]] = {}
    parsed_files: list[tuple[Path, ast.Module]] = []
    for path in py_files:
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except SyntaxError:
            continue
        parsed_files.append((path, tree))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            noneditable = _collect_noneditable_model_fields(node)
            if noneditable:
                model_noneditable_fields[node.name] = noneditable
    if not model_noneditable_fields:
        return []
    issues: list[StaticIssue] = []
    for path, tree in parsed_files:
        rel = _rel(project_root, path)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not _looks_like_modelform(node):
                continue
            meta = _find_inner_class(node, 'Meta')
            if not meta:
                continue
            model_name = _find_meta_model_name(meta)
            fields = _find_meta_fields(meta)
            if not model_name or not fields:
                continue
            forbidden = sorted(set(fields).intersection(model_noneditable_fields.get(model_name, set())))
            for field_name in forbidden:
                issues.append(StaticIssue(severity='error', code='django_modelform_noneditable_field', file=rel, message=f'ModelForm `{node.name}` includes non-editable model field `{model_name}.{field_name}`. Remove it from Meta.fields or use an editable/form-only field.'))
    return issues

def _collect_noneditable_model_fields(class_node: ast.ClassDef) -> set[str]:
    result: set[str] = set()
    for stmt in class_node.body:
        if not isinstance(stmt, ast.Assign) or not isinstance(stmt.value, ast.Call):
            continue
        field_name = _single_assignment_name(stmt)
        if not field_name:
            continue
        if _is_django_model_field_call(stmt.value) and _field_call_is_noneditable(stmt.value):
            result.add(field_name)
    return result

def _single_assignment_name(stmt: ast.Assign) -> str | None:
    if len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    return target.id if isinstance(target, ast.Name) else None

def _is_django_model_field_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr.endswith('Field')
    if isinstance(func, ast.Name):
        return func.id.endswith('Field')
    return False

def _field_call_is_noneditable(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg in {'auto_now', 'auto_now_add'} and isinstance(keyword.value, ast.Constant) and (keyword.value.value is True):
            return True
        if keyword.arg == 'editable' and isinstance(keyword.value, ast.Constant) and (keyword.value.value is False):
            return True
    return False

def _looks_like_modelform(class_node: ast.ClassDef) -> bool:
    for base in class_node.bases:
        if isinstance(base, ast.Attribute) and base.attr == 'ModelForm':
            return True
        if isinstance(base, ast.Name) and base.id == 'ModelForm':
            return True
    return False

def _find_inner_class(class_node: ast.ClassDef, name: str) -> ast.ClassDef | None:
    for stmt in class_node.body:
        if isinstance(stmt, ast.ClassDef) and stmt.name == name:
            return stmt
    return None

def _find_meta_model_name(meta_node: ast.ClassDef) -> str | None:
    for stmt in meta_node.body:
        if isinstance(stmt, ast.Assign) and _single_assignment_name(stmt) == 'model':
            if isinstance(stmt.value, ast.Name):
                return stmt.value.id
            if isinstance(stmt.value, ast.Attribute):
                return stmt.value.attr
    return None

def _find_meta_fields(meta_node: ast.ClassDef) -> list[str]:
    for stmt in meta_node.body:
        if isinstance(stmt, ast.Assign) and _single_assignment_name(stmt) == 'fields':
            if isinstance(stmt.value, (ast.List, ast.Tuple)):
                fields: list[str] = []
                for item in stmt.value.elts:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        fields.append(item.value)
                return fields
    return []

def _validate_placeholder_density(project_root: Path, text_files: list[Path]) -> list[StaticIssue]:
    issues: list[StaticIssue] = []
    placeholder_pattern = re.compile('\\b(todo|fixme|placeholder|not implemented|pass\\s*(#|$))', re.IGNORECASE | re.MULTILINE)
    for path in text_files:
        rel = _rel(project_root, path)
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            text = path.read_text(encoding='utf-8', errors='ignore')
        matches = placeholder_pattern.findall(text)
        if len(matches) >= 3:
            issues.append(StaticIssue(severity='warning', code='placeholder_heavy_file', file=rel, message='File contains several placeholder-like markers; verify the implementation is complete.'))
    return issues

def _validate_html_structure(project_root: Path, html_files: list[Path]) -> list[StaticIssue]:
    issues: list[StaticIssue] = []
    seen_ids: dict[str, str] = {}
    for path in html_files:
        rel = _rel(project_root, path)
        text = path.read_text(encoding='utf-8', errors='ignore')
        for html_id in re.findall('\\bid=[\\"\']([^\\"\']+)[\\"\']', text):
            if html_id in seen_ids:
                issues.append(StaticIssue(severity='warning', code='duplicate_html_id', file=rel, message=f'HTML id `{html_id}` is also declared in {seen_ids[html_id]}.'))
            else:
                seen_ids[html_id] = rel
        if 'href="#"' in text or "href='#'" in text:
            issues.append(StaticIssue(severity='warning', code='placeholder_link', file=rel, message='Template contains placeholder links; verify navigation/download actions are real.'))
    return issues

def _validate_benchmark_contract(project_root: Path, files: list[Path], html_files: list[Path], benchmark_contract: dict[str, Any]) -> list[StaticIssue]:
    issues: list[StaticIssue] = []
    html_text = '\n'.join((path.read_text(encoding='utf-8', errors='ignore') for path in html_files))
    ids = set(re.findall('\\bid=[\\"\']([^\\"\']+)[\\"\']', html_text))
    names = set(re.findall('\\bname=[\\"\']([^\\"\']+)[\\"\']', html_text))
    classes: set[str] = set()
    for class_value in re.findall('\\bclass=[\\"\']([^\\"\']+)[\\"\']', html_text):
        classes.update((token for token in class_value.split() if token))
    hrefs = set(re.findall('\\bhref=[\\"\']([^\\"\']+)[\\"\']', html_text))
    tags = {tag.lower() for tag in re.findall('<\\s*([a-zA-Z][\\w:-]*)\\b', html_text)}
    all_paths = {path.relative_to(project_root).as_posix() for path in files}
    settings_text = '\n'.join((path.read_text(encoding='utf-8', errors='ignore') for path in project_root.rglob('settings.py') if path.is_file()))
    urls_text = '\n'.join((path.read_text(encoding='utf-8', errors='ignore') for path in project_root.rglob('urls.py') if path.is_file()))
    for item in _iter_contract_parameters(benchmark_contract):
        name = str(item.get('name', ''))
        answer = str(item.get('answer', '')).strip()
        kind = str(item.get('kind') or classify_parameter(name, answer))
        if not answer or answer.lower() in {'none', 'null', 'n/a'}:
            continue
        if kind == 'id' and answer not in ids:
            issues.append(StaticIssue(severity='warning', code='contract_missing_html_id', file=_best_html_file_for_text(project_root, html_files, answer), message=f'Benchmark parameter `{name}` expects HTML id `{answer}`, but no matching id was found in templates.'))
        elif kind == 'name' and answer not in names and (answer not in ids):
            issues.append(StaticIssue(severity='warning', code='contract_missing_form_name', file=_best_html_file_for_text(project_root, html_files, answer), message=f'Benchmark parameter `{name}` expects form name/id `{answer}`, but no matching name or id was found.'))
        elif kind == 'class' and answer not in classes:
            issues.append(StaticIssue(severity='warning', code='contract_missing_css_class', file=_best_html_file_for_text(project_root, html_files, answer), message=f'Benchmark parameter `{name}` expects CSS class `{answer}`, but no matching class was found.'))
        elif kind == 'url':
            path = _url_to_path(answer)
            if path and path != '/' and (path not in hrefs) and (_route_literal(path) not in urls_text):
                issues.append(StaticIssue(severity='warning', code='contract_unreferenced_url', file='urls.py', message=f'Benchmark parameter `{name}` references `{path}`, but it was not found in links or URL patterns.'))
        elif kind == 'file' and answer and ('.' in answer) and (not answer.startswith(('http://', 'https://'))):
            filename = Path(answer).name
            if filename and filename not in {Path(path).name for path in all_paths} and (filename not in html_text):
                issues.append(StaticIssue(severity='warning', code='contract_unreferenced_file', file=None, message=f'Benchmark parameter `{name}` references file `{filename}`, but no static reference was found.'))
    issues.extend(_validate_testcode_signals(project_root=project_root, html_files=html_files, html_text=html_text, ids=ids, names=names, classes=classes, tags=tags, benchmark_contract=benchmark_contract))
    risks = set(benchmark_contract.get('risks') or [])
    if 'admin' in risks and ('admin.site.urls' in urls_text or '/admin' in jsonish(benchmark_contract)):
        if 'django.contrib.admin' not in settings_text:
            issues.append(StaticIssue(severity='error', code='contract_admin_missing_app', file=_first_rel(project_root, project_root.rglob('settings.py')), message='Benchmark appears to require Django admin, but django.contrib.admin is missing from INSTALLED_APPS.'))
    if 'auth' in risks and settings_text:
        missing = [app for app in ('django.contrib.auth', 'django.contrib.sessions', 'django.contrib.messages') if app not in settings_text]
        if missing:
            issues.append(StaticIssue(severity='warning', code='contract_auth_missing_django_components', file=_first_rel(project_root, project_root.rglob('settings.py')), message=f"Benchmark appears to require auth flows; verify missing Django components: {', '.join(missing)}."))
    return issues

def _validate_testcode_signals(*, project_root: Path, html_files: list[Path], html_text: str, ids: set[str], names: set[str], classes: set[str], tags: set[str], benchmark_contract: dict[str, Any]) -> list[StaticIssue]:
    signals = benchmark_contract.get('testcode_signals') or {}
    if not isinstance(signals, dict) or not any((signals.get(key) for key in ('ids', 'names', 'classes', 'tags', 'css_selectors'))):
        return []
    missing_fragments: list[str] = []
    matched = False
    for expected in _string_values(signals.get('ids')):
        if expected in ids:
            matched = True
        else:
            missing_fragments.append(f'id="{expected}"')
    for expected in _string_values(signals.get('names')):
        if expected in names:
            matched = True
        else:
            missing_fragments.append(f'name="{expected}"')
    for expected in _string_values(signals.get('classes')):
        if expected in classes:
            matched = True
        else:
            missing_fragments.append(f'class token "{expected}"')
    for expected in _string_values(signals.get('tags')):
        if expected.lower() in tags:
            matched = True
        else:
            missing_fragments.append(f'<{expected}> tag')
    for expected in _string_values(signals.get('css_selectors')):
        if _css_selector_signal_matches(expected, html_text, ids=ids, classes=classes):
            matched = True
        else:
            missing_fragments.append(f'CSS selector `{expected}`')
    if matched:
        return []
    return [StaticIssue(severity='warning', code='testcode_signal_missing_dom_probe', file=_rel(project_root, html_files[0]) if html_files else None, message=f"ProjectEval testcode probes do not appear in the rendered templates. Missing candidate DOM probes: {', '.join(missing_fragments[:8])}.")]

def _string_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]

def _css_selector_signal_matches(selector: str, html_text: str, *, ids: set[str], classes: set[str]) -> bool:
    selector = selector.strip()
    if not selector:
        return False
    if selector.startswith('#'):
        return selector[1:] in ids
    if selector.startswith('.'):
        return selector[1:] in classes
    attr_match = re.fullmatch('\\[id=[\\"\']([^\\"\']+)[\\"\']\\]', selector)
    if attr_match:
        return attr_match.group(1) in ids
    attr_match = re.fullmatch('\\[name=[\\"\']([^\\"\']+)[\\"\']\\]', selector)
    if attr_match:
        return attr_match.group(1) in re.findall('\\bname=[\\"\']([^\\"\']+)[\\"\']', html_text)
    return selector in html_text

def _iter_contract_parameters(contract: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for items in (contract.get('selectors') or {}).values():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                result.append(item)
    if result:
        return result
    for page in contract.get('pages', []) or []:
        for fn in page.get('functions', []) or []:
            for param in fn.get('parameters', []) or []:
                if isinstance(param, dict):
                    result.append(param)
    return result

def _best_html_file_for_text(project_root: Path, html_files: list[Path], text: str) -> str | None:
    for path in html_files:
        try:
            if text in path.read_text(encoding='utf-8', errors='ignore'):
                return _rel(project_root, path)
        except OSError:
            continue
    return _rel(project_root, html_files[0]) if html_files else None

def _url_to_path(value: str) -> str:
    if value.startswith('http://') or value.startswith('https://'):
        match = re.match('https?://[^/]+(/.*)?$', value)
        return match.group(1) or '/' if match else ''
    return value if value.startswith('/') else ''

def _route_literal(path: str) -> str:
    return path.strip('/').split('/', 1)[0]

def _first_rel(project_root: Path, paths: Any) -> str | None:
    for path in paths:
        return _rel(project_root, path)
    return None

def jsonish(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return ''

def _validate_django_shape(project_root: Path) -> list[StaticIssue]:
    settings_files = list(project_root.rglob('settings.py'))
    manage_files = _find_manage_py_files(project_root)
    if settings_files and (not manage_files):
        return [StaticIssue(severity='error', code='django_missing_manage_py', file=_rel(project_root, settings_files[0]), message='Django settings.py exists but no manage.py was found in the generated project.')]
    issues: list[StaticIssue] = []
    for migrations_dir in project_root.rglob('migrations'):
        if migrations_dir.is_dir() and (not (migrations_dir / '__init__.py').exists()):
            issues.append(StaticIssue(severity='warning', code='django_migrations_missing_init', file=_rel(project_root, migrations_dir), message='Django migrations directory is missing __init__.py.'))
    return issues

def _find_manage_py_files(project_root: Path, *, max_depth: int=2) -> list[Path]:
    manage_files: list[Path] = []
    for path in project_root.rglob('manage.py'):
        if not path.is_file():
            continue
        try:
            depth = len(path.relative_to(project_root).parts) - 1
        except ValueError:
            continue
        if depth <= max_depth:
            manage_files.append(path)
    return sorted(manage_files, key=lambda item: (len(item.relative_to(project_root).parts), item.as_posix()))

def _iter_project_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in project_root.rglob('*'):
        if not path.is_file():
            continue
        if any((part in IGNORED_DIR_NAMES for part in path.parts)):
            continue
        files.append(path)
    return files

def _result(issues: list[StaticIssue]) -> dict[str, Any]:
    rendered = [{'severity': issue.severity, 'code': issue.code, 'message': issue.message, 'file': issue.file} for issue in issues]
    errors = [issue for issue in issues if issue.severity == 'error']
    summary = 'Static analysis passed.' if not issues else _render_summary(issues)
    return {'success': not errors, 'issues': rendered, 'summary': summary, 'fix_hints': _build_fix_hints(issues)}

def _render_summary(issues: list[StaticIssue]) -> str:
    lines = ['Static analysis findings:']
    for issue in issues[:12]:
        location = f' ({issue.file})' if issue.file else ''
        lines.append(f'- {issue.severity}:{issue.code}{location}: {issue.message}')
    return '\n'.join(lines)

def _build_fix_hints(issues: list[StaticIssue]) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    for issue in issues:
        hint = {'code': issue.code, 'action': {'missing_generated_root': 'regenerate_project_root', 'empty_project': 'generate_project_files', 'python_syntax_error': 'fix_python_syntax', 'placeholder_heavy_file': 'replace_placeholders_with_real_behavior', 'duplicate_html_id': 'make_html_ids_unique', 'placeholder_link': 'replace_placeholder_links', 'django_missing_manage_py': 'add_django_manage_py', 'django_migrations_missing_init': 'add_migrations_init', 'django_modelform_noneditable_field': 'remove_noneditable_field_from_modelform', 'contract_missing_html_id': 'add_exact_benchmark_html_id', 'contract_missing_form_name': 'align_form_id_and_name_with_contract', 'contract_missing_css_class': 'add_expected_css_class', 'contract_unreferenced_url': 'add_or_link_expected_route', 'contract_unreferenced_file': 'add_or_reference_expected_file', 'contract_admin_missing_app': 'enable_django_admin_components', 'contract_auth_missing_django_components': 'enable_django_auth_session_message_components'}.get(issue.code, 'inspect_static_finding')}
        if issue.file:
            hint['target'] = issue.file
        hints.append(hint)
    return hints

def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return str(path)