from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml
from app.llm.model_config import load_model_configs
from app.ui_backend.models import BenchmarkRequest, role_settings_to_dict

class ConfigManager:

    def __init__(self, repo_root: Path | None=None) -> None:
        self.repo_root = (repo_root or Path.cwd()).resolve()

    def list_model_config_paths(self) -> list[str]:
        return sorted((str(path).replace('\\', '/') for path in (self.repo_root / 'configs').glob('models*.yaml')))

    def load_role_defaults(self, models_config_path: str | Path) -> dict[str, dict[str, Any]]:
        parsed = load_model_configs(models_config_path)
        return {role: {'model': config.model, 'temperature': float(config.temperature or 0.0), 'max_tokens': int(config.max_tokens or 2048), 'provider': config.provider, 'api_key_env': config.api_key_env, 'base_url': config.base_url, 'capabilities': {'supports_tools': config.capabilities.supports_tools, 'supports_json': config.capabilities.supports_json, 'supports_system_prompt': config.capabilities.supports_system_prompt, 'max_context': config.capabilities.max_context}, 'extra': dict(config.extra)} for role, config in parsed.items()}

    def write_session_models_config(self, *, session_dir: Path, base_models_config_path: str | Path, global_model: str | None, role_settings: dict[str, dict[str, Any]]) -> Path:
        source_path = Path(base_models_config_path)
        raw = yaml.safe_load(source_path.read_text(encoding='utf-8')) or {}
        roles = raw.setdefault('roles', {})
        for role_name, role_data in roles.items():
            if global_model:
                role_data['model'] = global_model
            override = role_settings.get(role_name)
            if override:
                role_data['model'] = override['model']
                role_data['temperature'] = override['temperature']
                role_data['max_tokens'] = override['max_tokens']
        target_path = session_dir / 'models_config.generated.yaml'
        target_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding='utf-8')
        return target_path

    def write_runner_config(self, *, session_dir: Path, request: BenchmarkRequest, models_config_path: Path) -> Path:
        payload = {'projecteval_root': request.projecteval_root, 'models_config': str(models_config_path), 'system_config': request.system_config_path, 'level': request.level, 'mode': request.mode, 'project_ids': request.project_ids, 'workspace_root': str((session_dir / 'workspace').resolve()), 'model_label': request.session_name, 'parameter_role': request.parameter_role, 'parameter_repair_role': request.parameter_repair_role, 'run_judge': request.run_judge, 'run_indicators': request.run_indicators, 'run_static_analysis': request.run_static_analysis, 'run_dynamic_analysis': request.run_dynamic_analysis, 'use_agentic_tools': request.use_agentic_tools, 'agentic_context_compaction': request.agentic_context_compaction, 'core_mode': request.core_mode, 'single_agent_iterations': request.single_agent_iterations, 'experiment_date': request.session_name, 'archive_root': request.archive_root, 'scoreboard_path': request.scoreboard_path, 'scoreboard_system_name': request.session_name, 'reuse_completed_workspaces': request.reuse_completed_workspaces, 'resume_interrupted_workspaces': request.resume_interrupted_workspaces, 'post_core_only': request.post_core_only, 'regenerate_parameters': request.regenerate_parameters, 'opencode_model': request.opencode_model, 'opencode_cli_path': request.opencode_cli_path, 'opencode_timeout_seconds': request.opencode_timeout_seconds}
        target_path = session_dir / 'benchmark_runner_config.yaml'
        target_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding='utf-8')
        return target_path

    def benchmark_request_to_config_snapshot(self, request: BenchmarkRequest) -> dict[str, Any]:
        return {'base_models_config_path': request.base_models_config_path, 'system_config_path': request.system_config_path, 'projecteval_root': request.projecteval_root, 'archive_root': request.archive_root, 'scoreboard_path': request.scoreboard_path, 'level': request.level, 'mode': request.mode, 'project_ids': list(request.project_ids), 'global_model': request.global_model, 'role_settings': role_settings_to_dict(request.role_settings), 'run_judge': request.run_judge, 'run_indicators': request.run_indicators, 'run_static_analysis': request.run_static_analysis, 'run_dynamic_analysis': request.run_dynamic_analysis, 'use_agentic_tools': request.use_agentic_tools, 'agentic_context_compaction': request.agentic_context_compaction, 'core_mode': request.core_mode, 'single_agent_iterations': request.single_agent_iterations, 'reuse_completed_workspaces': request.reuse_completed_workspaces, 'resume_interrupted_workspaces': request.resume_interrupted_workspaces, 'post_core_only': request.post_core_only, 'regenerate_parameters': request.regenerate_parameters, 'parameter_role': request.parameter_role, 'parameter_repair_role': request.parameter_repair_role, 'opencode_model': request.opencode_model, 'opencode_cli_path': request.opencode_cli_path, 'opencode_timeout_seconds': request.opencode_timeout_seconds}