"""Per-iteration code history for the generated project."""
from __future__ import annotations
import logging
import shutil
import subprocess
from pathlib import Path
logger = logging.getLogger(__name__)
HISTORY_DIRNAME = 'code_history'
_IGNORED_DIRS = {'.git', '__pycache__', '.pytest_cache', '.mypy_cache', 'node_modules'}

def record_code_history(*, workspace: Path, coding_iteration: int | None) -> str | None:
    """Commit the current generated project state and write the iteration diff."""
    try:
        source = Path(workspace) / 'generated_project'
        if not source.exists():
            return None
        repo = Path(workspace) / 'artifacts' / HISTORY_DIRNAME
        if not _ensure_repo(repo):
            return None
        _mirror_tree(source, repo)
        _git(repo, 'add', '-A')
        iteration_label = coding_iteration if coding_iteration is not None else '?'
        _git(repo, 'commit', '-q', '--allow-empty', '-m', f'coder iteration {iteration_label}')
        diff = _git_capture(repo, 'show', '--no-color', '--stat', '--patch', 'HEAD')
        patch_path = Path(workspace) / 'artifacts' / f'code_diff_iteration_{iteration_label}.patch'
        patch_path.write_text(diff, encoding='utf-8')
        return str(patch_path)
    except Exception as exc:
        logger.warning('Failed to record code history for iteration %s: %s', coding_iteration, exc)
        return None

def _ensure_repo(repo: Path) -> bool:
    if (repo / '.git').exists():
        return True
    repo.mkdir(parents=True, exist_ok=True)
    if _git(repo, 'init', '-q') is None:
        return False
    _git(repo, 'config', 'user.email', 'mass@local')
    _git(repo, 'config', 'user.name', 'MASS')
    (repo / '.gitignore').write_text('__pycache__/\n*.pyc\n.pytest_cache/\n*.sqlite3\n*.db\n', encoding='utf-8')
    return True

def _mirror_tree(source: Path, repo: Path) -> None:
    """Make ``repo`` mirror ``source`` (excluding caches), preserving ``repo/.git``."""
    for child in repo.iterdir():
        if child.name == '.git':
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
    for path in source.rglob('*'):
        if set(path.parts) & _IGNORED_DIRS:
            continue
        rel = path.relative_to(source)
        target = repo / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, check=False)
    except (OSError, FileNotFoundError) as exc:
        logger.warning('git command failed (%s): %s', ' '.join(args), exc)
        return None

def _git_capture(repo: Path, *args: str) -> str:
    result = _git(repo, *args)
    if result is None:
        return ''
    return result.stdout or ''