from __future__ import annotations
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict

class ProjectServerManager:
    """Gestisce l'esecuzione in background dei server Django per l'anteprima dei progetti."""
    _instance = None
    _lock = threading.Lock()
    _running_servers: Dict[str, subprocess.Popen] = {}
    _server_ports: Dict[str, int] = {}

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ProjectServerManager, cls).__new__(cls)
            return cls._instance

    def find_free_port(self) -> int:
        """Trova una porta libera sul sistema."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
            return port

    def start_server(self, project_id: str, workspace_path: str | Path) -> int:
        """Avvia un server Django per il progetto specificato."""
        if project_id in self._running_servers:
            if self._running_servers[project_id].poll() is None:
                return self._server_ports[project_id]
            else:
                self.stop_server(project_id)
        gen_root = Path(workspace_path) / 'generated_project'
        manage_py = gen_root / 'manage.py'
        if not manage_py.exists():
            raise FileNotFoundError(f'Impossibile trovare manage.py in {gen_root}')
        port = self.find_free_port()
        try:
            subprocess.run([sys.executable, str(manage_py), 'migrate'], cwd=str(gen_root), capture_output=True, text=True, timeout=30)
        except Exception as e:
            print(f'Errore durante il migrate del progetto {project_id}: {e}')
        process = subprocess.Popen([sys.executable, str(manage_py), 'runserver', f'127.0.0.1:{port}', '--noreload'], cwd=str(gen_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        time.sleep(1.5)
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"Il server di anteprima è crashato all'avvio: {stderr}")
        self._running_servers[project_id] = process
        self._server_ports[project_id] = port
        return port

    def stop_server(self, project_id: str):
        """Ferma il server per il progetto specificate."""
        if project_id in self._running_servers:
            proc = self._running_servers[project_id]
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            del self._running_servers[project_id]
            if project_id in self._server_ports:
                del self._server_ports[project_id]

    def is_running(self, project_id: str) -> bool:
        """Verifica se il server per un progetto è attivo."""
        if project_id not in self._running_servers:
            return False
        return self._running_servers[project_id].poll() is None

    def get_port(self, project_id: str) -> int | None:
        """Restituisce la porta su cui gira il progetto."""
        return self._server_ports.get(project_id)