from __future__ import annotations
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from app.graph.state import GraphState
CHECKPOINT_FILENAME = 'workflow_checkpoint.json'
CHECKPOINT_VERSION = 1
SNAPSHOT_ROOT = 'checkpoint_snapshots'

def checkpoint_path(workspace: Path) -> Path:
    return Path(workspace) / 'artifacts' / CHECKPOINT_FILENAME

def load_checkpoint(workspace: Path) -> dict[str, Any] | None:
    path = checkpoint_path(workspace)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None

def save_checkpoint(*, workspace: Path, state: GraphState, current_node: str, status: str, last_completed_node: str | None=None, resume_node: str | None=None, note: str='') -> None:
    path = checkpoint_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'version': CHECKPOINT_VERSION, 'status': status, 'current_node': current_node, 'resume_node': resume_node or current_node, 'last_completed_node': last_completed_node, 'updated_at': datetime.now(timezone.utc).isoformat(), 'note': note, 'state': _json_safe_state(state)}
    tmp_path = path.with_suffix(path.suffix + '.tmp')
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding='utf-8')
    tmp_path.replace(path)

def mark_checkpoint_completed(*, workspace: Path, state: GraphState) -> None:
    save_checkpoint(workspace=workspace, state=state, current_node='completed', resume_node='completed', last_completed_node='finalizer', status='completed')

def restore_pre_node_snapshot(*, workspace: Path, node_name: str) -> None:
    if node_name != 'coder':
        return
    snapshot = _snapshot_path(workspace, node_name)
    target = Path(workspace) / 'generated_project'
    if not snapshot.exists():
        return
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(snapshot, target)

def prepare_pre_node_snapshot(*, workspace: Path, node_name: str) -> None:
    if node_name != 'coder':
        return
    source = Path(workspace) / 'generated_project'
    snapshot = _snapshot_path(workspace, node_name)
    if snapshot.exists():
        shutil.rmtree(snapshot)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        shutil.copytree(source, snapshot)
    else:
        snapshot.mkdir(parents=True, exist_ok=True)

def checkpoint_summary(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get('state') if isinstance(payload.get('state'), dict) else {}
    resume_node = payload.get('resume_node')
    next_iteration = None
    if resume_node in {'coder', 'test_writer', 'browser_test_writer', 'reviewer'}:
        next_iteration = (state.get('coding_iteration') or 0) + 1 if resume_node == 'coder' else state.get('coding_iteration')
    elif resume_node in {'architect', 'planning_reviewer'}:
        next_iteration = (state.get('planning_iteration') or 0) + 1 if resume_node == 'architect' else state.get('planning_iteration')
    return {'status': payload.get('status'), 'current_node': payload.get('current_node'), 'resume_node': resume_node, 'last_completed_node': payload.get('last_completed_node'), 'updated_at': payload.get('updated_at'), 'planning_iteration': state.get('planning_iteration'), 'coding_iteration': state.get('coding_iteration'), 'global_iteration': state.get('global_iteration'), 'next_iteration': next_iteration, 'trace_count': len(state.get('traces', [])) if isinstance(state.get('traces'), list) else 0}

def _snapshot_path(workspace: Path, node_name: str) -> Path:
    return Path(workspace) / 'artifacts' / SNAPSHOT_ROOT / f'before_{node_name}' / 'generated_project'

def _json_safe_state(state: GraphState) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in dict(state).items():
        if key == 'event_callback':
            continue
        try:
            json.dumps(value)
        except TypeError:
            payload[key] = str(value)
        else:
            payload[key] = value
    return payload