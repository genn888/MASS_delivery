# MiniMax-M2.7 su HPC UNISA con vLLM

Questa guida descrive la configurazione funzionante per servire `MiniMaxAI/MiniMax-M2.7` sul cluster HPC UNISA usando vLLM, con endpoint OpenAI-compatible raggiungibile da MASS.

Risultato ottenuto:

- modello: `MiniMaxAI/MiniMax-M2.7`
- quantizzazione: checkpoint ufficiale FP8/F8_E4M3
- backend: vLLM `0.22.1rc1.dev16+ge9499996d.cu129`
- PyTorch: `2.11.0+cu129`
- GPU: 4 x NVIDIA A100-SXM4 80GB
- partizione: `gpuq`
- account SLURM: `did_tesi_nlp_330`
- nodo testato: `gnode04`
- porta remota: `8004`
- endpoint locale Mac: `http://localhost:8004/v1`
- contesto server testato: `131072` token
- KV cache osservata: `244,576` token
- concorrenza massima osservata per richieste da `131072` token: `1.87x`
- modello locale: `/mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7`
- cache Hugging Face: `/mnt/beegfs/g.dambrosio65/hf_cache`
- cache vLLM: `/mnt/beegfs/g.dambrosio65/vllm_cache`

Nota importante: il modello e le cache devono stare su BeeGFS, non nella home. La home e montata con quota/spazio effettivo di circa `200G`; il modello MiniMax scaricato occupa circa `215G`.

## Setup Da Zero

Questa sezione serve se devi rifare tutto da zero.

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

### 2. Verifica BeeGFS

Controlla i filesystem montati:

```bash
df -h
mount | grep -Ei 'bgfs|beegfs|lustre|gpfs|scratch|work'
```

Nel setup reale il filesystem distribuito e:

```text
/mnt/beegfs
```

Output osservato:

```text
beegfs_nodev    5.4P  105T  5.3P   2% /mnt/beegfs
```

Verifica di poter scrivere:

```bash
whoami
id
ls -ld /mnt/beegfs
touch /mnt/beegfs/test_write_$USER && rm /mnt/beegfs/test_write_$USER
```

### 3. Crea le cartelle su BeeGFS

```bash
export BGFS_ROOT=/mnt/beegfs/g.dambrosio65
mkdir -p "$BGFS_ROOT"/{hf_cache,models,vllm_cache,tmp}
ls -ld "$BGFS_ROOT" "$BGFS_ROOT"/{hf_cache,models,vllm_cache,tmp}
df -h "$BGFS_ROOT"
```

### 4. Crea il venv dedicato

Per non rompere gli ambienti Qwen gia funzionanti, usa un venv separato:

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate
python -m pip install -U virtualenv
python -m virtualenv ~/venvs/vllm-minimax-m27
deactivate

source ~/venvs/vllm-minimax-m27/bin/activate
python -m pip install -U pip uv
python --version
which python
```

### 5. Installa PyTorch CUDA 12.9

```bash
source ~/venvs/vllm-minimax-m27/bin/activate

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

Sul login node `cuda available: False` e normale. La cosa importante e:

```text
torch: 2.11.0+cu129
torch cuda: 12.9
```

### 6. Installa vLLM cu129

Nel setup reale, installare vLLM con indici generici ha portato a una wheel che cercava CUDA 13:

```text
ImportError: libcudart.so.13: cannot open shared object file
```

La soluzione e installare direttamente la wheel vLLM `cu129`:

```bash
source ~/venvs/vllm-minimax-m27/bin/activate

python -m uv pip install -U \
  "https://wheels.vllm.ai/e9499996df8968f473db1f6bc7ec31207022aea0/vllm-0.22.1rc1.dev16%2Bge9499996d.cu129-cp38-abi3-manylinux_2_28_x86_64.whl" \
  --extra-index-url https://download.pytorch.org/whl/cu129
```

Installa anche Hugging Face Hub, Xet e Transformers da Git:

```bash
python -m uv pip install -U huggingface_hub hf_transfer hf-xet \
  git+https://github.com/huggingface/transformers.git
```

Verifica:

```bash
python - <<'PY'
import torch
print("torch:", torch.__version__)
print("torch cuda:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
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

Output buono sul nodo GPU:

```text
torch: 2.11.0+cu129
torch cuda: 12.9
cuda available: True
vllm: 0.22.1rc1.dev16+ge9499996d
vllm._C: ok
```

### 7. Login Hugging Face

Il download senza token puo essere lento o instabile. Usa un token Hugging Face `Read`.

Non incollare token in chat o in file di documentazione. Fai login dal terminale:

```bash
source ~/venvs/vllm-minimax-m27/bin/activate

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

