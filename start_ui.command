#!/bin/zsh

set -e

cd "$(dirname "$0")"

if [ -f "$HOME/.zshrc" ]; then
  source "$HOME/.zshrc"
fi

if [ ! -f ".env" ]; then
  touch ".env"
fi

if [ -f ".env" ]; then
  set -a
  source ".env"
  set +a
fi

if [ ! -d ".venv" ]; then
  echo "=== Inizializzazione ambiente macOS ==="
  echo "Creazione dell'ambiente virtuale (.venv)..."
  python3 -m venv .venv
  echo "Installazione delle dipendenze (requirements.txt)..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  echo "Setup completato con successo!"
fi

echo "=== Avvio di MAS Control Center ==="
(sleep 2 && open http://localhost:8501) &
.venv/bin/python -m streamlit run streamlit_app.py --server.port 8501 --server.headless true
