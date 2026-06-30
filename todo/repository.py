from __future__ import annotations
import json
from json import JSONDecodeError
from pathlib import Path
from todo.models import Task

class TaskRepository:

    def __init__(self, storage_path: str | Path='tasks.json') -> None:
        self.storage_path = Path(storage_path)

    def load(self) -> list[Task]:
        if not self.storage_path.exists():
            return []
        try:
            raw_items = json.loads(self.storage_path.read_text(encoding='utf-8'))
        except JSONDecodeError:
            return []
        return [Task(**item) for item in raw_items]

    def save(self, tasks: list[Task]) -> None:
        self.storage_path.write_text(json.dumps([task.to_dict() for task in tasks], indent=2), encoding='utf-8')