rispondi:

```text
n
```

Output buono:

```text
Token is valid (permission: read).
Login successful.
```

### 8. Scarica MiniMax-M2.7 su BeeGFS

`MiniMaxAI/MiniMax-M2.7` e gia il checkpoint ufficiale FP8/F8_E4M3. Non serve cercare una GGUF Q4/Q5 per questo setup.

```bash
source ~/venvs/vllm-minimax-m27/bin/activate

export BGFS_ROOT=/mnt/beegfs/g.dambrosio65
export HF_HOME="$BGFS_ROOT/hf_cache"
export HUGGINGFACE_HUB_CACHE="$BGFS_ROOT/hf_cache/hub"
unset HF_HUB_ENABLE_HF_TRANSFER
export HF_XET_HIGH_PERFORMANCE=1

hf download MiniMaxAI/MiniMax-M2.7 \
  --local-dir "$BGFS_ROOT/models/MiniMax-M2.7" \
  --max-workers 2
```

Nota: in caso di download interrotto, rilancia lo stesso comando con lo stesso `HF_HOME` e lo stesso `--local-dir`. La progress bar puo sembrare ripartire da zero, ma i file gia completi vengono saltati e i chunk incompleti vengono ripresi quando possibile.

Con file molto grandi, `--max-workers 2` e stato piu stabile di `--max-workers 8`.

### 9. Verifica il download

```bash
du -sh /mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7
find /mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7 -maxdepth 1 -type f | wc -l
find /mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7 -maxdepth 1 -name "model-*.safetensors" | wc -l
find /mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7 -name "*.incomplete" -o -name "*.lock" -o -name "*.part"
ls -lh /mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7 | head -40
```

Output osservato:

```text
215G    /mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7
138
125
```

Il nome degli shard arriva fino a `of-00130`, ma nel setup reale l'indice usa `125` shard. Verifica sempre l'indice:

```bash
cd /mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7

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
index_files: 125
index_missing: 0
index ok
```

### 10. Richiedi 4 A100

La partizione `gpuq` ha limite massimo osservato di `07:00:00`. Se chiedi `08:00:00`, Slurm lascia il job pending con:

```text
(PartitionTimeLimit)
```

Usa:

```bash
srun \
  --partition=gpuq \
  -A did_tesi_nlp_330 \
  --ntasks=1 \
  --cpus-per-task=24 \
  --gres=gpu:a100:4 \
  --time=07:00:00 \
  --pty bash
```

Quando parte, il prompt diventa `gnode...`.

Controlla:

```bash
hostname
echo "$CUDA_VISIBLE_DEVICES"
nvidia-smi
```

Output buono:

```text
gnode04
0,1,2,3
NVIDIA A100-SXM4-80GB
```

### 11. Verifica Python e GPU sul nodo

Sul nodo GPU:

```bash
source ~/venvs/vllm-minimax-m27/bin/activate

export BGFS_ROOT=/mnt/beegfs/g.dambrosio65
export HF_HOME="$BGFS_ROOT/hf_cache"
export HUGGINGFACE_HUB_CACHE="$BGFS_ROOT/hf_cache/hub"
export VLLM_CACHE_ROOT="$BGFS_ROOT/vllm_cache"
export HF_XET_HIGH_PERFORMANCE=1

python - <<'PY'
import torch, vllm, transformers
print("torch:", torch.__version__)
print("torch cuda:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
print("gpu count:", torch.cuda.device_count())
for i in range(torch.cuda.device_count()):
    print(i, torch.cuda.get_device_name(i))
print("vllm:", vllm.__version__)
print("transformers:", transformers.__version__)
PY
```

Output buono:

```text
torch: 2.11.0+cu129
torch cuda: 12.9
cuda available: True
gpu count: 4
0 NVIDIA A100-SXM4-80GB
1 NVIDIA A100-SXM4-80GB
2 NVIDIA A100-SXM4-80GB
3 NVIDIA A100-SXM4-80GB
vllm: 0.22.0 oppure 0.22.1rc1.dev16+ge9499996d
```

### 12. Configura CUDA toolkit

vLLM puo aver bisogno di `nvcc` per compilare kernel durante profiling/warmup. Senza questa configurazione puo fallire con:

