from __future__ import annotations
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from app.graph.state import GraphState, append_trace
from app.llm.base_client import BaseLLMClient, ChatMessage, ModelResponse
from app.observability.events import emit_agent_event
from app.tools.agent_tools import ToolRegistry

class BaseAgent(ABC):
    """Common interface and utilities for workflow agents."""
    MAX_TOKENS_GROWTH_FACTOR = 1.6
    MAX_TOKENS_MAX_ESCALATIONS = 3
    MAX_TOKENS_RETRY_BACKOFF_SECONDS = 2
    TOO_SHORT_RESPONSE_MAX_RETRIES = 3
    TOO_SHORT_RESPONSE_RETRY_INTERVAL_SECONDS = 30
    TOO_SHORT_RESPONSE_MAX_COMPLETION_TOKENS = 8
    AGENTIC_LENGTH_EMPTY_MAX_RETRIES = 2
    JSON_PAYLOAD_MAX_RETRIES = 3
    JSON_PAYLOAD_RETRY_INTERVAL_SECONDS = 30
    MAX_TOOL_STEPS = 12
    AGENTIC_STEP_MAX_TOKENS = 32768
    AGENTIC_CONTEXT_COMPACTION = os.getenv('MASS_AGENTIC_CONTEXT_COMPACTION', '0').strip().lower() not in ('0', 'false', 'no', '')

    def __init__(self, llm: BaseLLMClient, prompt_path: Path) -> None:
        self.llm = llm
        self.prompt_path = prompt_path
        self.logger = logging.getLogger(self.__class__.__name__)

    def load_prompt(self) -> str:
        return self.prompt_path.read_text(encoding='utf-8').strip()

    @staticmethod
    def _sanitize_token(value: str) -> str:
        return ''.join((ch if ch.isalnum() or ch in {'-', '_'} else '_' for ch in value))

    def _save_transcript(self, *, state: GraphState, role: str, system_prompt: str, user_prompt: str, response: ModelResponse) -> str | None:
        workspace = state.get('workspace')
        if not workspace:
            return None
        transcript_dir = Path(workspace) / 'artifacts' / 'agent_transcripts'
        transcript_dir.mkdir(parents=True, exist_ok=True)
        trace_index = len(state.get('traces', [])) + 1
        timestamp = time.strftime('%Y%m%d-%H%M%S')
        filename = f'{trace_index:02d}_{timestamp}_{self._sanitize_token(self.__class__.__name__)}_{self._sanitize_token(role)}.json'
        payload = {'timestamp': timestamp, 'agent': self.__class__.__name__, 'role': role, 'prompt_path': str(self.prompt_path), 'provider': getattr(getattr(self.llm, 'config', None), 'provider', None), 'configured_model': getattr(getattr(self.llm, 'config', None), 'model', None), 'resolved_model': response.model, 'system_prompt': system_prompt, 'user_prompt': user_prompt, 'response_text': response.text, 'finish_reason': response.finish_reason, 'usage': response.usage, 'extra': response.extra}
        target_path = transcript_dir / filename
        target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding='utf-8')
        return str(target_path)

    def generate_text(self, *, role: str, system_prompt: str, context: dict[str, Any], response_format: Mapping[str, Any] | None=None) -> str:
        response = self.generate_response(role=role, system_prompt=system_prompt, context=context, response_format=response_format)
        return response.text.strip()

    def generate_text_with_trace(self, *, state: GraphState, role: str, system_prompt: str, context: dict[str, Any], response_format: Mapping[str, Any] | None=None) -> tuple[str, list[dict[str, Any]]]:
        started_at = time.perf_counter()
        user_prompt = self._format_context(role=role, context=context)
        emit_agent_event(state.get('event_callback'), agent_name=self.__class__.__name__, event_type='start', content=f'{role} started', metadata={'role': role, 'context_keys': sorted(context.keys())})
        emit_agent_event(state.get('event_callback'), agent_name=self.__class__.__name__, event_type='prompt', content=user_prompt, metadata={'role': role, 'prompt_path': str(self.prompt_path), 'system_prompt': system_prompt, 'user_prompt': user_prompt, 'context_keys': sorted(context.keys())})
        response = self.generate_response(role=role, system_prompt=system_prompt, context=context, response_format=response_format)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        transcript_path = self._save_transcript(state=state, role=role, system_prompt=system_prompt, user_prompt=user_prompt, response=response)
        trace = {'agent': self.__class__.__name__, 'role': role, 'provider': getattr(getattr(self.llm, 'config', None), 'provider', None), 'model': response.model or getattr(getattr(self.llm, 'config', None), 'model', None), 'prompt_path': str(self.prompt_path), 'transcript_path': transcript_path, 'duration_ms': duration_ms, 'finish_reason': response.finish_reason, 'usage': response.usage, 'response_preview': response.text[:500], 'extra': response.extra}
        emit_agent_event(state.get('event_callback'), agent_name=self.__class__.__name__, event_type='output', content=response.text, metadata={'role': role, 'duration_ms': duration_ms, 'finish_reason': response.finish_reason, 'usage': response.usage, 'extra': response.extra})
        emit_agent_event(state.get('event_callback'), agent_name=self.__class__.__name__, event_type='end', content=f'{role} completed', metadata={'role': role, 'duration_ms': duration_ms, 'finish_reason': response.finish_reason})
        return (response.text.strip(), append_trace(state, trace))

    def generate_response(self, *, role: str, system_prompt: str, context: dict[str, Any], response_format: Mapping[str, Any] | None=None) -> ModelResponse:
        messages = [ChatMessage(role='system', content=system_prompt), ChatMessage(role='user', content=self._format_context(role=role, context=context))]
        return self._invoke_model(messages=messages, response_format=response_format)

    def _invoke_model(self, *, messages: list[ChatMessage], response_format: Mapping[str, Any] | None=None, tools: Sequence[Mapping[str, Any]] | None=None, initial_max_tokens: int | None=None, escalate_on_truncation: bool=True) -> ModelResponse:
        """One model call with empty-response and MAX_TOKENS-escalation retries."""
        attempt = 1
        too_short_attempts = 0
        length_empty_escalations = 0
        max_tokens_escalations = 0
        current_max_tokens: int | None = initial_max_tokens
        retry_nudge: str | None = None
        while True:
            response_messages = messages
            if retry_nudge:
                response_messages = [*messages, ChatMessage(role='user', content=retry_nudge)]
            response = self.llm.generate(messages=response_messages, tools=tools, response_format=response_format, max_tokens=current_max_tokens)
            if not getattr(response, 'tool_calls', None) and self._is_too_short_response(response):
                finish_reason = str(response.finish_reason or '').upper()
                truncated_empty = 'MAX_TOKENS' in finish_reason or finish_reason == 'LENGTH'
                if truncated_empty:
                    if length_empty_escalations >= self.AGENTIC_LENGTH_EMPTY_MAX_RETRIES:
                        usage = response.usage or {}
                        raise RuntimeError(f'{self.__class__.__name__} kept returning an empty response truncated at the output budget after {self.AGENTIC_LENGTH_EMPTY_MAX_RETRIES} budget escalations (finish_reason={response.finish_reason!r}, usage={usage!r}).')
                    base_max_tokens = current_max_tokens or getattr(getattr(self.llm, 'config', None), 'max_tokens', None) or self.AGENTIC_STEP_MAX_TOKENS
                    grown = int(base_max_tokens * self.MAX_TOKENS_GROWTH_FACTOR)
                    context_cap = self.llm.capabilities.max_context
                    if isinstance(context_cap, int) and context_cap > 0:
                        grown = min(grown, context_cap)
                    current_max_tokens = grown
                    length_empty_escalations += 1
                    retry_nudge = 'Your previous attempt used the entire output budget on internal reasoning and was cut off before emitting any visible output or tool call. Stop reasoning now: emit the next tool call (or your final answer) immediately, with at most one short sentence of thought.'
                    self.logger.warning('Agent %s returned an empty response truncated at the output budget; retrying with larger max_tokens=%s and a stop-reasoning nudge (%s/%s).', self.__class__.__name__, current_max_tokens, length_empty_escalations, self.AGENTIC_LENGTH_EMPTY_MAX_RETRIES)
                    attempt += 1
                    continue
                too_short_attempts += 1
                if too_short_attempts > self.TOO_SHORT_RESPONSE_MAX_RETRIES:
                    usage = response.usage or {}
                    raise RuntimeError(f'{self.__class__.__name__} received an empty or too-short response after {self.TOO_SHORT_RESPONSE_MAX_RETRIES} retries (finish_reason={response.finish_reason!r}, usage={usage!r}).')
                retry_nudge = 'The previous completion was empty or too short to use. Regenerate the full response for the original request. Do not acknowledge this retry instruction; return only the requested content.'
                self.logger.warning('Agent %s received an empty or too-short response on attempt %s; retrying in %s seconds (%s/%s).', self.__class__.__name__, attempt, self.TOO_SHORT_RESPONSE_RETRY_INTERVAL_SECONDS, too_short_attempts, self.TOO_SHORT_RESPONSE_MAX_RETRIES)
                attempt += 1
                time.sleep(self.TOO_SHORT_RESPONSE_RETRY_INTERVAL_SECONDS)
                continue
            finish_reason = str(response.finish_reason or '').upper()
            hit_output_limit = 'MAX_TOKENS' in finish_reason or finish_reason == 'LENGTH'
            if not hit_output_limit:
                return response
            if not escalate_on_truncation:
                return response
            base_max_tokens = current_max_tokens or getattr(getattr(self.llm, 'config', None), 'max_tokens', None)
            if base_max_tokens is None:
                return response
            next_max_tokens = int(base_max_tokens * self.MAX_TOKENS_GROWTH_FACTOR)
            context_cap = self.llm.capabilities.max_context
            if isinstance(context_cap, int) and context_cap > 0:
                next_max_tokens = min(next_max_tokens, context_cap)
            if next_max_tokens <= base_max_tokens or max_tokens_escalations >= self.MAX_TOKENS_MAX_ESCALATIONS:
                self.logger.warning('Agent %s hit MAX_TOKENS with output budget at its ceiling (%s) after %s escalation(s); returning the truncated response.', self.__class__.__name__, base_max_tokens, max_tokens_escalations)
                return response
            current_max_tokens = next_max_tokens
            max_tokens_escalations += 1
            attempt += 1
            self.logger.warning('Agent %s hit MAX_TOKENS on attempt %s; retrying with larger max_tokens=%s (escalation %s/%s).', self.__class__.__name__, attempt - 1, current_max_tokens, max_tokens_escalations, self.MAX_TOKENS_MAX_ESCALATIONS)
            time.sleep(self.MAX_TOKENS_RETRY_BACKOFF_SECONDS)

    def run_tool_loop(self, *, state: GraphState, role: str, system_prompt: str, context: dict[str, Any], registry: ToolRegistry, tool_names: Sequence[str] | None=None, max_steps: int | None=None, response_format: Mapping[str, Any] | None=None) -> tuple[str, list[dict[str, Any]]]:
        """Run an agentic ReAct loop: the model calls tools until it returns a final answer."""
        steps = self.MAX_TOOL_STEPS if max_steps is None else max_steps
        tool_schemas = registry.schemas(tool_names)
        user_prompt = self._format_context(role=role, context=context)
        messages: list[ChatMessage] = [ChatMessage(role='system', content=system_prompt), ChatMessage(role='user', content=user_prompt)]
        traces: list[dict[str, Any]] = list(state.get('traces', []))
        callback = state.get('event_callback')
        emit_agent_event(callback, agent_name=self.__class__.__name__, event_type='start', content=f'{role} started (tool loop)', metadata={'role': role, 'tools': list(tool_names or registry.names())})

        def record(response: ModelResponse, *, step: int, duration_ms: float, transcript_path: str | None) -> None:
            calls = [c.get('function', {}).get('name') for c in response.tool_calls or []]
            traces.append({'agent': self.__class__.__name__, 'role': role, 'provider': getattr(getattr(self.llm, 'config', None), 'provider', None), 'model': response.model or getattr(getattr(self.llm, 'config', None), 'model', None), 'prompt_path': str(self.prompt_path), 'transcript_path': transcript_path, 'duration_ms': duration_ms, 'finish_reason': response.finish_reason, 'usage': response.usage, 'response_preview': (response.text or '')[:500], 'tool_step': step, 'tool_calls': calls, 'extra': response.extra})
            emit_agent_event(callback, agent_name=self.__class__.__name__, event_type='output', content=response.text or '', metadata={'role': role, 'step': step, 'tool_calls': calls, 'finish_reason': response.finish_reason})
        final_text = ''
        for step in range(1, steps + 1):
            self._prune_stale_tool_results(messages)
            manifest = self._build_workspace_manifest(messages) if self.AGENTIC_CONTEXT_COMPACTION else ''
            probe_messages = [*messages, ChatMessage(role='user', content=manifest)] if manifest else messages
            started_at = time.perf_counter()
            response = self._invoke_model(messages=probe_messages, response_format=response_format, tools=tool_schemas, initial_max_tokens=self.AGENTIC_STEP_MAX_TOKENS, escalate_on_truncation=False)
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            transcript_path = self._save_transcript(state={**state, 'traces': traces}, role=role, system_prompt=system_prompt, user_prompt=user_prompt if step == 1 else f'[tool-loop step {step}] continued', response=response)
            record(response, step=step, duration_ms=duration_ms, transcript_path=transcript_path)
            tool_calls = list(response.tool_calls or [])
            if not tool_calls:
                final_text = response.text or ''
                break
            messages.append(ChatMessage(role='assistant', content=response.text or '', tool_calls=tool_calls))
            for call in tool_calls:
                fn = call.get('function', {}) or {}
                name = fn.get('name') or ''
                arguments = fn.get('arguments')
                result = registry.execute(name, arguments)
                emit_agent_event(callback, agent_name=self.__class__.__name__, event_type='tool', content=result[:1000], metadata={'role': role, 'step': step, 'tool': name, 'arguments': str(arguments)[:500]})
                messages.append(ChatMessage(role='tool', content=result, tool_call_id=call.get('id'), name=name))
        else:
            self.logger.warning('Agent %s reached the tool-step cap (%s); forcing a final answer.', self.__class__.__name__, steps)
            messages.append(ChatMessage(role='user', content='You have reached the tool-call limit. Stop calling tools and return your final answer now based on what you have already gathered.'))
            response = self._invoke_model(messages=messages, response_format=response_format, initial_max_tokens=self.AGENTIC_STEP_MAX_TOKENS, escalate_on_truncation=False)
            final_text = response.text or ''
            record(response, step=steps + 1, duration_ms=0.0, transcript_path=None)
        emit_agent_event(callback, agent_name=self.__class__.__name__, event_type='end', content=f'{role} completed (tool loop)', metadata={'role': role})
        return (final_text.strip(), traces)
    _ELIDED_TOOL_RESULT = '{"_elided": "superseded read_file result; call read_file again if you still need this file"}'
    _ELIDED_TOOL_OUTPUT = '{"_elided": "superseded tool output; re-run the tool if you still need it"}'
    _ELIDED_WRITE_CONTENT = '<elided: superseded by a later write to this path; call read_file for the current content>'
    _LATEST_ONLY_TOOLS = frozenset({'validate_python', 'django_check', 'run_pytest'})
    _BY_ARGS_TOOLS = frozenset({'grep', 'list_files'})

    @staticmethod
    def _tool_call_path(function: Mapping[str, Any]) -> tuple[str, str | None]:
        """Return (tool_name, path) for an assistant tool_call's ``function`` blob."""
        name = function.get('name') or ''
        arguments = function.get('arguments')
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, ValueError):
                arguments = None
        path = None
        if isinstance(arguments, dict):
            raw = arguments.get('path')
            if isinstance(raw, str) and raw.strip():
                path = raw.strip()
        return (name, path)

    @staticmethod
    def _tool_call_args_str(function: Mapping[str, Any]) -> str:
        """Stable string form of a tool call's arguments, for supersession keying."""
        args = function.get('arguments')
        if isinstance(args, str):
            return args
        try:
            return json.dumps(args, sort_keys=True)
        except (TypeError, ValueError):
            return str(args)

    @classmethod
    def _supersession_key(cls, name: str, function: Mapping[str, Any], path: str | None) -> tuple | None:
        """Key under which a tool *result* is superseded by a later identical-intent call."""
        if name == 'read_file' and path:
            return ('path', path)
        if name in cls._LATEST_ONLY_TOOLS:
            return ('tool', name)
        if name in cls._BY_ARGS_TOOLS:
            return ('args', name, cls._tool_call_args_str(function))
        return None

    @classmethod
    def _elide_write_content(cls, call: dict[str, Any]) -> None:
        """Replace the (full-file) ``content`` in a write_file call's arguments with a stub."""
        fn = call.get('function') or {}
        args = fn.get('arguments')
        parsed: Any
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
            except (json.JSONDecodeError, ValueError):
                return
        elif isinstance(args, dict):
            parsed = dict(args)
        else:
            return
        if isinstance(parsed, dict) and parsed.get('content') not in (None, cls._ELIDED_WRITE_CONTENT):
            parsed['content'] = cls._ELIDED_WRITE_CONTENT
            fn['arguments'] = json.dumps(parsed)
            call['function'] = fn

    @classmethod
    def _prune_stale_tool_results(cls, messages: list[ChatMessage]) -> None:
        """Collapse redundant tool payloads that a later turn has superseded."""
        call_meta: dict[str, tuple[str, int, tuple | None]] = {}
        last_key_index: dict[tuple, int] = {}
        last_write_index: dict[str, int] = {}
        for idx, message in enumerate(messages):
            if message.role != 'assistant' or not message.tool_calls:
                continue
            for call in message.tool_calls:
                fn = call.get('function', {}) or {}
                name, path = cls._tool_call_path(fn)
                key = cls._supersession_key(name, fn, path)
                cid = call.get('id')
                if cid:
                    call_meta[cid] = (name, idx, key)
                if key is not None:
                    last_key_index[key] = idx
                if name == 'write_file' and path:
                    last_write_index[path] = idx
        if cls.AGENTIC_CONTEXT_COMPACTION:
            for idx, message in enumerate(messages):
                if message.role != 'assistant' or not message.tool_calls:
                    continue
                for call in message.tool_calls:
                    name, path = cls._tool_call_path(call.get('function', {}) or {})
                    if name == 'write_file' and path:
                        latest = last_write_index.get(path)
                        if latest is not None and latest > idx:
                            cls._elide_write_content(call)
        for message in messages:
            if message.role != 'tool' or not message.tool_call_id:
                continue
            meta = call_meta.get(message.tool_call_id)
            if not meta:
                continue
            name, call_idx, key = meta
            if key is None:
                continue
            is_read_file = key[0] == 'path'
            if not is_read_file and (not cls.AGENTIC_CONTEXT_COMPACTION):
                continue
            latest = last_key_index.get(key)
            if latest is None or latest <= call_idx:
                continue
            if message.content not in (cls._ELIDED_TOOL_RESULT, cls._ELIDED_TOOL_OUTPUT):
                message.content = cls._ELIDED_TOOL_RESULT if is_read_file else cls._ELIDED_TOOL_OUTPUT

    @classmethod
    def _build_workspace_manifest(cls, messages: list[ChatMessage]) -> str:
        """Compact, refreshed-each-step state note: files written + latest check status."""
        written: list[str] = []
        cid_name: dict[str, str] = {}
        for message in messages:
            if message.role != 'assistant' or not message.tool_calls:
                continue
            for call in message.tool_calls:
                name, path = cls._tool_call_path(call.get('function', {}) or {})
                cid = call.get('id')
                if cid:
                    cid_name[cid] = name
                if name == 'write_file' and path and (path not in written):
                    written.append(path)
        status: str | None = None
        for message in messages:
            if message.role == 'tool' and cid_name.get(message.tool_call_id or '') in cls._LATEST_ONLY_TOOLS and (message.content not in (cls._ELIDED_TOOL_RESULT, cls._ELIDED_TOOL_OUTPUT)):
                tool = cid_name.get(message.tool_call_id or '')
                status = f"latest {tool}: {(message.content or '').strip()[:200]}"
        if not written and (not status):
            return ''
        lines = ['[workspace state — auto-generated summary, not a new user request]']
        if written:
            lines.append('Files written so far (call read_file for current content): ' + ', '.join(written))
        if status:
            lines.append(status)
        return '\n'.join(lines)

    def generate_parsed_payload_with_retries(self, *, state: GraphState, role: str, system_prompt: str, context: dict[str, Any], parser: Callable[[str], Any], response_format: Mapping[str, Any] | None=None, retry_instruction: str | None=None, fallback_factory: Callable[[], Any] | None=None, max_retries: int | None=None) -> tuple[Any, list[dict[str, Any]], str]:
        retries = self.JSON_PAYLOAD_MAX_RETRIES if max_retries is None else max_retries
        base_trace_count = len(state.get('traces', []))
        traces: list[dict[str, Any]] = []
        retry_context = dict(context)
        last_error: Exception | None = None
        last_raw_content = ''
        for attempt in range(retries + 1):
            raw_content, attempt_traces = self.generate_text_with_trace(state=state, role=role, system_prompt=system_prompt, context=retry_context, response_format=response_format)
            last_raw_content = raw_content
            traces.extend(attempt_traces[base_trace_count:])
            try:
                return (parser(raw_content), traces, raw_content)
            except Exception as exc:
                last_error = exc
                if attempt >= retries:
                    break
                self.logger.warning('Generated %s payload was not valid JSON on attempt %s; retrying in %s seconds (%s/%s). Error: %s', role, attempt + 1, self.JSON_PAYLOAD_RETRY_INTERVAL_SECONDS, attempt + 1, retries, exc)
                time.sleep(self.JSON_PAYLOAD_RETRY_INTERVAL_SECONDS)
                retry_context = {**context, 'previous_invalid_response_preview': raw_content[:1200], 'json_retry_instruction': retry_instruction or "The previous response was not a valid JSON object for the requested payload. Regenerate the payload now. The first character of your response must be '{'. Return exactly one JSON object. Do not include analysis, markdown, code fences, or explanatory text outside the JSON."}
        if fallback_factory is not None:
            self.logger.warning('Falling back after %s invalid %s payload attempts. Last error: %s', retries + 1, role, last_error)
            return (fallback_factory(), traces, last_raw_content)
        if last_error is not None:
            raise last_error
        raise ValueError(f'Unable to generate a valid {role} JSON payload.')

    @staticmethod
    def _is_too_short_response(response: ModelResponse) -> bool:
        text = (response.text or '').strip()
        if not text:
            return True
        usage = response.usage or {}
        completion_tokens = usage.get('completion_tokens')
        if isinstance(completion_tokens, int):
            return completion_tokens <= BaseAgent.TOO_SHORT_RESPONSE_MAX_COMPLETION_TOKENS
        return len(text.split()) <= 1

    @staticmethod
    def _format_context(*, role: str, context: dict[str, Any]) -> str:
        lines = [f'role: {role}']
        for key, value in context.items():
            if isinstance(value, (dict, list)):
                serialized = json.dumps(value, indent=2, ensure_ascii=True)
                lines.append(f'{key}: {serialized}')
            else:
                lines.append(f'{key}: {value}')
        return '\n'.join(lines)

    @abstractmethod
    def run(self, state: GraphState) -> GraphState:
        """Run the agent and return a partial state update."""