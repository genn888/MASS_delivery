from __future__ import annotations
from pathlib import Path
from todo.models import Task
from todo.repository import TaskRepository

def test_repository_roundtrip(tmp_path: Path) -> None:
    repo = TaskRepository(tmp_path / 'tasks.json')
    repo.save([Task(id=1, description='Buy milk'), Task(id=2, description='Write tests')])
    loaded = repo.load()
    assert len(loaded) == 2
    assert loaded[0].description == 'Buy milk'
    assert loaded[1].id == 2

def test_repository_handles_missing_file(tmp_path: Path) -> None:
    repo = TaskRepository(tmp_path / 'missing.json')
    assert repo.load() == []

def test_repository_handles_corrupted_json(tmp_path: Path) -> None:
    path = tmp_path / 'tasks.json'
    path.write_text('{not-valid-json}', encoding='utf-8')
    repo = TaskRepository(path)
    assert repo.load() == []