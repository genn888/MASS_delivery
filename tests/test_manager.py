import pytest
import os
from storage import StorageHandler
from manager import TaskManager, TaskNotFoundError

@pytest.fixture
def temp_storage(tmp_path):
    file = tmp_path / 'test_tasks.json'
    return StorageHandler(filename=str(file))

@pytest.fixture
def manager(temp_storage):
    return TaskManager(temp_storage)

def test_add_task(manager):
    task = manager.add_task('Test Task')
    assert task.id == 1
    assert task.description == 'Test Task'
    assert len(manager.list_tasks()) == 1

def test_add_empty_task(manager):
    with pytest.raises(ValueError):
        manager.add_task('  ')

def test_mark_complete(manager):
    task = manager.add_task('Complete me')
    manager.mark_complete(task.id)
    assert manager.list_tasks()[0].completed is True

def test_mark_complete_not_found(manager):
    with pytest.raises(TaskNotFoundError):
        manager.mark_complete(999)

def test_delete_task(manager):
    task = manager.add_task('Delete me')
    manager.delete_task(task.id)
    assert len(manager.list_tasks()) == 0

def test_delete_not_found(manager):
    with pytest.raises(TaskNotFoundError):
        manager.delete_task(999)

def test_clear_completed(manager):
    t1 = manager.add_task('Task 1')
    t2 = manager.add_task('Task 2')
    manager.mark_complete(t1.id)
    manager.clear_completed()
    tasks = manager.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].id == t2.id