from __future__ import annotations
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any
from app.ui_backend.config_manager import ConfigManager
from app.ui_backend.models import BenchmarkRequest, role_settings_to_dict
from app.ui_backend.session_manager import SessionManager
AGENT_EVENT_STDOUT_PREFIX = '__MASS_AGENT_EVENT__ '

@dataclass
class BenchmarkRunHandle:
    run_id: str
    session_name: str
    request: BenchmarkRequest
    status: str = 'queued'
    started_at: float = field(default_factory=time.time)
    events: Queue[dict[str, Any]] = field(default_factory=Queue)
    event_history: list[dict[str, Any]] = field(default_factory=list)
    thread: threading.Thread | None = None
    returncode: int | None = None
    error: str | None = None
    process_id: int | None = None
    summary: dict[str, Any] | None = None

    def push(self, payload: dict[str, Any]) -> None:
        self.event_history.append(payload)
        self.events.put(payload)

    def get_history(self) -> list[dict[str, Any]]:
        return list(self.event_history)

    def drain_events(self) -> list[dict[str, Any]]:
        drained: list[dict[str, Any]] = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except Empty:
                return drained

class BenchmarkRunner:

    def __init__(self, *, session_manager: SessionManager | None=None, config_manager: ConfigManager | None=None, repo_root: Path | None=None) -> None:
        self.session_manager = session_manager or SessionManager()
        self.config_manager = config_manager or ConfigManager(repo_root=repo_root)
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self._runs: dict[str, BenchmarkRunHandle] = {}
        self._lock = threading.Lock()
        self._result_ingest_interval_seconds = 2.0

    def start(self, request: BenchmarkRequest) -> BenchmarkRunHandle:
        session_dir = self.session_manager.create_session(request.session_name)
        handle = BenchmarkRunHandle(run_id=uuid.uuid4().hex, session_name=request.session_name, request=request)
        with self._lock:
            self._runs[handle.run_id] = handle
        thread = threading.Thread(target=self._run_benchmark_thread, kwargs={'handle': handle, 'session_dir': session_dir}, daemon=True)
        handle.thread = thread
        thread.start()
        return handle

    def get_handle(self, run_id: str) -> BenchmarkRunHandle | None:
        with self._lock:
            return self._runs.get(run_id)

    def get_latest_run_for_session(self, session_name: str) -> BenchmarkRunHandle | None:
        with self._lock:
            matching = [h for h in self._runs.values() if h.session_name == session_name]
            if not matching:
                return None
            return max(matching, key=lambda h: h.started_at)

    def get_any_active_run(self) -> BenchmarkRunHandle | None:
        with self._lock:
            active = [h for h in self._runs.values() if h.status in {'queued', 'running'}]
            if not active:
                return None
            return max(active, key=lambda h: h.started_at)

    def stop(self, run_id: str) -> bool:
        handle = self.get_handle(run_id)
        if not handle or not handle.process_id:
            return False
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(handle.process_id)], check=False, capture_output=True)
            else:
                os.killpg(handle.process_id, signal.SIGTERM)
            handle.status = 'stopped'
            handle.error = "Interrotto dall'utente."
            self.session_manager.record_benchmark_run(handle.session_name, {'run_id': handle.run_id, 'status': 'stopped', 'project_ids': list(handle.request.project_ids), 'stopped_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'request': self.config_manager.benchmark_request_to_config_snapshot(handle.request)})
            return True
        except Exception:
            return False

    def _run_benchmark_thread(self, *, handle: BenchmarkRunHandle, session_dir: Path) -> None:
        request = handle.request
        handle.status = 'running'
        seen_project_snapshots: dict[str, str] = {}
        current_project_id: str | None = None
        models_config_path = self.config_manager.write_session_models_config(session_dir=session_dir, base_models_config_path=request.base_models_config_path, global_model=request.global_model, role_settings=role_settings_to_dict(request.role_settings))
        runner_config_path = self.config_manager.write_runner_config(session_dir=session_dir, request=request, models_config_path=models_config_path)
        self.session_manager.update_session_config(request.session_name, {'status': 'running', 'last_models_config_path': str(models_config_path), 'last_runner_config_path': str(runner_config_path), 'last_system_config_path': request.system_config_path, 'last_level': request.level, 'last_mode': request.mode, 'last_project_ids': list(request.project_ids)})
        self.session_manager.record_benchmark_run(request.session_name, {'run_id': handle.run_id, 'status': 'running', 'project_ids': list(request.project_ids), 'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(handle.started_at)), 'models_config_path': str(models_config_path), 'runner_config_path': str(runner_config_path), 'request': self.config_manager.benchmark_request_to_config_snapshot(request)})
        command = [sys.executable, '-m', 'app.benchmark.projecteval_runner', '--config', str(runner_config_path)]
        process = subprocess.Popen(command, cwd=self.repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=os.name != 'nt')
        handle.process_id = process.pid
        self.session_manager.record_benchmark_run(request.session_name, {'run_id': handle.run_id, 'status': 'running', 'pid': process.pid, 'project_ids': list(request.project_ids)})
        handle.push(self._event('system', 'start', f'Benchmark started with PID {process.pid}.'))
        log_counter = 0
        last_workspace_ingest_at = 0.0
        try:
            assert process.stdout is not None
            for line in process.stdout:
                clean_line = line.rstrip()
                agent_event = self._parse_agent_event_line(clean_line)
                if agent_event is not None:
                    handle.push(agent_event)
                    continue
                handle.push(self._event('benchmark', 'log', clean_line))
                current_project_id, parsed_events = self._parse_log_line(clean_line, current_project_id=current_project_id)
                for event in parsed_events:
                    handle.push(event)
                self.session_manager.append_session_log(request.session_name, 'benchmark', clean_line)
                log_counter += 1
                now = time.monotonic()
                if log_counter % 5 == 0 and now - last_workspace_ingest_at >= self._result_ingest_interval_seconds:
                    self.session_manager.ingest_workspace_results(request.session_name)
                    self._emit_project_status_updates(handle=handle, session_name=request.session_name, seen_project_snapshots=seen_project_snapshots, filter_project_ids=list(request.project_ids))
                    last_workspace_ingest_at = now
            handle.returncode = process.wait()
            self.session_manager.ingest_workspace_results(request.session_name)
            self._emit_project_status_updates(handle=handle, session_name=request.session_name, seen_project_snapshots=seen_project_snapshots, filter_project_ids=list(request.project_ids))
            summary = self._collect_benchmark_summary(request)
            handle.summary = summary
            if handle.status != 'stopped':
                handle.status = 'completed' if process.returncode == 0 else 'error'
            handle.push(self._event('system', 'end' if process.returncode == 0 else 'stopped' if handle.status == 'stopped' else 'error', f'Benchmark finished with return code {process.returncode}.', {'returncode': process.returncode}))
            self.session_manager.record_benchmark_run(request.session_name, {'run_id': handle.run_id, 'status': handle.status, 'project_ids': list(request.project_ids), 'returncode': process.returncode, 'finished_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'summary': summary, 'request': self.config_manager.benchmark_request_to_config_snapshot(request)})
            self.session_manager.update_official_results(request.session_name, mas_report=summary.get('mas_report'), judge_scores=summary.get('judge_scores'), export_dir=summary.get('export_dir'))
            self.session_manager.update_session_config(request.session_name, {'status': 'idle'})
        except Exception as exc:
            handle.error = str(exc)
            handle.status = 'error'
            handle.push(self._event('system', 'error', str(exc)))
            self.session_manager.append_session_log(request.session_name, 'benchmark', f'ERROR: {exc}')
            self.session_manager.update_session_config(request.session_name, {'status': 'error'})

    def _collect_benchmark_summary(self, request: BenchmarkRequest) -> dict[str, Any]:
        experiments_dir = self.repo_root / request.projecteval_root / 'experiments' / request.session_name / request.session_name / request.mode
        mas_reports = sorted(experiments_dir.glob('runs/*/summary/run_summary.json'), key=lambda path: path.stat().st_mtime) if experiments_dir.exists() else []
        mas_report = None
        if mas_reports:
            mas_report = json.loads(mas_reports[-1].read_text(encoding='utf-8'))
        judge_scores: dict[str, Any] = {}
        if isinstance(mas_report, dict):
            judge_scores = mas_report.get('official_scores', {})
        return {'export_dir': str(experiments_dir) if experiments_dir.exists() else None, 'mas_report': mas_report, 'judge_scores': judge_scores}

    def _emit_project_status_updates(self, *, handle: BenchmarkRunHandle, session_name: str, seen_project_snapshots: dict[str, str], filter_project_ids: list[str] | None=None) -> None:
        detail = self.session_manager.get_session_detail(session_name, sync_workspace=False)
        filter_set = set(filter_project_ids) if filter_project_ids else None
        for project in detail.get('projects', []):
            project_id = str(project.get('project_id'))
            if filter_set and project_id not in filter_set:
                continue
            file_count = self._count_generated_files(project)
            trace_count = project.get('trace_count', 0)
            is_placeholder_running_state = project.get('final_status') == 'running' and project.get('test_status') == 'running' and (project.get('validation_status') is None) and (file_count == 0) and (trace_count == 0)
            if is_placeholder_running_state:
                continue
            signature = json.dumps({'final_status': project.get('final_status'), 'test_status': project.get('test_status'), 'validation_status': project.get('validation_status'), 'trace_count': trace_count}, sort_keys=True)
            if seen_project_snapshots.get(project_id) == signature:
                continue
            seen_project_snapshots[project_id] = signature
            content = f"📦 Project {project_id}: final={project.get('final_status')} | test={project.get('test_status')} | validation={project.get('validation_status')} | files={file_count} | traces={trace_count}"
            handle.push(self._event('project', 'project_status', content, {'project_id': project_id, 'final_status': project.get('final_status'), 'test_status': project.get('test_status'), 'validation_status': project.get('validation_status'), 'file_count': file_count, 'trace_count': trace_count}))

    @staticmethod
    def _count_generated_files(project: dict[str, Any]) -> int:
        cached_count = project.get('generated_file_count')
        if isinstance(cached_count, int):
            return cached_count
        workspace = project.get('workspace')
        if not isinstance(workspace, str):
            return 0
        generated_root = Path(workspace) / 'generated_project'
        if not generated_root.exists():
            return 0
        count = 0
        for path in generated_root.rglob('*'):
            if not path.is_file():
                continue
            if '__pycache__' in path.parts:
                continue
            count += 1
        return count

    def _parse_log_line(self, line: str, *, current_project_id: str | None) -> tuple[str | None, list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []
        project_match = re.search('Running (?:\\w+_agent|multi_agent|single_agent)?\\s*workflow for ProjectEval project (\\d+) level (\\d+)', line)
        if project_match:
            project_id, level = project_match.groups()
            events.append(self._event('system', 'milestone', f'🚀 Project {project_id} started (level {level})', {'project_id': project_id, 'level': int(level)}))
            return (project_id, events)
        agent_patterns = [('RequirementAnalyzerAgent \\| Analyzing user requirements', '📋 Requirement analysis'), ('ArchitectAgent \\| Generating architecture plan iteration (\\d+)', '🏗️ Architecture iteration {0}'), ('PlanningReviewerAgent \\| Reviewing architecture plan', '🔎 Planning review'), ('CoderAgent \\| Generating implementation payload iteration (\\d+)', '💻 Coding iteration {0}'), ('ReviewerAgent \\| Reviewer: running', '🧪 Reviewer checking implementation'), ('app\\.graph\\.builder \\| Running workflow finalizer iteration (\\d+)', '📄 Final report iteration {0}'), ('app\\.graph\\.builder \\| Running test loop iteration (\\d+)', '✅ Test loop iteration {0}'), ('TestWriterAgent \\| Generating and running dynamic tests', '📝 Dynamic generated tests'), ('BrowserTestWriterAgent \\| Generating and running Selenium browser tests', '🌐 Selenium browser tests')]
        for pattern, template in agent_patterns:
            match = re.search(pattern, line)
            if match:
                content = template.format(*match.groups()) if match.groups() else template
                events.append(self._event('pipeline', 'milestone', content if current_project_id is None else f'{content} · project {current_project_id}', {'project_id': current_project_id}))
                return (current_project_id, events)
        if '429 Too Many Requests' in line:
            events.append(self._event('rate_limit', 'warning', '⏳ OpenRouter rate limit hit (429)', {'project_id': current_project_id}))
            return (current_project_id, events)
        retry_match = re.search('Retrying request .* in ([0-9.]+) seconds', line)
        if retry_match:
            events.append(self._event('rate_limit', 'retry', f'🔁 Retrying in {retry_match.group(1)}s', {'project_id': current_project_id, 'delay_seconds': float(retry_match.group(1))}))
            return (current_project_id, events)
        return (current_project_id, events)

    @staticmethod
    def _parse_agent_event_line(line: str) -> dict[str, Any] | None:
        line = line.lstrip()
        if not line.startswith(AGENT_EVENT_STDOUT_PREFIX):
            return None
        raw_payload = line[len(AGENT_EVENT_STDOUT_PREFIX):].strip()
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            return {'agent_name': 'agent_event', 'event_type': 'warning', 'content': 'Evento agente non leggibile.', 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'metadata': {'raw': raw_payload[:1000]}}
        if not isinstance(payload, dict):
            return None
        metadata = payload.get('metadata')
        if not isinstance(metadata, dict):
            metadata = {}
        return {'agent_name': str(payload.get('agent_name') or 'agent'), 'event_type': str(payload.get('event_type') or 'event'), 'content': str(payload.get('content') or ''), 'timestamp': str(payload.get('timestamp') or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), 'metadata': metadata}

    @staticmethod
    def _event(agent_name: str, event_type: str, content: str, metadata: dict[str, Any] | None=None) -> dict[str, Any]:
        return {'agent_name': agent_name, 'event_type': event_type, 'content': content, 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'metadata': metadata or {}}