from __future__ import annotations
import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any
from app.observability.events import AgentEvent, emit_agent_event
from app.ui_backend.session_manager import SessionManager
from app.workflow import run_workflow

@dataclass
class WorkflowRunHandle:
    run_id: str
    session_name: str
    workspace: Path
    status: str = 'queued'
    events: Queue[dict[str, Any]] = field(default_factory=Queue)
    final_state: dict[str, Any] | None = None
    error: str | None = None
    thread: threading.Thread | None = None

    def push(self, event: AgentEvent) -> None:
        self.events.put(event.to_dict())

    def drain_events(self) -> list[dict[str, Any]]:
        drained: list[dict[str, Any]] = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except Empty:
                return drained
_RUNS: dict[str, WorkflowRunHandle] = {}
_LOCK = threading.Lock()

class AgentRunner:

    def __init__(self, session_manager: SessionManager | None=None) -> None:
        self.session_manager = session_manager or SessionManager()

    def start_chat_run(self, *, session_name: str, user_task: str, models_config_path: str, system_config_path: str, initial_overrides: dict[str, Any] | None=None) -> WorkflowRunHandle:
        session_dir = self.session_manager.create_session(session_name)
        run_id = uuid.uuid4().hex
        workspace = session_dir / 'chat_runs' / run_id
        workspace.mkdir(parents=True, exist_ok=True)
        handle = WorkflowRunHandle(run_id=run_id, session_name=session_name, workspace=workspace)
        with _LOCK:
            _RUNS[run_id] = handle
        thread = threading.Thread(target=self._run_workflow_thread, kwargs={'handle': handle, 'user_task': user_task, 'models_config_path': models_config_path, 'system_config_path': system_config_path, 'initial_overrides': initial_overrides or {}}, daemon=True)
        handle.thread = thread
        thread.start()
        return handle

    def get_handle(self, run_id: str) -> WorkflowRunHandle | None:
        with _LOCK:
            return _RUNS.get(run_id)

    def _run_workflow_thread(self, *, handle: WorkflowRunHandle, user_task: str, models_config_path: str, system_config_path: str, initial_overrides: dict[str, Any]) -> None:
        handle.status = 'running'
        emit_agent_event(handle.push, agent_name='system', event_type='start', content='Workflow chat run started.', metadata={'run_id': handle.run_id, 'workspace': str(handle.workspace)})
        try:
            overrides = dict(initial_overrides)
            overrides['event_callback'] = handle.push
            final_state = run_workflow(user_task=user_task, workspace=handle.workspace, models_config_path=models_config_path, system_config_path=system_config_path, initial_overrides=overrides)
            handle.final_state = final_state
            handle.status = 'completed'
            safe_state = self._sanitize_payload(final_state)
            (handle.workspace / 'final_state.json').write_text(json.dumps(safe_state, indent=2), encoding='utf-8')
            emit_agent_event(handle.push, agent_name='system', event_type='end', content='Workflow chat run completed.', metadata={'final_status': final_state.get('final_status')})
            self.session_manager.record_chat_run(handle.session_name, {'run_id': handle.run_id, 'user_task': user_task, 'workspace': str(handle.workspace), 'final_status': final_state.get('final_status'), 'test_status': final_state.get('test_status'), 'final_output_path': final_state.get('final_output_path'), 'implementation_summary': final_state.get('implementation_summary')})
        except Exception as exc:
            handle.error = str(exc)
            handle.status = 'error'
            emit_agent_event(handle.push, agent_name='system', event_type='error', content=str(exc), metadata={'run_id': handle.run_id})

    def _sanitize_payload(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                if key == 'event_callback':
                    continue
                sanitized[key] = self._sanitize_payload(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_payload(item) for item in value]
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)
            self.session_manager.record_chat_run(handle.session_name, {'run_id': handle.run_id, 'user_task': user_task, 'workspace': str(handle.workspace), 'final_status': 'error', 'error': str(exc)})