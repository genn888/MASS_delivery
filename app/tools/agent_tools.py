"""Agentic tool layer for LLM tool-calling."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from app.tools.file_tools import FileTool
from app.tools.test_tools import TestTool
MAX_READ_CHARS = 16000
MAX_LIST_FILES = 400
MAX_GREP_MATCHES = 100
MAX_OUTPUT_TAIL = 3000
READ_TOOLS = ('read_file', 'list_files', 'grep')
WRITE_TOOLS = ('write_file', 'delete_path')
CHECK_TOOLS = ('validate_python', 'django_check', 'run_pytest')

@dataclass(slots=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]

    def schema(self) -> dict[str, Any]:
        return {'type': 'function', 'function': {'name': self.name, 'description': self.description, 'parameters': self.parameters}}

class ToolRegistry:
    """Holds available tools and dispatches model-issued calls."""

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self, names: tuple[str, ...] | list[str] | None=None) -> list[dict[str, Any]]:
        selected = list(names) if names is not None else self.names()
        return [self._tools[n].schema() for n in selected if n in self._tools]

    def execute(self, name: str, arguments: Any) -> str:
        """Run a tool by name with raw arguments (JSON string or dict). Never raises."""
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({'error': f"unknown tool '{name}'"})
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as exc:
                return json.dumps({'error': f'invalid JSON arguments: {exc}'})
        elif isinstance(arguments, dict):
            args = arguments
        elif arguments is None:
            args = {}
        else:
            return json.dumps({'error': 'arguments must be a JSON object'})
        try:
            return tool.handler(args)
        except Exception as exc:
            return json.dumps({'error': f'{type(exc).__name__}: {exc}'})

def build_tool_registry(*, file_tool: FileTool, test_tool: TestTool | None=None, project_root_rel: str='generated_project') -> ToolRegistry:
    """Build a registry over the existing FileTool/TestTool, scoped to the project root."""
    root_rel = project_root_rel.strip('/')

    def proj(rel: str) -> str:
        clean = str(rel or '').strip().replace('\\', '/').lstrip('/')
        if clean == root_rel or clean.startswith(f'{root_rel}/'):
            return clean
        return f'{root_rel}/{clean}' if clean else root_rel

    def project_base() -> Path:
        return file_tool.resolve_path(root_rel)

    def read_file(args: dict[str, Any]) -> str:
        rel = str(args.get('path', '')).strip()
        if not rel:
            return json.dumps({'error': "missing required argument 'path'"})
        try:
            content = file_tool.read_text(proj(rel))
        except FileNotFoundError:
            return json.dumps({'error': f'file not found: {rel}'})
        except (ValueError, OSError) as exc:
            return json.dumps({'error': f'{type(exc).__name__}: {exc}'})
        truncated = len(content) > MAX_READ_CHARS
        return json.dumps({'path': rel, 'truncated': truncated, 'content': content[:MAX_READ_CHARS]})

    def list_files(args: dict[str, Any]) -> str:
        subdir = str(args.get('subdir', '') or '').strip()
        try:
            target = file_tool.resolve_path(proj(subdir) if subdir else root_rel)
        except ValueError as exc:
            return json.dumps({'error': str(exc), 'files': []})
        if not target.exists():
            return json.dumps({'error': 'path does not exist', 'files': []})
        base = project_base()
        files: list[str] = []
        for path in sorted(target.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                files.append(path.relative_to(base).as_posix())
                if len(files) >= MAX_LIST_FILES:
                    break
        return json.dumps({'files': files, 'truncated': len(files) >= MAX_LIST_FILES})

    def grep(args: dict[str, Any]) -> str:
        pattern = str(args.get('pattern', ''))
        if not pattern:
            return json.dumps({'error': "missing required argument 'pattern'"})
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return json.dumps({'error': f'invalid regex: {exc}'})
        subdir = str(args.get('subdir', '') or '').strip()
        try:
            target = file_tool.resolve_path(proj(subdir) if subdir else root_rel)
        except ValueError as exc:
            return json.dumps({'error': str(exc), 'matches': []})
        if not target.exists():
            return json.dumps({'error': 'path does not exist', 'matches': []})
        base = project_base()
        matches: list[str] = []
        for path in sorted(target.rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            rel = path.relative_to(base).as_posix()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f'{rel}:{lineno}: {line.strip()[:200]}')
                    if len(matches) >= MAX_GREP_MATCHES:
                        break
            if len(matches) >= MAX_GREP_MATCHES:
                break
        return json.dumps({'matches': matches, 'truncated': len(matches) >= MAX_GREP_MATCHES})

    def write_file(args: dict[str, Any]) -> str:
        rel = str(args.get('path', '')).strip()
        content = args.get('content')
        if not rel:
            return json.dumps({'error': "missing required argument 'path'"})
        if not isinstance(content, str):
            return json.dumps({'error': "'content' must be a string"})
        try:
            file_tool.write_text(proj(rel), content)
        except (ValueError, OSError) as exc:
            return json.dumps({'error': f'{type(exc).__name__}: {exc}'})
        return json.dumps({'written': rel, 'bytes': len(content)})

    def delete_path(args: dict[str, Any]) -> str:
        rel = str(args.get('path', '')).strip()
        if not rel:
            return json.dumps({'error': "missing required argument 'path'"})
        try:
            file_tool.remove_path(proj(rel))
        except (ValueError, OSError) as exc:
            return json.dumps({'error': f'{type(exc).__name__}: {exc}'})
        return json.dumps({'deleted': rel})

    def validate_python(args: dict[str, Any]) -> str:
        raw_paths = args.get('paths')
        if raw_paths is None:
            base = project_base()
            checked = [p.relative_to(file_tool.workspace).as_posix() for p in sorted(base.rglob('*.py')) if '__pycache__' not in p.parts]
        elif isinstance(raw_paths, list):
            checked = [proj(str(p)) for p in raw_paths]
        else:
            return json.dumps({'error': "'paths' must be a list when provided"})
        return json.dumps(file_tool.validate_python_syntax(checked))

    def django_check(_args: dict[str, Any]) -> str:
        if test_tool is None:
            return json.dumps({'error': 'test tool not available for this agent'})
        result = test_tool.run_django_check(project_base())
        return json.dumps({'success': result.get('success'), 'returncode': result.get('returncode'), 'skipped': result.get('skipped'), 'summary': (result.get('failure_summary') or {}).get('summary'), 'stderr_tail': str(result.get('stderr') or '')[-MAX_OUTPUT_TAIL:]})

    def run_pytest(args: dict[str, Any]) -> str:
        if test_tool is None:
            return json.dumps({'error': 'test tool not available for this agent'})
        base = project_base()
        target = str(args.get('target', '') or '').strip()
        if target:
            try:
                resolved = file_tool.resolve_path(proj(target))
            except ValueError as exc:
                return json.dumps({'error': str(exc)})
            result = test_tool.run_pytest_target(base, resolved)
        else:
            result = test_tool.run_pytest(base)
        return json.dumps({'success': result.get('success'), 'returncode': result.get('returncode'), 'no_tests_collected': result.get('no_tests_collected'), 'summary': (result.get('failure_summary') or {}).get('summary'), 'stdout_tail': str(result.get('stdout') or '')[-MAX_OUTPUT_TAIL:], 'stderr_tail': str(result.get('stderr') or '')[-MAX_OUTPUT_TAIL:]})
    registry = ToolRegistry()
    registry.register(AgentTool(name='read_file', description='Read a text file from the generated project and return its content.', parameters={'type': 'object', 'properties': {'path': {'type': 'string', 'description': 'Path relative to the project root'}}, 'required': ['path']}, handler=read_file))
    registry.register(AgentTool(name='list_files', description='List files in the generated project (optionally under a subdirectory).', parameters={'type': 'object', 'properties': {'subdir': {'type': 'string', 'description': 'Optional subdirectory relative to the project root'}}}, handler=list_files))
    registry.register(AgentTool(name='grep', description='Search the generated project for a regex pattern; returns matching path:line entries.', parameters={'type': 'object', 'properties': {'pattern': {'type': 'string', 'description': 'Python regular expression'}, 'subdir': {'type': 'string', 'description': 'Optional subdirectory to limit the search'}}, 'required': ['pattern']}, handler=grep))
    registry.register(AgentTool(name='write_file', description='Create or overwrite a file in the generated project with the given content.', parameters={'type': 'object', 'properties': {'path': {'type': 'string', 'description': 'Path relative to the project root'}, 'content': {'type': 'string', 'description': 'Full file content'}}, 'required': ['path', 'content']}, handler=write_file))
    registry.register(AgentTool(name='delete_path', description='Delete a file or directory from the generated project.', parameters={'type': 'object', 'properties': {'path': {'type': 'string', 'description': 'Path relative to the project root'}}, 'required': ['path']}, handler=delete_path))
    registry.register(AgentTool(name='validate_python', description="Compile-check Python files for syntax errors. Omit 'paths' to check the whole project.", parameters={'type': 'object', 'properties': {'paths': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Optional list of .py paths relative to the project root'}}}, handler=validate_python))
    registry.register(AgentTool(name='django_check', description="Run 'manage.py check' on the generated project if it is a Django project.", parameters={'type': 'object', 'properties': {}}, handler=django_check))
    registry.register(AgentTool(name='run_pytest', description='Run pytest on the generated project (optionally a specific target path).', parameters={'type': 'object', 'properties': {'target': {'type': 'string', 'description': 'Optional test path relative to the project root'}}}, handler=run_pytest))
    return registry