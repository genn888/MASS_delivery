from __future__ import annotations
from dataclasses import asdict, dataclass

@dataclass(slots=True)
class Task:
    id: int
    description: str
    completed: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)