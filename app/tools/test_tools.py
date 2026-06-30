from __future__ import annotations
import subprocess
import sys
import re
from pathlib import Path
from typing import Any

class TestTool:
    """Run Python tests inside the configured workspace."""
    __test__ = False

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def run_pytest(self, target_root: Path | None=None) -> dict[str, Any]:
        active_root = (target_root or self.workspace).resolve()
        tests_dir = active_root / 'tests'
        target = str(tests_dir) if tests_dir.exists() else str(active_root)
        return self.run_pytest_target(active_root, Path(target))

    def run_pytest_targets(self, target_root: Path, targets: list[Path]) -> dict[str, Any]:
        active_root = target_root.resolve()
        active_targets = [target.resolve() for target in targets]
        command = [sys.executable, '-m', 'pytest', *[str(target) for target in active_targets]]
        completed = subprocess.run(command, cwd=active_root, capture_output=True, text=True, check=False)
        no_tests_collected = completed.returncode == 5
        success = completed.returncode == 0
        failure_summary = self._summarize_pytest_output(completed.stdout, completed.stderr)
        if not success:
            combined = f'{completed.stdout}\n{completed.stderr}'.strip()
            last_error_line = next((line.strip() for line in reversed(combined.splitlines()) if line.strip()), 'Django check failed.')
            failure_summary = {**failure_summary, 'status': 'failed', 'summary': last_error_line, 'failures': failure_summary.get('failures') or [{'title': 'Django manage.py check failed', 'details': last_error_line}]}
        return {'command': command, 'returncode': completed.returncode, 'success': success, 'no_tests_collected': no_tests_collected, 'stdout': completed.stdout, 'stderr': completed.stderr, 'failure_summary': failure_summary, 'note': 'returncode 5 means no tests were collected and is treated as a failure signal.'}

    def find_django_manage_py(self, target_root: Path, *, max_depth: int=2) -> Path | None:
        """Find a plausible Django manage.py, allowing common nested project roots."""
        active_root = target_root.resolve()
        direct = active_root / 'manage.py'
        if direct.exists():
            return direct
        candidates: list[Path] = []
        for path in active_root.rglob('manage.py'):
            try:
                depth = len(path.relative_to(active_root).parts) - 1
            except ValueError:
                continue
            if depth <= max_depth:
                candidates.append(path)
        return sorted(candidates, key=lambda item: (len(item.relative_to(active_root).parts), item.as_posix()))[0] if candidates else None

    def run_django_check(self, target_root: Path) -> dict[str, Any]:
        active_root = target_root.resolve()
        manage_py = self.find_django_manage_py(active_root)
        if not manage_py:
            settings_files = list(active_root.rglob('settings.py'))
            return {'command': [], 'returncode': 0 if not settings_files else 1, 'success': not settings_files, 'stdout': '', 'stderr': 'Django settings.py exists but no manage.py was found.' if settings_files else '', 'manage_py': None, 'django_root': None, 'skipped': not settings_files, 'failure_summary': {'status': 'failed' if settings_files else 'skipped', 'summary': 'missing manage.py' if settings_files else 'not a Django project', 'failures': [], 'truncated': False}}
        command = [sys.executable, str(manage_py), 'check']
        completed = subprocess.run(command, cwd=manage_py.parent, capture_output=True, text=True, check=False)
        success = completed.returncode == 0
        failure_summary = self._summarize_pytest_output(completed.stdout, completed.stderr)
        if not success:
            combined = f'{completed.stdout}\n{completed.stderr}'.strip()
            last_error_line = next((line.strip() for line in reversed(combined.splitlines()) if line.strip()), 'Django check failed.')
            failure_summary = {**failure_summary, 'status': 'failed', 'summary': last_error_line, 'failures': failure_summary.get('failures') or [{'title': 'Django manage.py check failed', 'details': last_error_line}]}
        return {'command': command, 'returncode': completed.returncode, 'success': success, 'stdout': completed.stdout, 'stderr': completed.stderr, 'manage_py': str(manage_py), 'django_root': str(manage_py.parent), 'skipped': False, 'failure_summary': failure_summary}

    def run_pytest_target(self, target_root: Path, target: Path) -> dict[str, Any]:
        active_root = target_root.resolve()
        active_target = target.resolve()
        command = [sys.executable, '-m', 'pytest', str(active_target)]
        completed = subprocess.run(command, cwd=active_root, capture_output=True, text=True, check=False)
        no_tests_collected = completed.returncode == 5
        success = completed.returncode == 0
        return {'command': command, 'returncode': completed.returncode, 'success': success, 'no_tests_collected': no_tests_collected, 'stdout': completed.stdout, 'stderr': completed.stderr, 'failure_summary': self._summarize_pytest_output(completed.stdout, completed.stderr), 'note': 'returncode 5 means no tests were collected and is treated as a failure signal.'}

    @staticmethod
    def _summarize_pytest_output(stdout: str, stderr: str, *, max_failures: int=5) -> dict[str, Any]:
        combined = f'{stdout}\n{stderr}'.strip()
        failures: list[dict[str, str]] = []
        current: dict[str, str] | None = None
        for raw_line in combined.splitlines():
            line = raw_line.rstrip()
            header = re.match('_{3,}\\s+(.+?)\\s+_{3,}$', line)
            if header:
                if current:
                    failures.append(current)
                current = {'title': header.group(1)[:180], 'details': ''}
                if len(failures) >= max_failures:
                    break
                continue
            if current is not None:
                if line.startswith(('E   ', 'E    ', 'FAILED ', 'ERROR ')):
                    details = current.get('details', '')
                    if len(details) < 1200:
                        current['details'] = (details + '\n' + line.strip()).strip()
            elif line.startswith(('FAILED ', 'ERROR ')):
                failures.append({'title': line[:180], 'details': ''})
                if len(failures) >= max_failures:
                    break
        if current and len(failures) < max_failures:
            failures.append(current)
        summary_match = re.search('=+\\s*(.+?(?:failed|passed|error|errors).+?)\\s*=+$', combined, flags=re.IGNORECASE | re.MULTILINE)
        return {'status': 'passed' if ' failed' not in combined.lower() and ' error' not in combined.lower() else 'failed', 'summary': summary_match.group(1).strip() if summary_match else '', 'failures': failures[:max_failures], 'truncated': len(failures) > max_failures}