# Project Organization Guide

This document provides a comprehensive overview of the MASS (Multi-Agent Software System) project structure and the purpose of its various components.

## Directory Structure

### 📂 `app/`
The core logic of the system is contained here.
- **`agents/`**: Contains the definition of the LLM agents (Architect, Coder, Reviewer, etc.). Each agent inherits from `BaseAgent`.
- **`graph/`**: Implementation of the workflow using LangGraph.
  - `builder.py`: Defines the nodes and edges of the execution graph.
  - `routing.py`: Logic for conditional transitions between nodes.
  - `state.py`: Definition of the shared state (`GraphState`).
- **`benchmark/`**: Tools and scripts for running benchmarks.
  - `projecteval_runner.py`: The main script to execute benchmarks on the ProjectEval dataset.
- **`validation/`**: Static validation logic that doesn't necessarily use LLMs.
  - `web_benchmark_validator.py`: Specific logic for validating web projects.
  - `batch_benchmark_validator.py`: Logic for validating batch/script-based projects.
- **`llm/`**: LLM client wrappers and factory logic.
- **`prompts/`**: Centralized location for the system prompts of all agents.
- **`tools/`**: Utilities and tools available to agents (e.g., `FileTool`).
- **`observability/`**: Internal event emission and monitoring logic.

### 📂 `sessions/`
Stores the results, logs, and workspaces for different benchmark or execution sessions.
- Each subdirectory (e.g., `gpt5.4nano_2`) represents a specific run.
- Contains `results.json` (summary of all projects) and `logs/` (detailed execution logs).

### 📂 `configs/`
YAML configuration files for models and system-wide settings.
- `models_*.yaml`: Configuration for different LLM providers and models.
- `system.yaml`: General system parameters (e.g., iteration limits).

### 📂 `external/`
Place for external repositories or large datasets.
- **`ProjectEval/`**: The external benchmark dataset and its internal tools.

### 📂 `pages/`
Streamlit UI pages for the dashboard.
- `1_Chat.py`: Interactive chat interface.
- `2_Benchmark.py`: Interface to start and monitor benchmarks.
- `3_Sessioni.py`: View history of sessions.
- `4_Dettaglio_Sessione.py`: Deep dive into a specific session's results.

### 📂 `tests/`
Automated tests for the MASS system itself.

### 📂 `doc/`
Documentation files providing detailed guides on the system.
- `file_organization.md`: This guide.
- `workflow.md`: Detailed description of the LangGraph execution flow.
- `agent_*.md`: Individual files for each agent (Requirement Analyzer, Architect, etc.), including Parameter Solver and Repairer.
- `validator_static.md`: Documentation on the deterministic validation system.
- `gpt5.4nano_2_results.md`: Analysis of the specific benchmark session.
- `workflow_diagram.puml` & `sequence_diagram.puml`: PlantUML sources for system visualization.

## Root Files
- `streamlit_app.py`: Entrypoint for the Streamlit dashboard.
- `manager.py`: Utility script for project management tasks.
- `requirements.txt`: Python dependencies.
- `start_ui.command`: Launcher script for macOS.
