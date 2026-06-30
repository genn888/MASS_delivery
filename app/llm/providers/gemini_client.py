from __future__ import annotations
import os
import random
import time
from typing import Any, Mapping, Sequence
from app.llm.base_client import BaseLLMClient, ChatMessage, ModelCapabilities, ModelResponse
from app.llm.model_config import RoleModelConfig

class GeminiNativeClient(BaseLLMClient):
    """Google GenAI client for Gemini-compatible models such as Gemma via Gemini API."""

    def __init__(self, config: RoleModelConfig) -> None:
        super().__init__(capabilities=config.capabilities)
        self.config = config
        api_key = self._read_api_key(config)
        try:
            from google import genai
            from google.genai import errors as genai_errors
        except ImportError as exc:
            raise RuntimeError("google-genai is required for provider 'gemini_native'. Install dependencies from requirements.txt.") from exc
        self._client = genai.Client(api_key=api_key)
        self._error_types = (genai_errors.APIError, genai_errors.ClientError, genai_errors.ServerError)

    def generate(self, messages: Sequence[ChatMessage], tools: Sequence[Mapping[str, Any]] | None=None, response_format: Mapping[str, Any] | None=None, temperature: float | None=None, max_tokens: int | None=None, **kwargs: Any) -> ModelResponse:
        if tools:
            raise ValueError('GeminiNativeClient tool calling is not implemented in this project yet.')
        system_instruction, contents = self._split_messages(messages)
        generation_config: dict[str, Any] = {}
        if temperature is not None:
            generation_config['temperature'] = temperature
        elif self.config.temperature is not None:
            generation_config['temperature'] = self.config.temperature
        if max_tokens is not None:
            generation_config['max_output_tokens'] = max_tokens
        elif self.config.max_tokens is not None:
            generation_config['max_output_tokens'] = self.config.max_tokens
        if response_format:
            generation_config['response_mime_type'] = response_format.get('mime_type')
        response = self._generate_with_retry(model=self.config.model, contents=contents, config={**generation_config, **({'system_instruction': system_instruction} if system_instruction else {})}, **kwargs)
        usage = {}
        raw_usage = getattr(response, 'usage_metadata', None)
        if raw_usage is not None:
            usage = {'prompt_token_count': getattr(raw_usage, 'prompt_token_count', None), 'candidates_token_count': getattr(raw_usage, 'candidates_token_count', None), 'total_token_count': getattr(raw_usage, 'total_token_count', None)}
        finish_reason = None
        candidates = getattr(response, 'candidates', None) or []
        if candidates:
            finish_reason = str(getattr(candidates[0], 'finish_reason', None))
        return ModelResponse(text=getattr(response, 'text', '') or '', raw=response, tool_calls=[], finish_reason=finish_reason, usage=usage, model=self.config.model)

    def _generate_with_retry(self, **request_kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._client.models.generate_content(**request_kwargs)
            except self._error_types as exc:
                status_code = getattr(exc, 'status_code', None)
                if status_code not in {429, 500, 503} or attempt == 4:
                    raise
                last_error = exc
                import logging
                logger = logging.getLogger(__name__)
                status_code = getattr(exc, 'status_code', None)
                if status_code == 429:
                    sleep_seconds = 60.0 + random.uniform(0.0, 1.0)
                    logger.warning(f'Rate limited (429) on {self.config.model}. Retrying in {sleep_seconds:.1f}s...')
                else:
                    sleep_seconds = min(20.0, 2 ** attempt + random.uniform(0.0, 1.0))
                    logger.warning(f'API Error ({status_code}) on {self.config.model}. Retrying in {sleep_seconds:.1f}s...')
                time.sleep(sleep_seconds)
        if last_error is not None:
            raise last_error
        raise RuntimeError('Gemini request retry loop exited unexpectedly.')

    @staticmethod
    def _read_api_key(config: RoleModelConfig) -> str:
        if not config.api_key_env:
            raise ValueError(f"Role '{config.role}' with provider 'gemini_native' requires 'api_key_env' in config.")
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing required environment variable '{config.api_key_env}' for role '{config.role}'.")
        return api_key

    @staticmethod
    def _split_messages(messages: Sequence[ChatMessage]) -> tuple[str | None, list[dict[str, str]]]:
        system_parts: list[str] = []
        contents: list[dict[str, str]] = []
        for message in messages:
            if message.role == 'system':
                system_parts.append(message.content)
                continue
            mapped_role = 'model' if message.role == 'assistant' else 'user'
            contents.append({'role': mapped_role, 'parts': [{'text': message.content}]})
        system_instruction = '\n\n'.join(system_parts).strip() or None
        return (system_instruction, contents)