```text
Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist
```

Sul nodo GPU:

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

Output buono:

```text
/cm/shared/apps/cuda12.8/toolkit/12.8.0/bin/nvcc
Cuda compilation tools, release 12.8
```

### 13. Avvia vLLM

Sul nodo GPU:

```bash
source ~/venvs/vllm-minimax-m27/bin/activate

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

vllm serve "$BGFS_ROOT/models/MiniMax-M2.7" \
  --host 0.0.0.0 \
  --port 8004 \
  --trust-remote-code \
  --tensor-parallel-size 4 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice \
  --tool-call-parser minimax_m2 \
  --reasoning-parser minimax_m2_append_think \
  --compilation-config '{"cudagraph_mode":"PIECEWISE"}'
```

Il primo avvio puo richiedere diversi minuti: carica circa `215G` da BeeGFS, profila memoria, compila kernel e cattura CUDA graph.

Output buono:

```text
GPU KV cache size: 244,576 tokens
Maximum concurrency for 131,072 tokens per request: 1.87x
Starting vLLM server on http://0.0.0.0:8004
Application startup complete.
```

Nota: il warning seguente non ha bloccato il server:

```text
Auto-initialization of reasoning token IDs failed.
```

## Test Dal Mac

### 1. Apri il tunnel SSH

In un nuovo terminale Mac, sostituendo `gnode04` con il nodo reale:

```bash
ssh -L 8004:gnode04:8004 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

Lascia aperto il terminale del tunnel mentre usi MASS.

### 2. Test endpoint

Da un altro terminale Mac:

```bash
curl http://localhost:8004/v1/models
```

Chat:

```bash
curl http://localhost:8004/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7",
    "messages": [{"role": "user", "content": "Scrivi esattamente: MiniMax operativo ora"}],
    "max_tokens": 80,
    "temperature": 1.0,
    "top_p": 0.95
  }'
```

## Configurazione MASS

Config consigliata:

```text
configs/models_local_minimax_m27_hpc_vllm.yaml
```

Contenuto di base:

```yaml
defaults: &defaults
  provider: openai_compatible
  model: /mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7
  api_key_env: LOCAL_MINIMAX_API_KEY
  base_url: http://localhost:8004/v1
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

Nel file `.env` del progetto MASS:

```bash
LOCAL_MINIMAX_API_KEY=dummy
```

## Uso Rapido Interattivo

Questa e la procedura breve quando il setup e gia pronto e vuoi solo riavviare il server.

### 1. Collegati al login node

```bash
ssh -l g.dambrosio65@studenti.unisa.it lnode.hpc.unisa.it
```

### 2. Controlla job esistenti

```bash
squeue -u "$USER"
```

Se serve fermare un job vecchio:

```bash
scancel JOBID
```

### 3. Richiedi 4 A100

```bash
srun \
  --partition=gpuq \
  -A did_tesi_nlp_330 \
  --ntasks=1 \
  --cpus-per-task=24 \
  --gres=gpu:a100:4 \
  --time=07:00:00 \
  --pty bash
```

Prendi nota del nodo:

```bash
hostname
```

### 4. Avvia vLLM

Sul nodo GPU:

```bash
source ~/venvs/vllm-minimax-m27/bin/activate

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

vllm serve "$BGFS_ROOT/models/MiniMax-M2.7" \
  --host 0.0.0.0 \
  --port 8004 \
  --trust-remote-code \
  --tensor-parallel-size 4 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice \
  --tool-call-parser minimax_m2 \
  --reasoning-parser minimax_m2_append_think \
  --compilation-config '{"cudagraph_mode":"PIECEWISE"}'
```

Lascia aperto questo terminale.

### 5. Apri il tunnel dal Mac

In un terminale Mac, sostituendo `gnode04` con il nodo reale:

