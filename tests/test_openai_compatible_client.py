from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.llm.base_client import ModelCapabilities
from app.llm.model_config import RoleModelConfig
from app.llm.providers.openai_compatible_client import OpenAICompatibleClient

def test_clamp_max_tokens_to_context_reduces_oversized_request():
    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    client.capabilities = ModelCapabilities(max_context=32768)
    client.config = RoleModelConfig(role='coder', provider='openai_compatible', model='qwen/qwen3.6-27b', max_tokens=131072)
    assert client._clamp_max_tokens_to_context(131072) == 32768

def test_clamp_max_tokens_to_context_keeps_valid_request():
    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    client.capabilities = ModelCapabilities(max_context=32768)
    client.config = RoleModelConfig(role='reviewer', provider='openai_compatible', model='qwen/qwen3.6-27b', max_tokens=8192)
    assert client._clamp_max_tokens_to_context(8192) == 8192
    assert client._clamp_max_tokens_to_context(None) is None