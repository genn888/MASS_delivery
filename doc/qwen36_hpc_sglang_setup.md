# Qwen 3.6 27B su HPC UNISA con SGLang

Questa guida descrive la configurazione funzionante per servire `Qwen/Qwen3.6-27B` su una A100 del cluster HPC UNISA usando SGLang, con endpoint OpenAI-compatible raggiungibile da MASS.

Risultato ottenuto:

- modello: `Qwen/Qwen3.6-27B`
- backend: SGLang
- GPU: NVIDIA A100 80GB
- porta remota: `8002`
- endpoint locale Mac: `http://localhost:8002/v1`
- config MASS: `configs/models_local_qwen36_27b_hpc_sglang.yaml`
- contesto server: `65536` token
- velocita osservata: circa `19 tok/s`, quasi `1.9x` rispetto al server Transformers usato prima

## Setup

Questa sezione serve se devi rifare tutto da zero.

### 1. Connettiti al cluster

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

### 2. Verifica account SLURM

```bash
sacctmgr show assoc user="$USER" format=User%35,Account%35,Partition%20,QOS%100
```

Account tesi usato:

```text
did_tesi_nlp_330
```

Partizione GPU NVIDIA usata:

```text
gpuq
```

Controlla lo stato delle risorse:

```bash
sinfo
```

### 3. Crea le cartelle utente

Sul login node:

```bash
cd ~
mkdir -p ~/tools ~/venvs ~/hf_cache
```

### 4. Installa virtualenv in area utente

Il Python di sistema puo non avere `venv/ensurepip`, quindi usiamo `virtualenv` installato nella home:

```bash
python3 -m pip install --target ~/tools/virtualenv virtualenv
```

### 5. Crea il venv SGLang

```bash
cd ~
PYTHONPATH=~/tools/virtualenv python3 -m virtualenv ~/venvs/sglang-qwen36
source ~/venvs/sglang-qwen36/bin/activate
```

Aggiorna gli strumenti base:

```bash
python -m pip install --upgrade pip uv
```

Installa PyTorch CUDA 12.8:

```bash
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

Installa SGLang:

```bash
uv pip install "sglang[all]" --prerelease=allow
```

Controlla:

```bash
python - <<'PY'
import torch
print("torch:", torch.__version__)
print("torch cuda:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
PY
```

Sul login node `cuda available` puo essere `False`. La cosa importante e che `torch cuda` sia compatibile con CUDA 12.x.

### 6. Scarica Qwen 3.6 27B localmente

Attiva il venv:

```bash
source ~/venvs/sglang-qwen36/bin/activate
```

Installa la CLI Hugging Face:

```bash
python -m pip install -U "huggingface_hub[cli]"
```

Imposta la cache:

```bash
export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub
```

Scarica il modello:

```bash
hf download Qwen/Qwen3.6-27B \
  --local-dir ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --max-workers 4
```

Path locale finale:

```text
/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local
```

Controllo:

```bash
du -sh ~/hf_cache/models--Qwen--Qwen3.6-27B-local
ls ~/hf_cache/models--Qwen--Qwen3.6-27B-local | head
```

### 7. Disabilita il thinking nel template locale

Vai nella cartella del modello:

```bash
cd ~/hf_cache/models--Qwen--Qwen3.6-27B-local
```

Fai backup:

```bash
cp chat_template.jinja chat_template.jinja.bak
```

Aggiungi `enable_thinking=false` in testa al template:

```bash
python - <<'PY'
from pathlib import Path

p = Path("chat_template.jinja")
text = p.read_text()
line = "{%- set enable_thinking = false -%}\n"

if "set enable_thinking = false" not in text:
    p.write_text(line + text)
    print("Added enable_thinking=false at top of chat_template.jinja")
else:
    print("enable_thinking=false already present")
PY
```

Controlla:

```bash
head -5 chat_template.jinja
grep -n "enable_thinking" chat_template.jinja | head -30
```

Output atteso in prima riga:

```jinja
{%- set enable_thinking = false -%}
```

Per ripristinare:

```bash
cp chat_template.jinja.bak chat_template.jinja
```

### 8. Configura CUDA toolkit per i kernel JIT di SGLang

SGLang compila alcuni kernel JIT. Serve il toolkit CUDA completo, non solo il runtime.

Sul cluster abbiamo trovato CUDA 12.8 qui:

```text
/cm/shared/apps/cuda12.8/toolkit/12.8.0
```

Verifica:

```bash
/cm/shared/apps/cuda12.8/toolkit/12.8.0/bin/nvcc --version
find /cm/shared/apps/cuda12.8/toolkit/12.8.0 -name cicc | head
find /cm/shared/apps/cuda12.8/toolkit/12.8.0 -name cuda_runtime.h | head
```

Output atteso:

```text
Cuda compilation tools, release 12.8
/cm/shared/apps/cuda12.8/toolkit/12.8.0/nvvm/bin/cicc
/cm/shared/apps/cuda12.8/toolkit/12.8.0/targets/x86_64-linux/include/cuda_runtime.h
```

Nel setup finale usiamo direttamente questo toolkit reale, non la pseudo CUDA home.

### 9. Richiedi una GPU A100

```bash
srun \
  --partition=gpuq \
  -A did_tesi_nlp_330 \
  --ntasks=1 \
  --cpus-per-task=8 \
  --gpus-per-task=1 \
  --time=02:00:00 \
  --pty bash
```

Quando parte, il prompt diventa `gnode...`.

Controlla:

```bash
hostname
echo "$CUDA_VISIBLE_DEVICES"
nvidia-smi
```

### 10. Avvia SGLang

Sul nodo GPU:

```bash
source ~/venvs/sglang-qwen36/bin/activate

export CUDA_HOME=/cm/shared/apps/cuda12.8/toolkit/12.8.0
export CUDA_PATH="$CUDA_HOME"
export PATH="$CUDA_HOME/bin:$CUDA_HOME/nvvm/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/targets/x86_64-linux/lib:$CUDA_HOME/nvvm/lib64:${LD_LIBRARY_PATH:-}"
export CPATH="$CUDA_HOME/targets/x86_64-linux/include:${CPATH:-}"
export C_INCLUDE_PATH="$CPATH"
export CPLUS_INCLUDE_PATH="$CPATH"

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub
```

Pulisci eventuali kernel JIT falliti:

```bash
rm -rf ~/.cache/tvm-ffi/sgl_kernel_jit_*
```

Avvia il server:

```bash
python -m sglang.launch_server \
  --model-path ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --host 0.0.0.0 \
  --port 8002 \
  --dtype bfloat16 \
  --mem-fraction-static 0.80 \
  --context-length 65536 \
  --attention-backend triton \
  --sampling-backend pytorch \
  --disable-cuda-graph
```

Output buono:

```text
Uvicorn running on http://0.0.0.0:8002
The server is fired up and ready to roll!
```

Nota: `--disable-cuda-graph` e `--sampling-backend pytorch` sono stati usati per evitare crash legati a FlashInfer/CUDA graph. Anche cosi SGLang e risultato quasi 2x piu veloce del server Transformers.

Nota sul contesto: usiamo `--context-length 65536` per permettere agli agenti piu pesanti di mantenere `max_tokens: 32768` senza fallire quando il prompt contiene gia migliaia di token. Con `32768` di contesto, una richiesta tipo `7971` token di input + `32768` token di output viene rifiutata da SGLang con `400 Bad Request`.

### 11. Apri tunnel SSH dal Mac

Se il nodo GPU e, per esempio, `gnode09`, dal Mac:

```bash
ssh -J g.dambrosio65@studenti.unisa.it@lnode.hpc.unisa.it \
  -L 8002:127.0.0.1:8002 \
  g.dambrosio65@studenti.unisa.it@gnode09
```

Lascia aperto questo terminale.

### 12. Test dal Mac

Lista modelli:

```bash
curl http://localhost:8002/v1/models
```

Chat:

```bash
curl http://localhost:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local",
    "messages": [{"role": "user", "content": "Scrivi esattamente: Qwen operativo ora"}],
    "max_tokens": 80
  }'
```

Risposta attesa:

```text
Qwen operativo ora
```

### 13. Configurazione MASS

Nel progetto MASS e stata creata:

```text
configs/models_local_qwen36_27b_hpc_sglang.yaml
```

La config usa:

```yaml
base_url: http://localhost:8002/v1
model: /home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local
api_key_env: LOCAL_QWEN_API_KEY
```

In `.env` deve esserci:

```bash
LOCAL_QWEN_API_KEY=dummy
```






















## Uso

Questa sezione serve quando il setup e gia pronto e devi solo far ripartire il server dopo una nuova connessione SSH o dopo la fine di un job SLURM.

### 1. Collegati al login node

Dal Mac, con VPN attiva:

```bash
ssh -l g.dambrosio65@studenti.unisa.it lnode.hpc.unisa.it
```

### 2. Controlla eventuali job attivi

```bash
squeue -u "$USER"
```

Se c'e un job vecchio da fermare:

```bash
scancel JOBID
```

### 3. Richiedi una GPU

```bash
srun \
  --partition=gpuq \
  -A did_tesi_nlp_330 \
  --ntasks=1 \
  --cpus-per-task=8 \
  --gpus-per-task=1 \
  --time=06:00:00 \
  --pty bash
