import ast
import py_compile
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import defaultdict
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, Any

class FileTool:
    """Simple workspace-local file read/write helper."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def resolve_path(self, relative_path: str) -> Path:
        candidate = (self.workspace / relative_path).resolve()
        candidate.relative_to(self.workspace)
        return candidate

    def read_text(self, relative_path: str) -> str:
        return self.resolve_path(relative_path).read_text(encoding='utf-8')

    def write_text(self, relative_path: str, content: str) -> Path:
        path = self.resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def write_files(self, files: Iterable[tuple[str, str]]) -> list[Path]:
        written_paths: list[Path] = []
        for relative_path, content in files:
            written_paths.append(self.write_text(relative_path, content))
        return written_paths

    def remove_dir(self, relative_path: str) -> None:
        path = self.resolve_path(relative_path)
        if path.exists():
            shutil.rmtree(path)

    def remove_path(self, relative_path: str) -> None:
        path = self.resolve_path(relative_path)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    def validate_python_syntax(self, relative_paths: Iterable[str]) -> dict[str, object]:
        checked_files: list[str] = []
        errors: list[dict[str, str]] = []
        for relative_path in relative_paths:
            if not relative_path.endswith('.py'):
                continue
            checked_files.append(relative_path)
            path = self.resolve_path(relative_path)
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append({'path': relative_path, 'message': str(exc)})
        return {'checked_files': checked_files, 'success': not errors, 'errors': errors}

    def validate_framework_sanity(self, project_root: str) -> dict[str, object]:
        root = self.resolve_path(project_root)
        errors: list[dict[str, str]] = []
        checked_files: list[str] = []
        manage_path = root / 'manage.py'
        settings_candidates = list(root.rglob('settings.py'))
        if settings_candidates and (not manage_path.exists()):
            errors.append({'path': str(root.relative_to(self.workspace)).replace('\\', '/'), 'message': 'Django-like project structure detected via settings.py, but manage.py is missing at the project root.'})
            return {'checked_files': checked_files, 'success': False, 'errors': errors}
        if not manage_path.exists():
            return {'checked_files': checked_files, 'success': True, 'errors': errors}
        checked_files.append(str(manage_path.relative_to(self.workspace)).replace('\\', '/'))
        manage_text = manage_path.read_text(encoding='utf-8')
        if 'DJANGO_SETTINGS_MODULE' not in manage_text:
            errors.append({'path': str(manage_path.relative_to(self.workspace)).replace('\\', '/'), 'message': 'manage.py exists but does not define DJANGO_SETTINGS_MODULE.'})
            return {'checked_files': checked_files, 'success': False, 'errors': errors}
        match = re.search("DJANGO_SETTINGS_MODULE',\\s*'([^']+)'", manage_text)
        if match is None:
            match = re.search('DJANGO_SETTINGS_MODULE",\\s*"([^"]+)"', manage_text)
        if match is None:
            return {'checked_files': checked_files, 'success': True, 'errors': errors}
        settings_module = match.group(1)
        settings_path = root / Path(*settings_module.split('.')).with_suffix('.py')
        urls_path = settings_path.parent / 'urls.py'
        if settings_path.exists():
            settings_relative = str(settings_path.relative_to(self.workspace)).replace('\\', '/')
            checked_files.append(settings_relative)
            settings_text = settings_path.read_text(encoding='utf-8')
            has_admin_route = False
            if urls_path.exists():
                urls_relative = str(urls_path.relative_to(self.workspace)).replace('\\', '/')
                checked_files.append(urls_relative)
                urls_text = urls_path.read_text(encoding='utf-8')
                has_admin_route = 'admin.site.urls' in urls_text
            has_admin_app = 'django.contrib.admin' in settings_text
            if has_admin_route and (not has_admin_app):
                errors.append({'path': settings_relative, 'message': "Django admin route is referenced in urls.py but 'django.contrib.admin' is missing from INSTALLED_APPS."})
            has_database_engine = "'ENGINE'" in settings_text or '"ENGINE"' in settings_text
            if 'DATABASES' in settings_text and (not has_database_engine):
                errors.append({'path': settings_relative, 'message': 'Django settings define DATABASES without an ENGINE; the project will fail on migrate/runserver.'})
            for setting_name in ('WSGI_APPLICATION', 'ASGI_APPLICATION'):
                app_match = re.search(f"""{setting_name}\\s*=\\s*['\\"]([^'\\"]+)['\\"]""", settings_text)
                if app_match is not None:
                    module_error = self._check_app_module_exists(root, app_match.group(1))
                    if module_error is not None:
                        errors.append(module_error)
            smoke_error = self._run_django_homepage_smoke_test(root)
            if smoke_error is not None:
                errors.append(smoke_error)
        return {'checked_files': checked_files, 'success': not errors, 'errors': errors}

    def _run_django_homepage_smoke_test(self, root: Path) -> dict[str, str] | None:
        migrate_result = subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=root, capture_output=True, text=True, check=False)
        if migrate_result.returncode != 0:
            details = (migrate_result.stderr or migrate_result.stdout).strip()
            if len(details) > 1200:
                details = details[:1200].rstrip() + '...'
            return {'path': str((root / 'manage.py').relative_to(self.workspace)).replace('\\', '/'), 'message': f'Django migrate smoke step failed. {details}'}
        return self._check_real_server_homepage(root)

    def _check_app_module_exists(self, root: Path, app_target: str) -> dict[str, str] | None:
        """Verify a declared WSGI/ASGI application maps to an existing module file."""
        parts = app_target.split('.')
        if parts and parts[-1] in {'application', 'app'}:
            parts = parts[:-1]
        if not parts:
            return None
        module_rel = Path(*parts).with_suffix('.py')
        if (root / module_rel).exists():
            return None
        return {'path': str((root / module_rel).relative_to(self.workspace)).replace('\\', '/'), 'message': f"Settings reference '{app_target}' but the module '{module_rel.as_posix()}' is missing; the real server (runserver) will fail to start."}

    def _check_real_server_homepage(self, root: Path, *, startup_timeout: float=15.0) -> dict[str, str] | None:
        """Launch a real ``runserver`` and GET ``/``; return an error dict on failure."""
        manage_rel = str((root / 'manage.py').relative_to(self.workspace)).replace('\\', '/')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        log_file = tempfile.TemporaryFile()
        try:
            process = subprocess.Popen([sys.executable, 'manage.py', 'runserver', f'127.0.0.1:{port}', '--noreload', '--nothreading'], cwd=root, stdout=log_file, stderr=subprocess.STDOUT)
        except OSError as exc:
            log_file.close()
            return {'path': manage_rel, 'message': f'Could not start runserver: {exc}'}
        base_url = f'http://127.0.0.1:{port}/'
        status: int | None = None
        deadline = time.monotonic() + startup_timeout
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(base_url, timeout=2) as response:
                        status = response.status
                    break
                except urllib.error.HTTPError as http_error:
                    status = http_error.code
                    break
                except (urllib.error.URLError, ConnectionError, OSError):
                    time.sleep(0.4)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        log_file.seek(0)
        server_output = log_file.read().decode('utf-8', 'ignore').strip()
        log_file.close()
        if len(server_output) > 1200:
            server_output = server_output[-1200:]
        if status is None:
            return {'path': manage_rel, 'message': f'Real server (runserver) did not serve the homepage. {server_output}'.strip()}
        if status >= 500:
            return {'path': manage_rel, 'message': f'Homepage returned HTTP {status} on the real server. {server_output}'.strip()}
        return None
    _ENTRY_POINT_NAMES: frozenset[str] = frozenset({'manage.py', 'app.py', 'main.py', 'run.py', 'wsgi.py', 'asgi.py', 'settings.py', 'urls.py', 'index.html', 'index.js', 'index.ts'})

    def get_full_snapshot(self, project_root_rel: str) -> str:
        """Return content of all files in the project."""
        root = self.resolve_path(project_root_rel)
        if not root.exists():
            return ''
        files_content = []
        for f in sorted(root.rglob('*')):
            if f.is_file() and '__pycache__' not in str(f):
                try:
                    rel = f.relative_to(root)
                    content = f.read_text(encoding='utf-8')
                    files_content.append(f'--- FILE: {rel} ---\n{content}')
                except Exception:
                    continue
        return '\n\n'.join(files_content)

    def get_focused_snapshot(self, project_root_rel: str, error_paths: list[str]=None, touched_paths: list[str]=None, max_total_files: int=25, excluded_path_patterns: tuple[str, ...]=()) -> str:
        """Return a subset of project files based on errors, touched status, and dependencies."""
        root = self.resolve_path(project_root_rel)
        if not root.exists():
            return ''
        project_files = [f for f in sorted(root.rglob('*')) if f.is_file() and '__pycache__' not in str(f)]
        all_files = [f for f in project_files if not any((fnmatch(f.relative_to(root).as_posix(), pattern) for pattern in excluded_path_patterns))]
        if len(all_files) <= max_total_files and (not error_paths) and (not excluded_path_patterns):
            return self.get_full_snapshot(project_root_rel)
        py_files = [f for f in all_files if f.suffix == '.py']
        reverse_dep_map = self._build_reverse_dep_map(root, py_files)
        focused_rel: list[Path] = []
        focused_set: set[Path] = set()

        def add_file(rel: Path) -> None:
            if rel in focused_set or len(focused_rel) >= max_total_files:
                return
            candidate = root / rel
            if candidate not in all_files:
                return
            focused_rel.append(rel)
            focused_set.add(rel)
        if error_paths:
            for p in error_paths:
                try:
                    abs_p = Path(p) if Path(p).is_absolute() else self.resolve_path(p)
                    rel = abs_p.relative_to(root)
                    add_file(rel)
                    for dependent in sorted(reverse_dep_map.get(rel, set())):
                        add_file(dependent)
                except (ValueError, Exception):
                    continue
        for f in all_files:
            if f.name in self._ENTRY_POINT_NAMES:
                add_file(f.relative_to(root))
        if touched_paths:
            for p in reversed(touched_paths):
                try:
                    abs_p = Path(p) if Path(p).is_absolute() else self.resolve_path(p)
                    rel = abs_p.relative_to(root)
                    add_file(rel)
                except (ValueError, Exception):
                    continue
        for f in all_files:
            add_file(f.relative_to(root))
        files_content: list[str] = []
        for rel in focused_rel:
            try:
                content = (root / rel).read_text(encoding='utf-8')
                files_content.append(f'--- FILE: {rel} ---\n{content}')
            except Exception:
                continue
        omitted = len(project_files) - len(files_content)
        if omitted > 0:
            files_content.append(f'--- NOTE: {omitted} other project file(s) are not shown to keep context clean. These files are still present on disk. Focus your review/fix on the visible files, but assume the rest of the project is intact. ---')
        return '\n\n'.join(files_content)

    def _build_reverse_dep_map(self, project_root: Path, py_files: list[Path]) -> dict[Path, set[Path]]:
        module_to_rel: dict[str, Path] = {}
        for f in py_files:
            rel = f.relative_to(project_root)
            parts = list(rel.with_suffix('').parts)
            dotted = '.'.join(parts)
            module_to_rel[dotted] = rel
            if parts:
                leaf = parts[-1]
                if leaf not in module_to_rel:
                    module_to_rel[leaf] = rel
        reverse: dict[Path, set[Path]] = defaultdict(set)
        for f in py_files:
            importer_rel = f.relative_to(project_root)
            try:
                source = f.read_text(encoding='utf-8', errors='ignore')
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    candidates: list[str] = []
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            candidates.append(alias.name)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        if node.level > 0:
                            pkg_parts = list(importer_rel.parts[:-1])
                            for _ in range(node.level - 1):
                                if pkg_parts:
                                    pkg_parts.pop()
                            base = '.'.join(pkg_parts)
                            full = f'{base}.{node.module}' if base else node.module
                            candidates.append(full)
                        else:
                            candidates.append(node.module)
                    for mod in candidates:
                        m = mod
                        while m:
                            if m in module_to_rel:
                                importee_rel = module_to_rel[m]
                                reverse[importee_rel].add(importer_rel)
                                break
                            m = m.rsplit('.', 1)[0] if '.' in m else ''
            except Exception:
                continue
        return reverse