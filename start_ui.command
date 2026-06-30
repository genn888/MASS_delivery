#!/bin/zsh

set -e

cd "$(dirname "$0")"

if [ -f "$HOME/.zshrc" ]; then
  source "$HOME/.zshrc"
fi

if [ -f ".env" ]; then
  set -a
  source ".env"
  set +a
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Ambiente virtuale .venv non trovato."
  echo "Esegui prima: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi

.venv/bin/python -m streamlit run streamlit_app.py --server.port 8501
