from dataclasses import dataclass

@dataclass
class Task:
    id: int
    description: str
    completed: bool = False

    def to_dict(self):
        return {'id': self.id, 'description': self.description, 'completed': self.completed}

    @classmethod
    def from_dict(cls, data):
        return cls(**data)