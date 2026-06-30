from __future__ import annotations
from todo.models import Task
from todo.repository import TaskRepository

class TaskNotFoundError(ValueError):
    pass

class TodoService:

    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    def list_tasks(self) -> list[Task]:
        return self.repository.load()

    def add_task(self, description: str) -> Task:
        cleaned = description.strip()
        if not cleaned:
            raise ValueError('Task description cannot be empty.')
        tasks = self.repository.load()
        next_id = max((task.id for task in tasks), default=0) + 1
        task = Task(id=next_id, description=cleaned)
        tasks.append(task)
        self.repository.save(tasks)
        return task

    def complete_task(self, task_id: int) -> Task:
        tasks = self.repository.load()
        task = self._find_task(tasks, task_id)
        task.completed = True
        self.repository.save(tasks)
        return task

    def delete_task(self, task_id: int) -> None:
        tasks = self.repository.load()
        task = self._find_task(tasks, task_id)
        tasks.remove(task)
        self.repository.save(tasks)

    def clear_completed(self) -> int:
        tasks = self.repository.load()
        remaining = [task for task in tasks if not task.completed]
        removed = len(tasks) - len(remaining)
        self.repository.save(remaining)
        return removed

    @staticmethod
    def _find_task(tasks: list[Task], task_id: int) -> Task:
        for task in tasks:
            if task.id == task_id:
                return task
        raise TaskNotFoundError(f'Task {task_id} does not exist.')