from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class RoleSettings:
    role: str
    model: str
    temperature: float
    max_tokens: int

@dataclass(slots=True)
class BenchmarkRequest:
    session_name: str
    project_ids: list[str]
    level: int = 2
    mode: str = 'direct'
    base_models_config_path: str = 'configs/models_nvidia_deepseek_v4_pro.yaml'
    system_config_path: str = 'configs/system.yaml'
    projecteval_root: str = 'external/ProjectEval'
    archive_root: str = 'benchmark_archives/projecteval'
    scoreboard_path: str = 'benchmark_archives/projecteval/projecteval_scoreboard.csv'
    global_model: str | None = None
    role_settings: dict[str, RoleSettings] = field(default_factory=dict)
    run_judge: bool = True
    run_indicators: bool = False
    run_static_analysis: bool = True
    run_dynamic_analysis: bool = True
    use_agentic_tools: bool = True
    agentic_context_compaction: bool = False
    core_mode: str = 'multi_agent'
    single_agent_iterations: int = 4
    reuse_completed_workspaces: bool = True
    resume_interrupted_workspaces: bool = True
    post_core_only: bool = False
    regenerate_parameters: bool = False
    parameter_role: str = 'parameter_solver'
    parameter_repair_role: str = 'parameter_repairer'
    opencode_model: str = 'local-minimax//mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7'
    opencode_cli_path: str = 'opencode'
    opencode_timeout_seconds: int = 600

@dataclass(slots=True)
class SessionSummary:
    name: str
    created_at: str
    updated_at: str
    status: str
    completed_projects: int
    total_projects: int
    local_pass_at_1: float
    official_score: float | None
    workspace_root: str

def role_settings_to_dict(role_settings: dict[str, RoleSettings]) -> dict[str, dict[str, Any]]:
    return {role: {'model': settings.model, 'temperature': settings.temperature, 'max_tokens': settings.max_tokens} for role, settings in role_settings.items()}