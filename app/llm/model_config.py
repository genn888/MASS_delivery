from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml
from app.llm.base_client import ModelCapabilities

@dataclass(slots=True)
class RoleModelConfig:
    role: str
    provider: str
    model: str
    api_key_env: str | None = None
    base_url: str | None = None
    temperature: float | None = 0.0
    max_tokens: int | None = None
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    extra: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class SystemConfig:
    max_planning_iterations: int = 2
    max_coding_iterations: int = 2
    max_global_iterations: int = 3

def _read_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open('r', encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}

def load_model_configs(path: str | Path) -> dict[str, RoleModelConfig]:
    data = _read_yaml(path)
    roles = data.get('roles', {})
    parsed_configs: dict[str, RoleModelConfig] = {}
    for role_name, role_data in roles.items():
        capabilities_raw = role_data.get('capabilities', {})
        known_keys = {'provider', 'model', 'api_key_env', 'base_url', 'temperature', 'max_tokens', 'capabilities'}
        parsed_configs[role_name] = RoleModelConfig(role=role_name, provider=role_data.get('provider', 'mock'), model=role_data.get('model', 'mock-default'), api_key_env=role_data.get('api_key_env'), base_url=role_data.get('base_url'), temperature=role_data.get('temperature', 0.0), max_tokens=role_data.get('max_tokens'), capabilities=ModelCapabilities(supports_tools=bool(capabilities_raw.get('supports_tools', False)), supports_json=bool(capabilities_raw.get('supports_json', False)), supports_system_prompt=bool(capabilities_raw.get('supports_system_prompt', True)), max_context=capabilities_raw.get('max_context')), extra={key: value for key, value in role_data.items() if key not in known_keys})
    return parsed_configs

def load_system_config(path: str | Path) -> SystemConfig:
    data = _read_yaml(path)
    return SystemConfig(max_planning_iterations=int(data.get('max_planning_iterations', 2)), max_coding_iterations=int(data.get('max_coding_iterations', 2)), max_global_iterations=int(data.get('max_global_iterations', 3)))