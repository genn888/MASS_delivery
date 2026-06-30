@echo off
cd /d "%~dp0"

if not exist .env type break > .env

if not exist .venv (
  echo === Inizializzazione ambiente Windows ===
  echo Creazione dell'ambiente virtuale (.venv)...
  python -m venv .venv
  echo Installazione delle dipendenze (requirements.txt)...
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  echo Setup completato con successo!
)

echo === Avvio di MAS Control Center ===
.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.port 8501
pause