```bash
ssh -L 8004:gnode04:8004 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

### 6. Test rapido

Dal Mac:

```bash
curl http://localhost:8004/v1/models
```

## Modalita Batch Con sbatch

Usa `sbatch` se vuoi che il server resti attivo anche chiudendo SSH, il Mac o il terminale.

Con `srun --pty bash`, il processo resta legato al terminale interattivo. Con `sbatch`, invece, Slurm prende in carico il job: quando il nodo GPU viene assegnato, avvia `vllm serve` da solo e lo mantiene attivo fino alla fine del tempo richiesto o fino a `scancel`.

### 1. Crea cartella log

Dal login node:

```bash
mkdir -p ~/mass_vllm_logs
```

### 2. Crea script Slurm

```bash
cat > ~/run_vllm_minimax_m27.sbatch <<'EOF'
#!/usr/bin/env bash
#SBATCH --job-name=mass-vllm-minimax
#SBATCH --partition=gpuq
#SBATCH -A did_tesi_nlp_330
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --gres=gpu:a100:4
#SBATCH --time=07:00:00
#SBATCH --output=/home/G.DAMBROSIO65/mass_vllm_logs/minimax-m27-%j.out
#SBATCH --error=/home/G.DAMBROSIO65/mass_vllm_logs/minimax-m27-%j.err

set -euo pipefail

hostname | tee /home/G.DAMBROSIO65/mass_vllm_minimax_node.txt

source /home/G.DAMBROSIO65/venvs/vllm-minimax-m27/bin/activate

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

vllm serve "$BGFS_ROOT/models/MiniMax-M2.7" \
  --host 0.0.0.0 \
  --port 8004 \
  --trust-remote-code \
  --tensor-parallel-size 4 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice \
  --tool-call-parser minimax_m2 \
  --reasoning-parser minimax_m2_append_think \
  --compilation-config '{"cudagraph_mode":"PIECEWISE"}'
EOF
```

Controlla:

```bash
ls -l ~/run_vllm_minimax_m27.sbatch
```

### 3. Lancia il job

```bash
sbatch ~/run_vllm_minimax_m27.sbatch
```

Output atteso:

```text
Submitted batch job 123456
```

Da questo momento puoi chiudere SSH: il job resta in coda o in esecuzione sul cluster.

### 4. Controlla job e nodo

```bash
squeue -j 123456
```

Quando lo stato e `R`, leggi il nodo:

```bash
cat ~/mass_vllm_minimax_node.txt
```

Oppure:

```bash
squeue -j 123456 -o "%.18i %.2t %.10M %.20N %R"
```

### 5. Segui i log

Sostituisci `123456` con il job reale:

```bash
tail -f ~/mass_vllm_logs/minimax-m27-123456.out
tail -n 120 ~/mass_vllm_logs/minimax-m27-123456.err
```

Aspetta:

```text
Application startup complete.
```

Poi puoi uscire dal `tail` con `Ctrl+C`. Il server resta attivo nel job batch.

### 6. Apri tunnel dal Mac

Con VPN attiva, sostituisci `gnodeXX` con il nodo reale:

```bash
ssh -L 8004:gnodeXX:8004 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

Il tunnel serve solo per usare MASS dal Mac. Se chiudi il tunnel, il server batch sul cluster resta vivo fino alla scadenza del job o a `scancel`.

### 7. Ferma il batch

Dal login node:

```bash
scancel 123456
```

## Come Fermare Tutto

### Modalita interattiva

1. Ferma benchmark/MASS.
2. Nel terminale del tunnel premi `Ctrl+C` o `exit`.
3. Nel terminale vLLM premi `Ctrl+C`.
4. Esci dal job GPU:

   ```bash
   exit
   ```

5. Controlla:

   ```bash
   squeue -u "$USER"
   ```

6. Se serve:

   ```bash
   scancel JOBID
   ```

### Modalita batch

1. Ferma benchmark/MASS.
2. Chiudi il tunnel SSH dal Mac.
3. Cancella il job:

   ```bash
   scancel JOBID
   ```

## Problemi Comuni

### Job pending con PartitionTimeLimit

Sintomo:

```text
(PartitionTimeLimit)
```

Causa: `gpuq` non accetta `--time=08:00:00`.

Soluzione:

```bash
--time=07:00:00
```

### Wheel vLLM cerca CUDA 13

Sintomo:

```text
ImportError: libcudart.so.13: cannot open shared object file
```

Soluzione: installa la wheel diretta `cu129`:

```bash
python -m uv pip uninstall -y vllm
python -m uv pip install -U \
  "https://wheels.vllm.ai/e9499996df8968f473db1f6bc7ec31207022aea0/vllm-0.22.1rc1.dev16%2Bge9499996d.cu129-cp38-abi3-manylinux_2_28_x86_64.whl" \
  --extra-index-url https://download.pytorch.org/whl/cu129
```

### Worker fallisce per nvcc mancante

Sintomo:

```text
Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist
```

Soluzione:

