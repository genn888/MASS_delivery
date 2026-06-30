from typing import List
from models import Task
from storage import StorageHandler

class TaskNotFoundError(Exception):
    pass

class TaskManager:

    def __init__(self, storage: StorageHandler):
        self.storage = storage
        self.tasks = self.storage.load_tasks()

    def add_task(self, description: str) -> Task:
        if not description.strip():
            raise ValueError('Task description cannot be empty')
        new_id = max([t.id for t in self.tasks], default=0) + 1
        task = Task(id=new_id, description=description)
        self.tasks.append(task)
        self.storage.save_tasks(self.tasks)
        return task

    def list_tasks(self) -> List[Task]:
        return self.tasks

    def mark_complete(self, task_id: int):
        for task in self.tasks:
            if task.id == task_id:
                task.completed = True
                self.storage.save_tasks(self.tasks)
                return
        raise TaskNotFoundError(f'Task with ID {task_id} not found')

    def delete_task(self, task_id: int):
        original_count = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.id != task_id]
        if len(self.tasks) == original_count:
            raise TaskNotFoundError(f'Task with ID {task_id} not found')
        self.storage.save_tasks(self.tasks)

    def clear_completed(self):
        self.tasks = [t for t in self.tasks if not t.completed]
        self.storage.save_tasks(self.tasks)