from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str = ''
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

@dataclass(slots=True)
class ModelCapabilities:
    supports_tools: bool = False
    supports_json: bool = False
    supports_system_prompt: bool = True
    max_context: int | None = None

@dataclass(slots=True)
class ModelResponse:
    text: str
    raw: Any
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

class BaseLLMClient(ABC):
    """Provider-agnostic text generation client."""

    def __init__(self, capabilities: ModelCapabilities | None=None) -> None:
        self.capabilities = capabilities or ModelCapabilities()

    @abstractmethod
    def generate(self, messages: Sequence[ChatMessage], tools: Sequence[Mapping[str, Any]] | None=None, response_format: Mapping[str, Any] | None=None, temperature: float | None=None, max_tokens: int | None=None, **kwargs: Any) -> ModelResponse:
        """Generate a normalized response from the configured provider."""