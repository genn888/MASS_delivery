# MiniMax-M3 su HPC UNISA con vLLM

Questa guida descrive la configurazione per servire `MiniMaxAI/MiniMax-M3-MXFP8` sul cluster HPC UNISA usando vLLM nightly, con endpoint OpenAI-compatible raggiungibile da MASS.

Differenze rispetto a M2.7:
- modello più grande (~444 GB, M2.7 era 215 GB) → servono **8x A100** invece di 4
- vLLM richiede la **nightly build** (non la stable 0.22.1rc1 usata per M2.7) per il supporto MSA
- flag obbligatorio aggiuntivo: `--block-size 128` (richiesto dall'architettura MSA di M3)
- parser aggiornati: `minimax_m3` invece di `minimax_m2`
- venv separato da M2.7: `vllm-m3-nightly`

Parametri target:

- modello: `MiniMaxAI/MiniMax-M3-MXFP8`
- quantizzazione: MXFP8 ufficiale MiniMax
- backend: vLLM nightly cu129
- GPU: 8 x NVIDIA A100-SXM4 80GB
- partizione: `gpuq`
- account SLURM: `did_tesi_nlp_330`
- porta remota: `8005` (per non collidere con M2.7 su 8004)
- endpoint locale Mac: `http://localhost:8005/v1`
- contesto server: `131072` token (abbassabile a 65536 se la KV cache non basta)
- modello locale: `/mnt/beegfs/g.dambrosio65/models/MiniMax-M3-MXFP8`

---

## Setup Da Zero

### 1. Collegati al cluster

Attiva FortiClient VPN.

Dal Mac:

```bash
ssh -l g.dambrosio65@studenti.unisa.it lnode.hpc.unisa.it
```

Controlla di essere su un login node:

```bash
hostname
```

Output atteso: `lnode01`, `lnode02` o simile.

### 2. Verifica BeeGFS e spazio disponibile

M3-MXFP8 pesa ~444 GB. Controlla che ci sia spazio sufficiente:

```bash
df -h /mnt/beegfs/g.dambrosio65
du -sh /mnt/beegfs/g.dambrosio65/models/
```

Serve almeno ~500 GB liberi (444 GB modello + margine cache).

### 3. Crea il venv dedicato

Usa un venv separato da M2.7 per non rompere il setup funzionante:

```bash
source ~/venvs/vllm-minimax-m27/bin/activate
python -m virtualenv ~/venvs/vllm-m3-nightly
deactivate

source ~/venvs/vllm-m3-nightly/bin/activate
python -m pip install -U pip uv
python --version
which python
```

### 4. Installa PyTorch CUDA 12.9

```bash
source ~/venvs/vllm-m3-nightly/bin/activate

python -m uv pip install torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/cu129
```

Verifica:

```bash
python - <<'PY'
import torch
print("torch:", torch.__version__)
print("torch cuda:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
PY
```

Output atteso sul login node (`cuda available: False` è normale qui):

```text
torch: 2.11.0+cu129
torch cuda: 12.9
```

### 5. Installa vLLM nightly cu129

A differenza di M2.7 (che usa la wheel stabile 0.22.1rc1), M3 richiede la nightly per il supporto all'architettura MSA:

```bash
source ~/venvs/vllm-m3-nightly/bin/activate

python -m uv pip install -U vllm \
  --torch-backend=auto \
  --extra-index-url https://wheels.vllm.ai/nightly \
  --extra-index-url https://download.pytorch.org/whl/cu129
```

Installa anche Hugging Face Hub e Transformers da Git:

```bash
python -m uv pip install -U huggingface_hub hf_transfer hf-xet \
  git+https://github.com/huggingface/transformers.git
```

Verifica:

```bash
python - <<'PY'
import torch
print("torch:", torch.__version__)
try:
    import vllm
    print("vllm:", vllm.__version__)
    import vllm._C
    print("vllm._C: ok")
except Exception as e:
    print("vllm error:", repr(e))
try:
    import transformers
    print("transformers:", transformers.__version__)
except Exception as e:
    print("transformers error:", repr(e))
PY
```

Output buono (versione nightly avrà una stringa tipo `0.x.y.devYYYYMMDD`):

```text
torch: 2.11.0+cu129
vllm: 0.x.y.devYYYYMMDD+ge...
vllm._C: ok
```

### 6. Login Hugging Face

```bash
source ~/venvs/vllm-m3-nightly/bin/activate

export BGFS_ROOT=/mnt/beegfs/g.dambrosio65
export HF_HOME="$BGFS_ROOT/hf_cache"
export HUGGINGFACE_HUB_CACHE="$BGFS_ROOT/hf_cache/hub"

hf auth logout 2>/dev/null || true
hf auth login
```

Quando chiede:

```text
Add token as git credential? [y/N]:
```

rispondi `n`.

Output buono:

```text
Token is valid (permission: read).
Login successful.
```

### 7. Scarica MiniMax-M3-MXFP8 su BeeGFS

Il checkpoint MXFP8 ufficiale pesa ~444 GB. Usa `--max-workers 2` per stabilità:

```bash
source ~/venvs/vllm-m3-nightly/bin/activate

export BGFS_ROOT=/mnt/beegfs/g.dambrosio65
export HF_HOME="$BGFS_ROOT/hf_cache"
export HUGGINGFACE_HUB_CACHE="$BGFS_ROOT/hf_cache/hub"
unset HF_HUB_ENABLE_HF_TRANSFER
export HF_XET_HIGH_PERFORMANCE=1

hf download MiniMaxAI/MiniMax-M3-MXFP8 \
  --local-dir "$BGFS_ROOT/models/MiniMax-M3-MXFP8" \
  --max-workers 2
```

Il download richiederà diverse ore. In caso di interruzione, rilancia lo stesso comando: i file già completi vengono saltati.

### 8. Verifica il download

```bash
du -sh /mnt/beegfs/g.dambrosio65/models/MiniMax-M3-MXFP8
find /mnt/beegfs/g.dambrosio65/models/MiniMax-M3-MXFP8 -name "*.incomplete" -o -name "*.lock" -o -name "*.part"
```

Verifica l'indice dei pesi:

```bash
cd /mnt/beegfs/g.dambrosio65/models/MiniMax-M3-MXFP8

python - <<'PY'
import json
from pathlib import Path
idx = json.loads(Path("model.safetensors.index.json").read_text())
files = sorted(set(idx.get("weight_map", {}).values()))
missing = [f for f in files if not Path(f).exists()]
print("index_files:", len(files))
print("index_missing:", len(missing))
print("\n".join(missing[:20]) if missing else "index ok")
PY
```

Output buono:

```text
index_missing: 0
index ok
```

### 9. Richiedi 8 A100

La partizione `gpuq` ha limite massimo di `07:00:00`. Chiedi 8 GPU:

```bash
srun \
  --partition=gpuq \
  -A did_tesi_nlp_330 \
  --ntasks=1 \
  --cpus-per-task=48 \
  --gres=gpu:a100:8 \
  --time=07:00:00 \
  --pty bash
```

Quando parte, controlla:

```bash
hostname
echo "$CUDA_VISIBLE_DEVICES"
nvidia-smi
```

Output buono:

```text
gnode0X
0,1,2,3,4,5,6,7
NVIDIA A100-SXM4-80GB  (x8)
```

### 10. Verifica Python e GPU sul nodo

```bash
source ~/venvs/vllm-m3-nightly/bin/activate

export BGFS_ROOT=/mnt/beegfs/g.dambrosio65
export HF_HOME="$BGFS_ROOT/hf_cache"
export HUGGINGFACE_HUB_CACHE="$BGFS_ROOT/hf_cache/hub"
export VLLM_CACHE_ROOT="$BGFS_ROOT/vllm_cache"

python - <<'PY'
import torch, vllm, transformers
print("torch:", torch.__version__)
print("cuda available:", torch.cuda.is_available())
print("gpu count:", torch.cuda.device_count())
for i in range(torch.cuda.device_count()):
    print(i, torch.cuda.get_device_name(i))
print("vllm:", vllm.__version__)
PY
```

Output buono:

```text
cuda available: True
gpu count: 8
0 NVIDIA A100-SXM4-80GB
...
7 NVIDIA A100-SXM4-80GB
```

### 11. Configura CUDA toolkit

```bash
export CUDA_HOME=/cm/shared/apps/cuda12.8/toolkit/12.8.0
export CUDA_PATH="$CUDA_HOME"
export PATH="$CUDA_HOME/bin:$CUDA_HOME/nvvm/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/targets/x86_64-linux/lib:$CUDA_HOME/nvvm/lib64:${LD_LIBRARY_PATH:-}"
export CPATH="$CUDA_HOME/targets/x86_64-linux/include:${CPATH:-}"
export C_INCLUDE_PATH="$CPATH"
export CPLUS_INCLUDE_PATH="$CPATH"

which nvcc
nvcc --version
```

### 12. Avvia vLLM

Sul nodo GPU, con 8 A100 e `--tensor-parallel-size 8`.

**Nota critica**: `--block-size 128` è obbligatorio per M3 (richiesto dall'architettura MSA — se omesso vLLM avvia ma le richieste lunghe falliscono silenziosamente).

```bash
source ~/venvs/vllm-m3-nightly/bin/activate

export BGFS_ROOT=/mnt/beegfs/g.dambrosio65
export HF_HOME="$BGFS_ROOT/hf_cache"
export HUGGINGFACE_HUB_CACHE="$BGFS_ROOT/hf_cache/hub"
export VLLM_CACHE_ROOT="$BGFS_ROOT/vllm_cache"
export HF_XET_HIGH_PERFORMANCE=1
export SAFETENSORS_FAST_GPU=1

export CUDA_HOME=/cm/shared/apps/cuda12.8/toolkit/12.8.0
export CUDA_PATH="$CUDA_HOME"
export PATH="$CUDA_HOME/bin:$CUDA_HOME/nvvm/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/targets/x86_64-linux/lib:$CUDA_HOME/nvvm/lib64:${LD_LIBRARY_PATH:-}"
export CPATH="$CUDA_HOME/targets/x86_64-linux/include:${CPATH:-}"
export C_INCLUDE_PATH="$CPATH"
export CPLUS_INCLUDE_PATH="$CPATH"

vllm serve "$BGFS_ROOT/models/MiniMax-M3-MXFP8" \
  --host 0.0.0.0 \
  --port 8005 \
  --trust-remote-code \
  --tensor-parallel-size 8 \
  --block-size 128 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice \
  --tool-call-parser minimax_m3 \
  --reasoning-parser minimax_m3 \
  --compilation-config '{"cudagraph_mode":"PIECEWISE"}'
```

Il primo avvio richiede diversi minuti: carica ~444 GB da BeeGFS, profila memoria, compila kernel MSA e cattura CUDA graph.

Output buono:

```text
Application startup complete.
```

Se la KV cache non è sufficiente a `131072` token, abbassa a `65536`:

```bash
  --max-model-len 65536
```

---

## Test Dal Mac

### 1. Apri il tunnel SSH

In un nuovo terminale Mac (sostituisci `gnodeXX` con il nodo reale):

```bash
ssh -L 8005:gnodeXX:8005 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

### 2. Test endpoint

```bash
curl http://localhost:8005/v1/models
```

Chat:

```bash
curl http://localhost:8005/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/mnt/beegfs/g.dambrosio65/models/MiniMax-M3-MXFP8",
    "messages": [{"role": "user", "content": "Scrivi esattamente: MiniMax M3 operativo"}],
    "max_tokens": 80,
    "temperature": 1.0
  }'
```

---

## Configurazione MASS

Config consigliata:

```text
configs/models_local_minimax_m3_hpc_vllm.yaml
```

Contenuto:

```yaml
defaults: &defaults
  provider: openai_compatible
  model: /mnt/beegfs/g.dambrosio65/models/MiniMax-M3-MXFP8
  api_key_env: LOCAL_MINIMAX_API_KEY
  base_url: http://localhost:8005/v1
  max_tokens: 16384
  temperature: 1.0
  capabilities:
    supports_json: true
    max_context: 131072

roles:
  requirement_analyzer: *defaults
  architect: *defaults
  planning_reviewer: *defaults
  coder:
    <<: *defaults
    max_tokens: 32768
  reviewer: *defaults
  test_writer: *defaults
  browser_test_writer: *defaults
  parameter_solver: *defaults
  parameter_repairer: *defaults
```

Nel file `.env` del progetto MASS (la stessa variabile di M2.7 va bene):

```bash
LOCAL_MINIMAX_API_KEY=dummy
```

---

## Uso Rapido — Modalità Batch (Consigliata)

Con `sbatch` il server resta attivo anche chiudendo il terminale.

### 1. Crea lo script Slurm

Dal login node:

```bash
mkdir -p ~/mass_vllm_logs

cat > ~/run_vllm_minimax_m3.sbatch <<'EOF'
#!/usr/bin/env bash
#SBATCH --job-name=mass-vllm-m3
#SBATCH --partition=gpuq
#SBATCH -A did_tesi_nlp_330
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=48
#SBATCH --gres=gpu:a100:8
#SBATCH --time=07:00:00
#SBATCH --output=/home/G.DAMBROSIO65/mass_vllm_logs/minimax-m3-%j.out
#SBATCH --error=/home/G.DAMBROSIO65/mass_vllm_logs/minimax-m3-%j.err

set -euo pipefail

hostname | tee /home/G.DAMBROSIO65/mass_vllm_m3_node.txt

source /home/G.DAMBROSIO65/venvs/vllm-m3-nightly/bin/activate

export BGFS_ROOT=/mnt/beegfs/g.dambrosio65
export HF_HOME="$BGFS_ROOT/hf_cache"
export HUGGINGFACE_HUB_CACHE="$BGFS_ROOT/hf_cache/hub"
export VLLM_CACHE_ROOT="$BGFS_ROOT/vllm_cache"
export HF_XET_HIGH_PERFORMANCE=1
export SAFETENSORS_FAST_GPU=1

export CUDA_HOME=/cm/shared/apps/cuda12.8/toolkit/12.8.0
export CUDA_PATH="$CUDA_HOME"
export PATH="$CUDA_HOME/bin:$CUDA_HOME/nvvm/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/targets/x86_64-linux/lib:$CUDA_HOME/nvvm/lib64:${LD_LIBRARY_PATH:-}"
export CPATH="$CUDA_HOME/targets/x86_64-linux/include:${CPATH:-}"
export C_INCLUDE_PATH="$CPATH"
export CPLUS_INCLUDE_PATH="$CPATH"

vllm serve "$BGFS_ROOT/models/MiniMax-M3-MXFP8" \
  --host 0.0.0.0 \
  --port 8005 \
  --trust-remote-code \
  --tensor-parallel-size 8 \
  --block-size 128 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice \
  --tool-call-parser minimax_m3 \
  --reasoning-parser minimax_m3 \
  --compilation-config '{"cudagraph_mode":"PIECEWISE"}'
EOF
```

### 2. Lancia il job

```bash
sbatch ~/run_vllm_minimax_m3.sbatch
```

Output atteso:

```text
Submitted batch job 123456
```

### 3. Controlla job e nodo

```bash
squeue -j 123456
```

Quando `ST` diventa `R`:

```bash
cat ~/mass_vllm_m3_node.txt
```

### 4. Segui i log

```bash
tail -f ~/mass_vllm_logs/minimax-m3-123456.out
```

Aspetta:

```text
Application startup complete.
```

### 5. Apri il tunnel dal Mac

```bash
ssh -L 8005:gnodeXX:8005 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

### 6. Test rapido

```bash
curl http://localhost:8005/v1/models
```

### 7. Ferma il server

```bash
scancel 123456
```

---

## Promemoria Rapido Riavvio

Quando il setup è già pronto e vuoi solo riavviare:

```bash
# 1. Login node
ssh -l g.dambrosio65@studenti.unisa.it lnode.hpc.unisa.it

# 2. Lancia job batch
sbatch ~/run_vllm_minimax_m3.sbatch
# prendi nota del job ID

# 3. Aspetta nodo
squeue -j JOBID
cat ~/mass_vllm_m3_node.txt

# 4. Segui log fino a "Application startup complete"
tail -f ~/mass_vllm_logs/minimax-m3-JOBID.out

# 5. Dal Mac: apri tunnel
ssh -L 8005:gnodeXX:8005 -l g.dambrosio65@studenti.unisa.it lnode.hpc.unisa.it

# 6. Test
curl http://localhost:8005/v1/models
```

---

## Problemi Comuni

### KV cache insufficiente

Sintomo: errore all'avvio tipo `KV cache too small` o OOM durante le richieste.

Soluzione: abbassa il contesto massimo:

```bash
--max-model-len 65536
```

### block-size mancante

Sintomo: le richieste con contesti lunghi restituiscono output troncati o vuoti senza errori espliciti.

Causa: M3 usa MSA (sparse attention con block size 128). Senza `--block-size 128` vLLM usa il default (16 o 32) e l'attenzione produce output errati.

Soluzione: aggiungi sempre `--block-size 128`.

### vLLM non trova l'architettura M3

Sintomo:

```text
ValueError: Model architectures ['MiniMaxM3ForCausalLM'] are not supported
```

Causa: stai usando la wheel stabile (0.22.1rc1) invece della nightly.

Soluzione: assicurati di aver attivato il venv corretto:

```bash
source ~/venvs/vllm-m3-nightly/bin/activate
python -c "import vllm; print(vllm.__version__)"
```

Se la versione non ha `dev` nella stringa, reinstalla la nightly:

```bash
python -m uv pip install -U vllm \
  --torch-backend=auto \
  --extra-index-url https://wheels.vllm.ai/nightly \
  --extra-index-url https://download.pytorch.org/whl/cu129
```

### Job pending con PartitionTimeLimit

Stesso problema di M2.7: la partizione `gpuq` non accetta `--time=08:00:00`.

Soluzione: usa sempre `--time=07:00:00`.

### Tunnel non risponde

```bash
# controlla job attivo
squeue -u "$USER"

# leggi nodo
cat ~/mass_vllm_m3_node.txt

# riapri tunnel verso nodo corretto
ssh -L 8005:gnodeXX:8005 -l g.dambrosio65@studenti.unisa.it lnode.hpc.unisa.it
```

### Worker fallisce per nvcc mancante

Stesso fix di M2.7:

```bash
export CUDA_HOME=/cm/shared/apps/cuda12.8/toolkit/12.8.0
export CUDA_PATH="$CUDA_HOME"
export PATH="$CUDA_HOME/bin:$CUDA_HOME/nvvm/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/targets/x86_64-linux/lib:$CUDA_HOME/nvvm/lib64:${LD_LIBRARY_PATH:-}"
```
