from __future__ import annotations
from pathlib import Path
from todo.repository import TaskRepository
from todo.service import TaskNotFoundError, TodoService

def build_service(tmp_path: Path) -> TodoService:
    return TodoService(TaskRepository(tmp_path / 'tasks.json'))

def test_add_task_assigns_incremental_id(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    first = service.add_task('Buy milk')
    second = service.add_task('Write tests')
    assert first.id == 1
    assert second.id == 2

def test_complete_task_marks_task_done(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    task = service.add_task('Ship feature')
    updated = service.complete_task(task.id)
    assert updated.completed is True

def test_delete_task_removes_task(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    task = service.add_task('Temporary task')
    service.delete_task(task.id)
    assert service.list_tasks() == []

def test_clear_completed_removes_only_completed_tasks(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    first = service.add_task('Done')
    second = service.add_task('Pending')
    service.complete_task(first.id)
    removed = service.clear_completed()
    remaining = service.list_tasks()
    assert removed == 1
    assert len(remaining) == 1
    assert remaining[0].description == 'Pending'
    assert remaining[0].completed is False

def test_missing_task_raises_error(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    try:
        service.complete_task(99)
    except TaskNotFoundError:
        assert True
    else:
        assert False, 'Expected TaskNotFoundError'