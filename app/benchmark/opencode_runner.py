from __future__ import annotations
import json
import logging
import queue as _queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable
logger = logging.getLogger(__name__)
OPENCODE_DEFAULT_MODEL = 'local-minimax//mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7'
OPENCODE_DEFAULT_CLI_PATH = 'opencode'
OPENCODE_DEFAULT_TIMEOUT_SECONDS = 600
_TOOL_ICONS = {'write': '📝', 'bash': '⚡', 'read': '👁', 'edit': '✏️', 'glob': '🔍', 'grep': '🔎', 'list': '📂', 'patch': '🩹'}

def _tool_label(tool: str, state: dict[str, Any]) -> str:
    icon = _TOOL_ICONS.get(tool, '🔧')
    inp = state.get('input') or {}
    if tool == 'write':
        path = inp.get('filePath') or state.get('title') or ''
        return f'{icon} Write: {path}'
    if tool in {'read', 'glob', 'list'}:
        path = inp.get('filePath') or inp.get('pattern') or inp.get('path') or state.get('title') or ''
        return f'{icon} {tool.capitalize()}: {path}'
    if tool == 'bash':
        cmd = str(inp.get('command') or '')[:120]
        return f'{icon} Bash: {cmd}'
    if tool == 'edit':
        path = inp.get('filePath') or state.get('title') or ''
        return f'{icon} Edit: {path}'
    if tool == 'grep':
        pattern = str(inp.get('pattern') or inp.get('query') or '')[:60]
        return f'{icon} Grep: {pattern}'
    return f"{icon} {tool}: {state.get('title') or ''}"

def export_opencode_session(session_id: str, *, cli_path: str=OPENCODE_DEFAULT_CLI_PATH, artifacts_dir: Path) -> dict[str, Any] | None:
    """Run `opencode export <sessionID>` and save to artifacts_dir/opencode_session_transcript.json."""
    try:
        result = subprocess.run([cli_path, 'export', session_id], capture_output=True, text=True, check=False, timeout=30)
        raw = result.stdout
        json_start = raw.find('{')
        if json_start < 0:
            logger.warning('opencode export produced no JSON for session %s', session_id)
            return None
        transcript = json.loads(raw[json_start:])
        target = artifacts_dir / 'opencode_session_transcript.json'
        target.write_text(json.dumps(transcript, indent=2, ensure_ascii=False), encoding='utf-8')
        logger.info('Saved opencode transcript to %s', target)
        return transcript
    except Exception as exc:
        logger.warning('Failed to export opencode session %s: %s', session_id, exc)
        return None

def build_run_summary(events: list[dict[str, Any]], elapsed: float) -> dict[str, Any]:
    """Build a human-readable summary from the raw parsed event list."""
    files_written: list[str] = []
    files_read: list[str] = []
    bash_commands: list[str] = []
    steps: list[dict[str, Any]] = []
    total_tokens: dict[str, int] = {}
    current_step: int = 0
    for ev in events:
        ev_type = ev.get('type')
        part = ev.get('part') or {}
        if ev_type == 'step_start':
            current_step += 1
        elif ev_type == 'step_finish':
            tokens = part.get('tokens') or {}
            steps.append({'step': current_step, 'reason': part.get('reason', ''), 'tokens': tokens})
            for k, v in tokens.items():
                if isinstance(v, (int, float)):
                    total_tokens[k] = total_tokens.get(k, 0) + int(v)
        elif ev_type == 'tool_use':
            tool = part.get('tool', '')
            state = part.get('state') or {}
            inp = state.get('input') or {}
            if tool == 'write':
                fp = inp.get('filePath') or state.get('title') or ''
                if fp:
                    files_written.append(fp)
            elif tool in {'read', 'glob', 'list'}:
                fp = inp.get('filePath') or inp.get('pattern') or inp.get('path') or ''
                if fp:
                    files_read.append(fp)
            elif tool == 'bash':
                cmd = str(inp.get('command') or '')
                if cmd:
                    bash_commands.append(cmd[:200])
    return {'elapsed_seconds': round(elapsed, 1), 'steps': len(steps), 'total_tokens': total_tokens, 'files_written': files_written, 'files_read': files_read, 'bash_commands': bash_commands, 'step_details': steps}

