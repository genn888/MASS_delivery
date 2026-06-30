import json
import logging
import os
import random
import re
import signal
import threading
import time
from contextlib import contextmanager
from typing import Any, Mapping, Sequence
from app.llm.base_client import BaseLLMClient, ChatMessage, ModelResponse
from app.llm.model_config import RoleModelConfig

class OpenAICompatibleClient(BaseLLMClient):
    """Client for OpenAI-compatible chat completion APIs."""

    class EmptyCompletionError(RuntimeError):
        """Raised when the provider returns a completion without usable choices."""

    class HardTimeoutError(TimeoutError):
        """Raised when a provider call exceeds the configured wall-clock timeout."""

    def __init__(self, config: RoleModelConfig) -> None:
        super().__init__(capabilities=config.capabilities)
        self.config = config
        api_key = self._read_api_key(config)
        try:
            from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
        except ImportError as exc:
            raise RuntimeError("openai is required for provider 'openai_compatible'. Install dependencies from requirements.txt.") from exc
        request_timeout_seconds = self._coerce_positive_float(config.extra.get('request_timeout_seconds'), default=600.0)
        client_kwargs: dict[str, Any] = {'api_key': api_key, 'timeout': request_timeout_seconds}
        if config.base_url:
            client_kwargs['base_url'] = config.base_url
        client_kwargs['max_retries'] = 0
        self._client = OpenAI(**client_kwargs)
        self._retryable_errors = (APIConnectionError, APIStatusError, APITimeoutError, RateLimitError, json.JSONDecodeError, self.EmptyCompletionError, self.HardTimeoutError)

    def generate(self, messages: Sequence[ChatMessage], tools: Sequence[Mapping[str, Any]] | None=None, response_format: Mapping[str, Any] | None=None, temperature: float | None=None, max_tokens: int | None=None, **kwargs: Any) -> ModelResponse:
        payload: dict[str, Any] = {'messages': [self._serialize_message(m) for m in messages]}
        provider_preferences = self.config.extra.get('provider_preferences')
        request_kwargs = dict(kwargs)
        extra_body = request_kwargs.get('extra_body')
        if not isinstance(extra_body, dict):
            extra_body = {}
        configured_extra_body = self.config.extra.get('extra_body')
        if isinstance(configured_extra_body, dict):
            extra_body = {**extra_body, **configured_extra_body}
        reasoning = self.config.extra.get('reasoning')
        if isinstance(reasoning, dict) and reasoning:
            extra_body = {**extra_body, 'reasoning': reasoning}
        if isinstance(provider_preferences, dict) and provider_preferences:
            extra_body = {**extra_body, 'provider': provider_preferences}
        if extra_body:
            request_kwargs['extra_body'] = extra_body
        if tools:
            payload['tools'] = list(tools)
        if response_format:
            payload['response_format'] = {key: value for key, value in dict(response_format).items() if key != 'mime_type'}
        if temperature is not None:
            payload['temperature'] = temperature
        elif self.config.temperature is not None:
            payload['temperature'] = self.config.temperature
        requested_max_tokens = max_tokens if max_tokens is not None else self.config.max_tokens
        effective_max_tokens = self._clamp_max_tokens_to_context(requested_max_tokens)
        if effective_max_tokens is not None:
            payload['max_tokens'] = effective_max_tokens
        completion, headers = self._create_completion_with_fallback(payload=payload, **request_kwargs)
        choices = getattr(completion, 'choices', None) or []
        if not choices:
            raise self.EmptyCompletionError('Completion returned without choices after retries/fallback.')
        choice = choices[0]
        message = choice.message
        tool_calls = []
        if getattr(message, 'tool_calls', None):
            tool_calls = [{'id': call.id, 'type': call.type, 'function': {'name': getattr(call.function, 'name', None), 'arguments': getattr(call.function, 'arguments', None)}} for call in message.tool_calls]
        usage = {}
        if getattr(completion, 'usage', None) is not None:
            usage = completion.usage.model_dump()
        actual_model = getattr(completion, 'model', None)
        extra = {}
        if headers.get('x-generation-id'):
            extra['generation_id'] = headers['x-generation-id']
        return ModelResponse(text=self._strip_reasoning_content(message.content or ''), raw=completion, tool_calls=tool_calls, finish_reason=choice.finish_reason, usage=usage, model=actual_model or self.config.model, extra=extra)

    @staticmethod
    def _strip_reasoning_content(text: str) -> str:
        """Remove reasoning blocks that some local OpenAI-compatible servers put in content."""
        if not text:
            return ''
        cleaned = text.strip()
        cleaned = re.sub('(?is)<think\\b[^>]*>.*?</think>\\s*', '', cleaned)
        lowered = cleaned.lower()
        marker = '</think>'
        if marker in lowered:
            marker_index = lowered.rfind(marker)
            cleaned = cleaned[marker_index + len(marker):]
        return cleaned.strip()

    def _create_completion_with_fallback(self, *, payload: dict[str, Any], **kwargs: Any) -> Any:
        requested_model = self.config.model
        fallback_model = str(self.config.extra.get('fallback_model', '')).strip() or None
        max_attempts = max(1, int(self._coerce_positive_float(self.config.extra.get('max_attempts'), default=3)))
        request_timeout_seconds = self._coerce_positive_float(self.config.extra.get('request_timeout_seconds'), default=600.0)
        hard_timeout_seconds = self._coerce_positive_float(self.config.extra.get('hard_timeout_seconds'), default=request_timeout_seconds + 30.0)
        logger = logging.getLogger(__name__)
        candidate_models = [requested_model]
        if fallback_model and fallback_model not in candidate_models:
            candidate_models.append(fallback_model)
        last_error: Exception | None = None
        for model_index, model_name in enumerate(candidate_models):
            for attempt in range(max_attempts):
                try:
                    with self._hard_timeout(hard_timeout_seconds, model_name):
                        response = self._client.chat.completions.with_raw_response.create(model=model_name, **payload, **kwargs)
                    completion = response.parse()
                    gen_id = response.headers.get('x-generation-id')
                    if not (getattr(completion, 'choices', None) or []):
                        raise self.EmptyCompletionError(f"Provider returned no choices for model '{model_name}'.")
                    return (completion, dict(response.headers))
                except self._retryable_errors as exc:
                    if not self._is_retryable(exc):
                        raise
                    last_error = exc
                    is_last_attempt = attempt == max_attempts - 1
                    has_next_model = model_index < len(candidate_models) - 1
                    status_code = getattr(exc, 'status_code', None)
                    response_headers = getattr(getattr(exc, 'response', None), 'headers', {})
                    retry_after = response_headers.get('retry-after')
                    rl_reset = response_headers.get('x-ratelimit-reset')
                    error_name = exc.__class__.__name__
                    if error_name in {'APITimeoutError', 'HardTimeoutError'}:
                        sleep_seconds = min(30.0, 2.0 + attempt + random.uniform(0.0, 1.5))
                        msg = f'⏱️ [Timeout] Richiesta OpenRouter oltre {request_timeout_seconds:.0f}s su {model_name}. Riprovo tra {sleep_seconds:.1f}s.'
                        logger.warning(f'{msg} (tentativo {attempt + 1}/{max_attempts})')
                    elif status_code == 429:
                        if retry_after:
                            try:
                                sleep_seconds = float(retry_after) + random.uniform(0.1, 1.0)
                                msg = f'⏳ [Rate Limit] OpenRouter suggerisce di attendere {sleep_seconds:.1f}s.'
                            except (ValueError, TypeError):
                                sleep_seconds = 90.0
                                msg = f'⏳ [Rate Limit] Header Retry-After non valido. Attesa prudenziale di {sleep_seconds:.1f}s.'
                        elif rl_reset:
                            try:
                                reset_val = float(rl_reset)
                                if reset_val > 1000000000:
                                    sleep_seconds = max(1.0, reset_val - time.time()) + random.uniform(0.5, 1.5)
                                else:
                                    sleep_seconds = reset_val + random.uniform(0.5, 1.5)
                                msg = f'⏳ [Rate Limit] Reset limite tra {sleep_seconds:.1f}s.'
                            except (ValueError, TypeError):
                                sleep_seconds = 90.0
                                msg = f'⏳ [Rate Limit] Header Reset non valido. Attesa prudenziale di {sleep_seconds:.1f}s.'
                        else:
                            sleep_seconds = 90.0 + random.uniform(0.0, 2.0)
                            msg = f'⏳ [Rate Limit] Nessun tempo fornito da OpenRouter. Attesa prudenziale di {sleep_seconds:.1f}s.'
                        logger.warning(f'{msg} (Tentativo {attempt + 1}/{max_attempts})')
                    elif status_code == 504:
                        sleep_seconds = 120.0 + random.uniform(0.0, 5.0)
                        logger.warning(f'⚠️ [504 Gateway Timeout] {model_name} non raggiungibile. Riprovo tra {sleep_seconds:.1f}s (tentativo {attempt + 1}/{max_attempts})...')
                    else:
                        sleep_seconds = min(60.0, 2 ** attempt + random.uniform(0.0, 1.5))
                        logger.warning(f'⚠️ [API Error] Errore {status_code} su {model_name}. Riprovo tra {sleep_seconds:.1f}s (tentativo {attempt + 1}/{max_attempts})...')
                    if is_last_attempt and (not has_next_model):
                        raise
                    if is_last_attempt:
                        logger.info(f'🔄 Passaggio al modello di fallback: {fallback_model}')
                        break
                    time.sleep(sleep_seconds)
        if last_error is not None:
            raise last_error
        raise RuntimeError('OpenAI-compatible completion loop exited unexpectedly.')

    @contextmanager
    def _hard_timeout(self, timeout_seconds: float, model_name: str) -> Any:
        if os.name == 'nt' or timeout_seconds <= 0 or threading.current_thread() is not threading.main_thread():
            yield
            return
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

        def _raise_timeout(signum: int, frame: Any) -> None:
            raise self.HardTimeoutError(f"Provider call exceeded {timeout_seconds:.0f}s for model '{model_name}'.")
        signal.signal(signal.SIGALRM, _raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            if previous_timer[0] > 0:
                signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])
            signal.signal(signal.SIGALRM, previous_handler)

    @staticmethod
    def _serialize_message(message: ChatMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {'role': message.role, 'content': message.content or ''}
        if getattr(message, 'tool_calls', None):
            payload['tool_calls'] = message.tool_calls
        if getattr(message, 'tool_call_id', None):
            payload['tool_call_id'] = message.tool_call_id
        if getattr(message, 'name', None):
            payload['name'] = message.name
        return payload

    def _clamp_max_tokens_to_context(self, max_tokens: int | None) -> int | None:
        if max_tokens is None:
            return None
        max_context = self.capabilities.max_context
        if isinstance(max_context, int) and max_context > 0 and (max_tokens > max_context):
            logging.getLogger(__name__).warning("Clamping max_tokens from %s to max_context=%s for role '%s' (%s).", max_tokens, max_context, self.config.role, self.config.model)
            return max_context
        return max_tokens

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, OpenAICompatibleClient.EmptyCompletionError):
            return True
        status_code = getattr(exc, 'status_code', None)
        return status_code in {408, 409, 429, 500, 502, 503, 504} or status_code is None

    @staticmethod
    def _read_api_key(config: RoleModelConfig) -> str:
        if not config.api_key_env:
            raise ValueError(f"Role '{config.role}' with provider 'openai_compatible' requires 'api_key_env' in config.")
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing required environment variable '{config.api_key_env}' for role '{config.role}'.")
        return api_key

    @staticmethod
    def _coerce_positive_float(value: Any, *, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default