```

Quando parte, prendi nota del nodo:

```bash
hostname
```

Esempio:

```text
gnode09
```

### 4. Avvia il server SGLang sul nodo GPU

Sul nodo GPU:

```bash
source ~/venvs/sglang-qwen36/bin/activate

export CUDA_HOME=/cm/shared/apps/cuda12.8/toolkit/12.8.0
export CUDA_PATH="$CUDA_HOME"
export PATH="$CUDA_HOME/bin:$CUDA_HOME/nvvm/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/targets/x86_64-linux/lib:$CUDA_HOME/nvvm/lib64:${LD_LIBRARY_PATH:-}"
export CPATH="$CUDA_HOME/targets/x86_64-linux/include:${CPATH:-}"
export C_INCLUDE_PATH="$CPATH"
export CPLUS_INCLUDE_PATH="$CPATH"

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

rm -rf ~/.cache/tvm-ffi/sgl_kernel_jit_*

python -m sglang.launch_server \
  --model-path ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --host 0.0.0.0 \
  --port 8002 \
  --dtype bfloat16 \
  --mem-fraction-static 0.90 \
  --context-length 131072 \
  --attention-backend triton \
  --sampling-backend pytorch \
  --disable-cuda-graph
```

65536

Lascia aperto questo terminale.

### 5. Apri il tunnel dal Mac

In un nuovo terminale Mac, sostituendo `gnode09` con il nodo reale:

```bash
ssh -J g.dambrosio65@studenti.unisa.it@lnode.hpc.unisa.it \
  -L 8002:127.0.0.1:8002 \
  g.dambrosio65@studenti.unisa.it@gnode11
```

Lascia aperto anche questo terminale.

### 6. Test rapido

Dal Mac:

```bash
curl http://localhost:8002/v1/models
```

Poi:

```bash
curl http://localhost:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local",
    "messages": [{"role": "user", "content": "Scrivi esattamente: Qwen operativo ora"}],
    "max_tokens": 80
  }'
```

Se risponde, puoi usare MASS.

### 7. Avvia benchmark MASS

Nel progetto MASS seleziona:

```text
configs/models_local_qwen36_27b_hpc_sglang.yaml
```

Oppure da CLI:

```bash
python -m app.main \
  --models-config configs/models_local_qwen36_27b_hpc_sglang.yaml \
  --task "Build a CLI TODO app with tests"
```

### 8. Cosa deve restare aperto

Per far funzionare MASS servono:

1. VPN FortiClient attiva.
2. Job SLURM attivo su `gpuq`.
3. Terminale con SGLang aperto.
4. Tunnel SSH aperto.
5. MASS aperto sul Mac.

### 9. Come fermare tutto

1. Ferma il benchmark/MASS.
2. Nel terminale del tunnel premi `Ctrl+C` o `exit`.
3. Nel terminale SGLang premi `Ctrl+C`.
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

### 10. Problemi comuni

#### La porta 8002 e occupata

Usa un'altra porta locale nel tunnel, per esempio:

```bash
ssh -J g.dambrosio65@studenti.unisa.it@lnode.hpc.unisa.it \
  -L 8003:127.0.0.1:8002 \
  g.dambrosio65@studenti.unisa.it@gnode09
```

In quel caso MASS deve usare:

```text
http://localhost:8003/v1
```

#### Errore `cicc: not found`

Significa che `PATH` non include `nvvm/bin`.

Correzione:

```bash
export CUDA_HOME=/cm/shared/apps/cuda12.8/toolkit/12.8.0
export PATH="$CUDA_HOME/bin:$CUDA_HOME/nvvm/bin:$PATH"
```

#### Errore `cuda_runtime.h: No such file or directory`

Significa che gli include CUDA non sono visibili.

Correzione:

```bash
export CUDA_HOME=/cm/shared/apps/cuda12.8/toolkit/12.8.0
export CPATH="$CUDA_HOME/targets/x86_64-linux/include:${CPATH:-}"
export C_INCLUDE_PATH="$CPATH"
export CPLUS_INCLUDE_PATH="$CPATH"
```

#### Errore su kernel JIT gia compilati male

Pulisci la cache:

```bash
rm -rf ~/.cache/tvm-ffi/sgl_kernel_jit_*
```

#### SGLang parte ma MASS non risponde

Controlla dal Mac:

```bash
curl http://localhost:8002/v1/models
```

Se non risponde, probabilmente e caduto il tunnel.

Se il tunnel risponde ma MASS no, controlla che la config selezionata sia:

```text
configs/models_local_qwen36_27b_hpc_sglang.yaml
```