def run_opencode_for_project(*, prompt: str, generated_project_dir: Path, model: str=OPENCODE_DEFAULT_MODEL, cli_path: str=OPENCODE_DEFAULT_CLI_PATH, timeout_seconds: int=OPENCODE_DEFAULT_TIMEOUT_SECONDS, event_callback: Callable[[dict[str, Any]], None] | None=None) -> dict[str, Any]:
    """Run opencode on a project. Files are written directly into generated_project_dir."""
    generated_project_dir.mkdir(parents=True, exist_ok=True)
    cmd = [cli_path, 'run', '--dir', str(generated_project_dir), '--model', model, '--dangerously-skip-permissions', '--format', 'json', prompt]
    logger.info('OpenCodeRunner | model=%s dir=%s', model, generated_project_dir)

    def _emit(event_type: str, content: str, metadata: dict[str, Any] | None=None) -> None:
        if event_callback is None:
            return
        event_callback({'agent_name': 'OpenCodeAgent', 'event_type': event_type, 'content': content, 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'metadata': metadata or {}})
    _emit('prompt', 'opencode generation started', {'system_prompt': f'opencode autonomous coding agent — model: {model}', 'user_prompt': prompt, 'role': 'coder'})
    start = time.monotonic()
    raw_events: list[dict[str, Any]] = []
    session_id: str | None = None
    step_count = 0
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_q: _queue.Queue[str | None] = _queue.Queue()
        stderr_q: _queue.Queue[str | None] = _queue.Queue()

        def _reader(stream: Any, q: _queue.Queue[str | None]) -> None:
            for ln in stream:
                q.put(ln)
            q.put(None)
        threading.Thread(target=_reader, args=(process.stdout, stdout_q), daemon=True).start()
        threading.Thread(target=_reader, args=(process.stderr, stderr_q), daemon=True).start()
        _HEARTBEAT_INTERVAL = 10.0

        def _drain_stderr() -> None:
            """Forward any pending stderr lines as log events (non-blocking)."""
            while True:
                try:
                    line = stderr_q.get_nowait()
                    if line is None:
                        break
                    line = line.rstrip()
                    if line:
                        _emit('log', f'[opencode stderr] {line}')
                        logger.warning('opencode stderr: %s', line)
                except _queue.Empty:
                    break
        while True:
            _drain_stderr()
            try:
                raw_line = stdout_q.get(timeout=_HEARTBEAT_INTERVAL)
            except _queue.Empty:
                elapsed_so_far = time.monotonic() - start
                _emit('log', f'[opencode] in attesa della risposta del modello... ({elapsed_so_far:.0f}s trascorsi)')
                if elapsed_so_far >= timeout_seconds:
                    process.kill()
                    raise subprocess.TimeoutExpired(cmd, timeout_seconds)
                continue
            if raw_line is None:
                break
            line = raw_line.rstrip()
            if not line or not line.startswith('{'):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                _emit('log', line)
                continue
            raw_events.append(ev)
            ev_type = ev.get('type', '')
            part = ev.get('part') or {}
            if session_id is None:
                session_id = ev.get('sessionID') or part.get('sessionID')
            if ev_type == 'step_start':
                step_count += 1
                _emit('log', f'[step {step_count}] started')
            elif ev_type == 'text':
                text = part.get('text', '').strip()
                if text:
                    snippet = text[:300].replace('\n', ' ')
                    _emit('log', f'[model] {snippet}')
                    logger.info('opencode model text: %s', snippet[:120])
            elif ev_type == 'tool_use':
                tool = part.get('tool', '')
                state = part.get('state') or {}
                label = _tool_label(tool, state)
                status = state.get('status', '')
                out = str(state.get('output') or '')[:200]
                log_line = f'[tool] {label}' + (f' → {out}' if out and status == 'completed' else '')
                _emit('log', log_line)
                logger.info('opencode tool: %s', label)
            elif ev_type == 'step_finish':
                tokens = part.get('tokens') or {}
                reason = part.get('reason', '')
                total = tokens.get('total', 0)
                _emit('log', f'[step {step_count}] finished — reason={reason} tokens={total}')
        elapsed = time.monotonic() - start
        remaining = max(1.0, timeout_seconds - elapsed)
        returncode = process.wait(timeout=remaining)
        run_summary = build_run_summary(raw_events, elapsed)
        _drain_stderr()
        if returncode != 0:
            remaining_stderr: list[str] = []
            while True:
                try:
                    line = stderr_q.get_nowait()
                    if line is None:
                        break
                    remaining_stderr.append(line.rstrip())
                except _queue.Empty:
                    break
            error_msg = '\n'.join(remaining_stderr)[:2000]
            _emit('output', f'opencode exited with code {returncode}.\n{error_msg}', {'finish_reason': 'error', 'duration_ms': int(elapsed * 1000)})
            _emit('end', 'opencode generation failed', {'finish_reason': 'error', 'duration_ms': int(elapsed * 1000)})
            return {'status': 'error', 'returncode': returncode, 'elapsed_seconds': elapsed, 'error': error_msg, 'session_id': session_id, 'raw_events': raw_events, 'run_summary': run_summary}
        summary_text = f"opencode completed in {elapsed:.1f}s — {run_summary['steps']} steps, {len(run_summary['files_written'])} files written, tokens: {run_summary['total_tokens'].get('total', '?')}"
        _emit('output', summary_text, {'finish_reason': 'stop', 'duration_ms': int(elapsed * 1000), 'usage': run_summary['total_tokens']})
        _emit('end', 'opencode generation completed', {'finish_reason': 'stop', 'duration_ms': int(elapsed * 1000)})
        return {'status': 'ok', 'returncode': 0, 'elapsed_seconds': elapsed, 'session_id': session_id, 'raw_events': raw_events, 'run_summary': run_summary}
    except subprocess.TimeoutExpired:
        process.kill()
        elapsed = time.monotonic() - start
        run_summary = build_run_summary(raw_events, elapsed)
        msg = f'opencode timed out after {timeout_seconds}s'
        _emit('output', msg, {'finish_reason': 'timeout', 'duration_ms': int(elapsed * 1000)})
        _emit('end', msg, {'finish_reason': 'timeout', 'duration_ms': int(elapsed * 1000)})
        return {'status': 'timeout', 'elapsed_seconds': elapsed, 'error': msg, 'session_id': session_id, 'raw_events': raw_events, 'run_summary': run_summary}
    except Exception as exc:
        elapsed = time.monotonic() - start
        run_summary = build_run_summary(raw_events, elapsed)
        _emit('output', str(exc), {'finish_reason': 'error', 'duration_ms': int(elapsed * 1000)})
        return {'status': 'error', 'elapsed_seconds': elapsed, 'error': str(exc), 'session_id': session_id, 'raw_events': raw_events, 'run_summary': run_summary}