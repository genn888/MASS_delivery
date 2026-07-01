# Agent Guide (Specification for AI/Autonomous Agents)

This guide contains technical specifications, system entrypoints, and command executions designed for AI agents executing or integrating the `MASS_delivery` project.

---

## 1. Directory Layout & Core Components
- `app/main.py`: Main CLI entrypoint for running single development tasks.
- `app/benchmark/projecteval_runner.py`: Benchmark adapter to evaluate the workflow.
- `streamlit_app.py`: Streamlit entrypoint for the dashboard.
- `configs/`: Directory containing Role-Model YAML mapping files. OpenRouter configurations use `base_url: https://openrouter.ai/api/v1` and map to `OPENROUTER_API_KEY`.
- `requirements.txt`: Python package dependencies (`langgraph`, `google-genai`, `openai`, `streamlit`, etc.).

---

## 2. Environmental Variables
The codebase relies on python-dotenv to fetch runtime secrets. The following keys must be configured in a `.env` file at the root or exported before runtime:
```bash
OPENROUTER_API_KEY="<your-openrouter-api-token>"
HF_TOKEN="<your-huggingface-token>"
```
*Note: An agent or user running the Streamlit dashboard can save these keys directly via the sidebar expander ("🔑 Le tue chiavi API"), which automatically writes the values to the `.env` file.*

---

## 3. Setup & Activation Commands
To initialize the execution environment manually on macOS (requires Python 3.9+):
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Alternatively, executing the launchers (`start_ui.command` on macOS or `start_ui.bat` on Windows) will automatically trigger environment initialization, package installation, and start the Streamlit service in one step.

---

## 4. CLI Execution Recipes

### A. Running a Multi-Agent Software Development Task via CLI
To invoke the LangGraph agent workflow to solve a software generation request:
```bash
python3 -m app.main \
  --models-config configs/models_openrouter_qwen36plus.yaml \
  --task "Build a Python CLI application for password generation with pytest tests" \
  --workspace "./workspace"
```
**Flags Description**:
- `--models-config`: Path to the YAML model mapping for OpenRouter.
- `--task`: Plain text requirement for the codebase to generate.
- `--workspace`: Path to output generated directories and test results.

### B. Running a ProjectEval Benchmark Task
To execute and evaluate the agent's workflow performance against local mock tests or structured evaluations:
```bash
python3 -m app.benchmark.projecteval_runner \
  --models-config configs/models_openrouter_qwen36plus.yaml \
  --level 1 \
  --mode direct \
  --project-ids 1,2 \
  --model-label gemini-mas-qwen-coder
```
**Expected Output**:
The system runs the workspace code generator on tasks `1` and `2`, runs pytest on the generated folders, and prints the technical final status (e.g. `passed`, `failed_bug`) along with computing local `Pass@1` metrics.

### C. Starting the Streamlit Server
To run the web interface manually for visual testing and monitoring:
```bash
streamlit run streamlit_app.py --server.port 8501
```
