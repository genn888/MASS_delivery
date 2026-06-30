from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

@dataclass(slots=True)
class AgentEvent:
    agent_name: str
    event_type: str
    content: str
    timestamp: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def build_event(*, agent_name: str, event_type: str, content: str, metadata: dict[str, Any] | None=None) -> AgentEvent:
    return AgentEvent(agent_name=agent_name, event_type=event_type, content=content, timestamp=datetime.now(timezone.utc).isoformat(), metadata=metadata or {})

def emit_agent_event(callback: Callable[[AgentEvent], None] | None, *, agent_name: str, event_type: str, content: str, metadata: dict[str, Any] | None=None) -> None:
    if callback is None:
        return
    callback(build_event(agent_name=agent_name, event_type=event_type, content=content, metadata=metadata))