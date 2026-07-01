from __future__ import annotations

import os
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

# Env var name -> etichetta mostrata in UI. Solo le chiavi "cloud" che un utente
# che clona la repo deve poter impostare col proprio account (le chiavi dei
# vLLM locali dell'HPC non hanno senso da UI, restano nei configs/*.yaml).
USER_API_KEYS: dict[str, str] = {
    "OPENROUTER_API_KEY": "OpenRouter API key",
    "HF_TOKEN": "Hugging Face token",
}


def _read_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def load_user_keys_into_environ() -> None:
    """Applica al processo Streamlit le chiavi salvate in .env.

    Non sovrascrive variabili già presenti nell'ambiente (es. esportate da
    start_ui.command), così un utente può comunque avere priorità con il
    proprio setup di shell.
    """
    for key, value in _read_env_file().items():
        if value and key not in os.environ:
            os.environ[key] = value


def get_saved_keys() -> dict[str, str]:
    saved = _read_env_file()
    return {key: saved.get(key, "") for key in USER_API_KEYS}


def save_user_key(key: str, value: str) -> None:
    if key not in USER_API_KEYS:
        raise ValueError(f"Chiave sconosciuta: '{key}'")
    value = value.strip()
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    new_lines: list[str] = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}=") or line.strip().startswith(f"{key} ="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)
