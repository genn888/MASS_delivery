# 🚀 MASS: Multi-Agent Sequential System (v2.0)

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Streamlit App](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat&logo=Streamlit&logoColor=white)](https://streamlit.io/)
[![Orchestration](https://img.shields.io/badge/LangGraph-orange?style=flat)](https://github.com/langchain-ai/langgraph)

An advanced, model-agnostic multi-agent code generation platform built on top of **LangGraph**. MASS automates the entire software engineering lifecycle—from requirement analysis and architectural planning to iterative coding, dynamic test validation, and quality review.

Featuring a premium **Streamlit Control Center** for interactive chat and automated benchmarking, MASS is optimized for execution on macOS and Windows with zero configuration (Note: This interface is designed specifically for research and experimental purposes, and is not yet ready for production deployment).

---

## 🌟 Key Features

*   **🧠 Multi-Agent Collaboration Loop**: Coordinates specialized agents (`Requirement Analyzer`, `Architect`, `Planning Reviewer`, `Coder`, `Test Writer`, and `Quality Reviewer`) inside an iterative LangGraph state machine.
*   **💻 Premium Web Interface**: A sleek, dark-themed Streamlit dashboard containing interactive Chat workspaces, persistent session history, and Benchmark run controls.
*   **⚡ Zero-Config Launchers**: Platform-specific double-click launchers (`start_ui.command` / `Start UI.app` for macOS and `start_ui.bat` for Windows) that automatically create virtual environments, install dependencies, and launch the web interface.
*   **🔑 Local API Keys Expander**: A secure sidebar manager in the Web UI to persist `OPENROUTER_API_KEY` and `HF_TOKEN` locally in `.env` (gitignored) without manual file editing.
*   **📈 ProjectEval Benchmark Adapter**: A direct executor interface to run, monitor, and assess agentic performance against execution-based benchmarks with automated Pass@1 proxy scoring.

---

## 📂 Repository Layout

```text
├── app/
│   ├── main.py                      # CLI entrypoint for single development tasks
│   ├── workflow.py                  # LangGraph state machine bootstrap
│   ├── agents/                      # Specialized agent prompt nodes
│   ├── graph/                       # Graph construction and compiler state
│   ├── llm/                         # Normalized LLM client abstraction layer
│   ├── benchmark/                   # ProjectEval runner and evaluator adapters
│   └── ui_backend/                  # Streamlit layouts, theme configurations, and key storage
├── configs/                         # YAML mapping for model selection and limits
├── pages/                           # Streamlit subpages (Chat, Benchmark, Sessions)
├── streamlit_app.py                 # Main Streamlit dashboard entrypoint
├── USER_GUIDE.md                    # Detailed User Guide (Italian)
├── AGENT_GUIDE.md                   # Agent Integration Specification (English)
├── start_ui.command                 # macOS automatic setup and launcher script
├── start_ui.bat                     # Windows automatic setup and launcher script
└── Start UI.app                     # macOS double-click app wrapper
```

---

## 🚀 Quick Start (Zero-Config)

MASS automatically manages its virtual environment and dependencies. You do not need to install python packages globally.

### 🍏 On macOS
1. Open the project folder in Finder.
2. Double-click the **`Start UI.app`** or **`start_ui.command`**.
   *(Note: If macOS displays a permissions error, run `chmod +x start_ui.command` in the Terminal once).*

### 🔌 On Windows
1. Double-click **`start_ui.bat`**.

*During the first run, the scripts will create a `.venv` directory, install all required packages from `requirements.txt` (takes ~30s), and automatically open your default browser to `http://localhost:8501`.*

---

## 🔑 Credentials Configuration

MASS requires external API keys to query cloud models. You can configure them in two ways:

1.  **Via the Web Interface (Recommended)**:
    Open the Streamlit app sidebar, click on the **🔑 Le tue chiavi API** expander, type your `OPENROUTER_API_KEY` and/or `HF_TOKEN`, and click **Salva chiavi**. They will be saved to your local `.env` file automatically.
2.  **Manually**:
    Create a `.env` file at the root of the project:
    ```env
    OPENROUTER_API_KEY=your_openrouter_key_here
    HF_TOKEN=your_huggingface_token_here
    ```

---

## 🛠️ CLI Usage Recipes

Before running CLI commands, ensure your virtual environment is active:
```bash
source .venv/bin/activate
```

### A. Run a Code Generation Task via CLI
```bash
python3 -m app.main \
  --models-config configs/models_openrouter_qwen36plus.yaml \
  --task "Build a Python CLI password manager with pytest tests" \
  --workspace "./workspace"
```

### B. Run a ProjectEval Benchmark
```bash
python3 -m app.benchmark.projecteval_runner \
  --models-config configs/models_openrouter_qwen36plus.yaml \
  --level 1 \
  --mode direct \
  --project-ids 1,2 \
  --model-label gemini-mas-qwen-coder
```

---

## 📘 Documentation

For detailed instructions, refer to:
*   📖 **[USER_GUIDE.md](./USER_GUIDE.md)**: Manuale utente in lingua italiana per la configurazione dei modelli e l'uso dell'interfaccia grafica.
*   🤖 **[AGENT_GUIDE.md](./AGENT_GUIDE.md)**: Technical integration recipes and developer schemas for AI/autonomous agents.
