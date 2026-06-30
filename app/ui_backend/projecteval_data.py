from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def load_projecteval_projects(projecteval_root: str | Path='external/ProjectEval') -> list[dict[str, Any]]:
    dataset_path = Path(projecteval_root) / 'data' / 'project_eval_project.json'
    raw = json.loads(dataset_path.read_text(encoding='utf-8'))
    projects: list[dict[str, Any]] = []
    for item in raw:
        stack = item['framework_technical_stack'][0]['technical_stack']
        projects.append({'project_id': str(item['project_id']), 'project_type': item['project_type'], 'technical_stack': stack, 'prompt': item.get('nl_prompt', '')})
    return sorted(projects, key=lambda item: int(item['project_id']))