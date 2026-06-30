from __future__ import annotations
from app.llm.base_client import BaseLLMClient
from app.llm.model_config import RoleModelConfig
from app.llm.registry import LLMRegistry
REQUIRED_WORKFLOW_ROLES = {'requirement_analyzer', 'architect', 'planning_reviewer', 'coder', 'reviewer', 'test_writer'}

def create_llm_registry(model_configs: dict[str, RoleModelConfig], registry: LLMRegistry | None=None) -> dict[str, BaseLLMClient]:
    missing_roles = REQUIRED_WORKFLOW_ROLES.difference(model_configs)
    if missing_roles:
        missing = ', '.join(sorted(missing_roles))
        raise ValueError(f'Missing role configuration(s): {missing}')
    active_registry = registry or LLMRegistry()
    return {role_name: active_registry.create(config) for role_name, config in model_configs.items()}