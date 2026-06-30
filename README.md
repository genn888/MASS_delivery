# Multi-Agent Autonomous Software Development v2

This project is a LangGraph-based multi-agent workflow for project-level code generation. The architecture remains model-agnostic: each role receives a normalized LLM client, while provider selection stays in YAML.

## Supported Providers

- `mock`: deterministic fallback for local runs without external APIs
- `gemini_native`: Google GenAI client for Gemini API models such as `gemma-4-31b-it`
- `openai_compatible`: OpenAI-compatible chat completions for providers such as DashScope/Qwen
- `mistral`: thin alias over the OpenAI-compatible path

## Multi-Provider Architecture

The provider layer is split into:

- `app/llm/base_client.py`: common `BaseLLMClient`, normalized `ModelResponse`, message schema, capability flags
- `app/llm/providers/`: concrete provider clients
- `app/llm/model_config.py`: YAML parsing into typed role configs
- `app/llm/registry.py`: provider-to-client resolution
- `app/llm/factory.py`: role validation and client creation

Agents only work with the normalized interface and never depend on provider-specific response shapes.

## Workflow Roles

The active workflow expects these roles:

- `requirement_analyzer`
- `architect`
- `planning_reviewer`
- `coder`
- `coder reviewer`


## Configuration Files

- [`configs/models_example.yaml`](/c:/Users/genna/Desktop/MAS/configs/models_example.yaml): all roles use `mock`
- [`configs/models_production.yaml`](/c:/Users/genna/Desktop/MAS/configs/models_production.yaml): production-oriented split with Gemma for planning/review roles and Qwen for coding
- [`configs/system.yaml`](/c:/Users/genna/Desktop/MAS/configs/system.yaml): iteration limits

## Required Environment Variables

For the production config:

- `GEMINI_API_KEY`
- `DASHSCOPE_API_KEY`

PowerShell examples:

```powershell
$env:GEMINI_API_KEY="your-gemini-key"
$env:DASHSCOPE_API_KEY="your-dashscope-key"
```

The project never hardcodes API keys. If a configured provider requires a key and the corresponding environment variable is missing, initialization fails with an explicit error.

## Install

```bash
pip install -r requirements.txt
```

## Run

Safe local run with mock providers:

```bash
python -m app.main --models-config configs/models_example.yaml --task "Build a CLI TODO app with tests"
```

Run with production provider mapping:

```bash
python -m app.main --models-config configs/models_production.yaml --task "Build a CLI TODO app with tests"
```

Optional flags:

- `--workspace`: workspace root used for artifacts and pytest
- `--models-config`: select a different role/model YAML
- `--system-config`: select a different system YAML

## Change Model Per Role

Edit the role entry in the selected YAML:

```yaml
roles:
  coder:
    provider: openai_compatible
    model: Qwen3-Coder-30B-A3B-Instruct
    api_key_env: DASHSCOPE_API_KEY
    base_url: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
```

You can change:

- `provider`
- `model`
- `api_key_env`
- `base_url`
- `temperature`
- `max_tokens`
- `capabilities`

## Main Files

- [`app/main.py`](/c:/Users/genna/Desktop/MAS/app/main.py): bootstrap and CLI entrypoint
- [`app/graph/builder.py`](/c:/Users/genna/Desktop/MAS/app/graph/builder.py): LangGraph construction and test loop integration
- [`app/llm/base_client.py`](/c:/Users/genna/Desktop/MAS/app/llm/base_client.py): normalized provider interface
- [`app/llm/providers/gemini_client.py`](/c:/Users/genna/Desktop/MAS/app/llm/providers/gemini_client.py): Gemini API integration
- [`app/llm/providers/openai_compatible_client.py`](/c:/Users/genna/Desktop/MAS/app/llm/providers/openai_compatible_client.py): DashScope/OpenAI-compatible integration
- [`app/llm/registry.py`](/c:/Users/genna/Desktop/MAS/app/llm/registry.py): provider registry plus mock fallback

## Notes

- The default startup path can still use the mock config, so the project remains runnable without calling external providers.
- Provider SDK imports are lazy inside the concrete clients, which helps local development and keeps the mock path lightweight.
- Output normalization happens through `ModelResponse`, so agent code only consumes `.text` and can later use usage/tool metadata without provider-specific branching.

## ProjectEval

This repository now includes a ProjectEval adapter runner:

- [`app/benchmark/projecteval_runner.py`](/c:/Users/genna/Desktop/MAS/app/benchmark/projecteval_runner.py)
- [`configs/projecteval_example.yaml`](/c:/Users/genna/Desktop/MAS/configs/projecteval_example.yaml)

It can:

- load ProjectEval tasks from a local clone of the official repository
- run the multi-agent workflow for each selected mission
- export ProjectEval-compatible files into `external/ProjectEval/experiments/...`
- compute a local `Pass@1` proxy from workflow completion
- optionally invoke `run_judge.py` for the official execution-based score

Example:

```bash
python -m app.benchmark.projecteval_runner --config configs/projecteval_example.yaml
```

Direct CLI example:

```bash
python -m app.benchmark.projecteval_runner \
  --projecteval-root external/ProjectEval \
  --models-config configs/models_production.yaml \
  --system-config configs/system.yaml \
  --level 1 \
  --mode direct \
  --project-ids 1,2 \
  --model-label gemini-mas-qwen-coder
```

Official ProjectEval evaluation:

```bash
python -m app.benchmark.projecteval_runner \
  --projecteval-root external/ProjectEval \
  --models-config configs/models_production.yaml \
  --system-config configs/system.yaml \
  --level 1 \
  --mode direct \
  --project-ids 1 \
  --model-label gemini-mas-qwen-coder \
  --run-judge
```

Manual requirement for official `run_judge.py`:

- put a supported browser driver executable such as `chromedriver.exe`, `msedgedriver.exe`, or `geckodriver.exe` in [`external/ProjectEval`](/c:/Users/genna/Desktop/MAS/external/ProjectEval)

Without a driver, the adapter still exports valid experiment files and computes local benchmark summaries, but it skips the official ProjectEval judge.
