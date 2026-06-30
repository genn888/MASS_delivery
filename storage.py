import json
import os
from typing import List
from models import Task

class StorageHandler:

    def __init__(self, filename='tasks.json'):
        self.filename = filename

    def load_tasks(self) -> List[Task]:
        if not os.path.exists(self.filename):
            return []
        try:
            with open(self.filename, 'r') as f:
                data = json.load(f)
                return [Task.from_dict(item) for item in data]
        except (json.JSONDecodeError, IOError):
            return []

    def save_tasks(self, tasks: List[Task]):
        try:
            with open(self.filename, 'w') as f:
                json.dump([task.to_dict() for task in tasks], f, indent=4)
        except IOError as e:
            print(f'Error saving tasks: {e}')