```bash
export CUDA_HOME=/cm/shared/apps/cuda12.8/toolkit/12.8.0
export CUDA_PATH="$CUDA_HOME"
export PATH="$CUDA_HOME/bin:$CUDA_HOME/nvvm/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/targets/x86_64-linux/lib:$CUDA_HOME/nvvm/lib64:${LD_LIBRARY_PATH:-}"
export CPATH="$CUDA_HOME/targets/x86_64-linux/include:${CPATH:-}"
export C_INCLUDE_PATH="$CPATH"
export CPLUS_INCLUDE_PATH="$CPATH"
```

### Download sembra ripartire da zero

Se rilanci:

```bash
hf download MiniMaxAI/MiniMax-M2.7 \
  --local-dir "$BGFS_ROOT/models/MiniMax-M2.7" \
  --max-workers 2
```

la progress bar puo ricominciare da `0`, ma spesso indica solo il totale incompleto della nuova sessione o del file corrente. Controlla lo stato reale con:

```bash
du -sh /mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7
find /mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7 -name "*.incomplete" -o -name "*.lock" -o -name "*.part"
```

### Il tunnel non risponde

Dal Mac:

```bash
curl http://localhost:8004/v1/models
```

Se non risponde:

1. controlla che il job sia ancora vivo:

   ```bash
   squeue -u "$USER"
   ```

2. controlla il nodo reale:

   ```bash
   cat ~/mass_vllm_minimax_node.txt
   ```

3. riapri il tunnel verso il nodo corretto:

   ```bash
   ssh -L 8004:gnodeXX:8004 \
     -l g.dambrosio65@studenti.unisa.it \
     lnode.hpc.unisa.it
   ```

## Promemoria Rapido Riavvio Batch

Questa e la mini guida da usare quando il setup e gia pronto e vuoi riavviare MiniMax senza tenere aperto il terminale SSH.

### 1. Lancia il server dal login node

Dal Mac:

```bash
ssh -l g.dambrosio65@studenti.unisa.it lnode.hpc.unisa.it
```

Sul login node, se lo script non esiste ancora, crealo prima con la sezione "Modalita Batch Con sbatch". Controllo rapido:

```bash
ls -l ~/run_vllm_minimax_m27.sbatch
```

Se ricevi:

```text
No such file or directory
```

devi prima creare lo script `~/run_vllm_minimax_m27.sbatch` usando il blocco della sezione batch sopra.

Se invece lo script esiste, lancialo:

```bash
sbatch ~/run_vllm_minimax_m27.sbatch
```

Output atteso:

```text
Submitted batch job 123456
```

### 2. Controlla quando parte

Sostituisci `123456` con il job reale:

```bash
squeue -j 123456
```

Quando `ST` diventa `R`, leggi il nodo:

```bash
cat ~/mass_vllm_minimax_node.txt
```

Oppure:

```bash
squeue -j 123456 -o "%.18i %.2t %.10M %.20N %R"
```

### 3. Aspetta che vLLM sia pronto

```bash
tail -f ~/mass_vllm_logs/minimax-m27-123456.out
```

Aspetta:

```text
Application startup complete.
```

Poi puoi chiudere `tail` con `Ctrl+C`. Il server resta vivo dentro il job Slurm.

### 4. Apri il tunnel dal Mac

In un terminale Mac, sostituisci `gnodeXX` con il nodo letto prima:

```bash
ssh -L 8004:gnodeXX:8004 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

Lascia aperto solo questo tunnel mentre usi MASS dal Mac. Se chiudi il tunnel, il server sul cluster resta acceso.

### 5. Test rapido dal Mac

```bash
curl http://localhost:8004/v1/models
```

### 6. Usa MASS con MiniMax locale

Config MASS:

```text
configs/models_local_minimax_m27_hpc_vllm.yaml
```

Variabile richiesta in `.env`:

```bash
LOCAL_MINIMAX_API_KEY=dummy
```

### 7. Usa opencode con MiniMax locale

La config globale opencode contiene il provider:

```text
local-minimax
```

Model string:

```text
local-minimax//mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7
```

Smoke test:

```bash
LOCAL_MINIMAX_API_KEY=dummy opencode run \
  --dir /tmp/opencode-local-minimax-smoke \
  --model 'local-minimax//mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7' \
  --dangerously-skip-permissions \
  --format json \
  'Crea un file hello.py che stampa esattamente MiniMax locale ok'
```

### 8. Ferma il server batch

Dal login node:

```bash
scancel 123456
```

squeue -u "$USER"