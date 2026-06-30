import pytest
import json
import os
from storage import StorageHandler
from models import Task

@pytest.fixture
def temp_storage(tmp_path):
    file = tmp_path / 'storage_test.json'
    return StorageHandler(filename=str(file))

def test_save_and_load(temp_storage):
    tasks = [Task(id=1, description='T1'), Task(id=2, description='T2', completed=True)]
    temp_storage.save_tasks(tasks)
    loaded = temp_storage.load_tasks()
    assert len(loaded) == 2
    assert loaded[0].description == 'T1'
    assert loaded[1].completed is True

def test_load_non_existent_file(temp_storage):
    if os.path.exists(temp_storage.filename):
        os.remove(temp_storage.filename)
    assert temp_storage.load_tasks() == []

def test_load_corrupted_file(temp_storage):
    with open(temp_storage.filename, 'w') as f:
        f.write('not json content')
    assert temp_storage.load_tasks() == []