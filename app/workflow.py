from __future__ import annotations
from pathlib import Path
from typing import Any
from app.graph.checkpoint import load_checkpoint, restore_pre_node_snapshot
from app.graph.builder import build_workflow
from app.graph.state import build_initial_state
from app.llm.factory import create_llm_registry
from app.llm.model_config import load_model_configs, load_system_config

def run_workflow(*, user_task: str, workspace: Path, models_config_path: str | Path, system_config_path: str | Path, initial_overrides: dict[str, Any] | None=None, resume_from_checkpoint: bool=False) -> dict[str, Any]:
    models_config = load_model_configs(models_config_path)
    system_config = load_system_config(system_config_path)
    llm_registry = create_llm_registry(models_config)
    resolved_workspace = workspace.resolve()
    checkpoint = load_checkpoint(resolved_workspace) if resume_from_checkpoint else None
    start_node = 'requirement_analyzer'
    if checkpoint and checkpoint.get('status') != 'completed':
        checkpoint_state = checkpoint.get('state') if isinstance(checkpoint.get('state'), dict) else {}
        resume_node = str(checkpoint.get('resume_node') or checkpoint.get('current_node') or start_node)
        restore_pre_node_snapshot(workspace=resolved_workspace, node_name=resume_node)
        initial_state = build_initial_state(user_task=user_task, workspace=resolved_workspace, system_config=system_config)
        initial_state.update(checkpoint_state)
        initial_state['workspace'] = str(resolved_workspace)
        start_node = resume_node
    else:
        initial_state = build_initial_state(user_task=user_task, workspace=resolved_workspace, system_config=system_config)
    if initial_overrides:
        initial_state.update(initial_overrides)
    app = build_workflow(llm_registry=llm_registry, workspace=resolved_workspace, system_config=system_config, start_node=start_node)
    return app.invoke(initial_state)