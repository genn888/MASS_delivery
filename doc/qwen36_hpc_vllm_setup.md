# Qwen 3.6 27B su HPC UNISA con vLLM

Questa guida descrive la configurazione funzionante per servire `Qwen/Qwen3.6-27B` su una A100 del cluster HPC UNISA usando vLLM, con endpoint OpenAI-compatible raggiungibile da MASS.

Risultato ottenuto:

- modello: `Qwen/Qwen3.6-27B`
- backend: vLLM `0.20.1`
- PyTorch: `2.11.0+cu129`
- GPU: NVIDIA A100-SXM4 80GB
- dtype: `bfloat16`
- porta remota: `8003`
- endpoint locale Mac: `http://localhost:8003/v1`
- config MASS: `configs/models_local_qwen36_27b_hpc_vllm.yaml`
- contesto server testato: `32768` token
- JSON mode MASS: abilitato con `supports_json: true`

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

### 2. Crea cartelle utente

```bash
cd ~
mkdir -p ~/tools ~/venvs ~/hf_cache ~/src
```

### 3. Prepara virtualenv

Il Python di sistema puo non avere `venv/ensurepip`. Se hai gia un ambiente funzionante, per esempio `sglang-qwen36`, usalo per creare un nuovo virtualenv senza toccare SGLang:

```bash
source ~/venvs/sglang-qwen36/bin/activate
python -m pip install -U virtualenv
python -m virtualenv ~/venvs/vllm-qwen36-cu129
deactivate
```

Se invece parti davvero da zero e non hai ancora `virtualenv`:

```bash
python3 -m pip install --target ~/tools/virtualenv virtualenv
PYTHONPATH=~/tools/virtualenv python3 -m virtualenv ~/venvs/vllm-qwen36-cu129
```

Attiva il nuovo ambiente:

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate
python -m pip install -U pip uv
```

### 4. Installa PyTorch CUDA e vLLM

Installa PyTorch CUDA 12.9:

```bash
uv pip install torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/cu129
```

Installa la wheel vLLM CUDA 12.9 esatta:

```bash
uv pip install \
  "https://github.com/vllm-project/vllm/releases/download/v0.20.1/vllm-0.20.1+cu129-cp38-abi3-manylinux_2_31_x86_64.whl"
```

Aggiorna Transformers:

```bash
uv pip install -U git+https://github.com/huggingface/transformers.git
```

Verifica sul login node:

```bash
python - <<'PY'
import torch, transformers, vllm
print("torch:", torch.__version__)
print("cuda:", torch.version.cuda)
print("cuda_available:", torch.cuda.is_available())
print("transformers:", transformers.__version__)
print("vllm:", vllm.__version__)
PY
```

Output buono sul login node:

```text
torch: 2.11.0+cu129
cuda: 12.9
cuda_available: False
vllm: 0.20.1
```

`cuda_available: False` sul login node e normale. La cosa importante e che non sia ROCm e che `torch.version.cuda` sia `12.9`.

### 5. Scarica Qwen 3.6 27B

Se lo hai gia scaricato per SGLang/Transformers, salta questo punto.

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate
python -m pip install -U "huggingface_hub[cli]"

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

hf download Qwen/Qwen3.6-27B \
  --local-dir ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --max-workers 4
```

Path locale finale:

```text
/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local
```

### 6. Richiedi una GPU A100

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

Quando parte, il prompt diventa `gnode...`.

Controlla:

```bash
hostname
nvidia-smi
```

### 7. Verifica vLLM sul nodo GPU

Sul nodo GPU:

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

python - <<'PY'
import torch, vllm
print("cuda_available:", torch.cuda.is_available())
print("gpu:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
print("torch cuda:", torch.version.cuda)
print("vllm:", vllm.__version__)
PY
```

Output buono:

```text
cuda_available: True
gpu: NVIDIA A100-SXM4-80GB
torch cuda: 12.9
vllm: 0.20.1
```

### 8. Avvia vLLM

> **Tool-calling (function calling).** I flag `--enable-auto-tool-choice` e
> `--tool-call-parser qwen3_coder` abilitano il function calling OpenAI-style, necessario
> per gli agenti che usano tool. Qwen 3.6 emette le chiamate in formato XML
> (`<tool_call><function=name><parameter=x>val</parameter></function></tool_call>`): il
> parser corretto è **`qwen3_coder`**. NON usare `hermes`: non aggancia questo formato e
> l'API restituisce `tool_calls: []` (fallimento silenzioso). Validato end-to-end il 2026-06-10.
> Se non ti serve il tool-calling puoi omettere quei due flag.

Sul nodo GPU:

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

vllm serve ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --host 0.0.0.0 \
  --port 8003 \
  --dtype bfloat16 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --language-model-only
```

Output buono:

```text
Resolved architecture: Qwen3_5ForConditionalGeneration
Using max model len 32768
Model loading took 50.22 GiB memory
GPU KV cache size: 262,872 tokens
Maximum concurrency for 32,768 tokens per request: 8.02x
Starting vLLM server on http://0.0.0.0:8003
Application startup complete.
```

Nota: al primo avvio vLLM compila e cattura CUDA graphs. Sul nostro test l'inizializzazione ha impiegato alcuni minuti, ma gli avvii successivi possono riusare cache in `~/.cache/vllm`.

### 9. Apri il tunnel SSH dal Mac

Se il nodo GPU e, per esempio, `gnode02`, dal Mac:

```bash
ssh -L 8003:gnode02:8003 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

Lascia aperto questo terminale.

### 10. Test dal Mac

Lista modelli:

```bash
curl http://localhost:8003/v1/models
```

Chat:

```bash
curl http://localhost:8003/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local",
    "messages": [{"role": "user", "content": "Scrivi esattamente: Qwen operativo ora"}],
    "max_tokens": 80,
    "temperature": 0.6,
    "top_p": 0.95
  }'
```

Risposta attesa:

```text
Qwen operativo ora
```

### 11. Configurazione MASS

Nel progetto MASS e stata creata:

```text
configs/models_local_qwen36_27b_hpc_vllm.yaml
```

La config usa:

```yaml
base_url: http://localhost:8003/v1
model: /home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local
api_key_env: LOCAL_QWEN_API_KEY
supports_json: true
```

Nel file `.env` del progetto MASS deve esserci:

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
gnode02
```

### 4. Avvia il server vLLM sul nodo GPU

Sul nodo GPU:

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

vllm serve ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --host 0.0.0.0 \
  --port 8003 \
  --dtype bfloat16 \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.90 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --language-model-only
```

Lascia aperto questo terminale.

### 5. Apri il tunnel dal Mac

In un nuovo terminale Mac, sostituendo `gnode02` con il nodo reale:

```bash
ssh -L 8003:gnode12:8003 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

Lascia aperto anche questo terminale.

### 6. Test rapido

Dal Mac:

```bash
curl http://localhost:8003/v1/models
```

Poi:

```bash
curl http://localhost:8003/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local",
    "messages": [{"role": "user", "content": "Scrivi esattamente: Qwen operativo ora"}],
    "max_tokens": 80,
    "temperature": 0.6,
    "top_p": 0.95
  }'
```

Se risponde, puoi usare MASS.

### 7. Avvia MASS con la config vLLM

Nel progetto MASS seleziona:

```text
configs/models_local_qwen36_27b_hpc_vllm.yaml
```

Oppure da CLI:

```bash
python -m app.main \
  --models-config configs/models_local_qwen36_27b_hpc_vllm.yaml \
  --task "Build a CLI TODO app with tests"
```

### 8. Avvia benchmark ProjectEval

Esempio:

```bash
python -m app.benchmark.projecteval_runner \
  --models-config configs/models_local_qwen36_27b_hpc_vllm.yaml \
  --system-config configs/system.yaml \
  --projecteval-root external/ProjectEval \
  --archive-root benchmark_archives/projecteval \
  --level 2 \
  --mode direct \
  --project-ids 1
```

Se usi la UI Streamlit di MASS, seleziona la config vLLM nel campo della models config.

### 9. Modalita batch manuale senza terminale vLLM aperto

Se vuoi che il server resti attivo per le 6 ore del job anche chiudendo SSH, il Mac o il terminale, usa `sbatch` invece di `srun --pty bash`.

Con `srun --pty bash`, il processo resta legato al terminale interattivo. Con `sbatch`, invece, Slurm prende in carico il job: quando il nodo GPU viene assegnato, avvia `vllm serve` da solo e lo mantiene attivo fino alla fine del tempo richiesto o fino a `scancel`.

Procedura passo passo, partendo dal prompt del login node:

```text
g.dambrosio65@studenti.unisa.it@lnode02:~$
```

#### 9.1. Crea la cartella dei log

```bash
mkdir -p ~/mass_vllm_logs
```

#### 9.2. Crea lo script Slurm

```bash
cat > ~/run_vllm_qwen36.sbatch <<'EOF'
#!/usr/bin/env bash
#SBATCH --job-name=mass-vllm-qwen36
#SBATCH --partition=gpuq
#SBATCH -A did_tesi_nlp_330
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus-per-task=1
#SBATCH --time=06:00:00
#SBATCH --output=/home/G.DAMBROSIO65/mass_vllm_logs/vllm-%j.out
#SBATCH --error=/home/G.DAMBROSIO65/mass_vllm_logs/vllm-%j.err

set -euo pipefail

hostname | tee ~/mass_vllm_node.txt

source ~/venvs/vllm-qwen36-cu129/bin/activate

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

vllm serve ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --host 0.0.0.0 \
  --port 8003 \
  --dtype bfloat16 \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.90 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --language-model-only
EOF
```

Controlla che lo script esista:

```bash
ls -l ~/run_vllm_qwen36.sbatch
```

#### 9.3. Lancia il job

```bash
sbatch ~/run_vllm_qwen36.sbatch
```

Output atteso:

```text
Submitted batch job 123456
```

Prendi nota del numero del job. Negli esempi sotto useremo `123456`, ma devi sostituirlo con il tuo `JOBID` reale.

Da questo momento puoi chiudere il terminale SSH: il job resta in coda o in esecuzione sul centro di calcolo.

#### 9.4. Controlla se il job e partito

```bash
squeue -j 123456
```

Se nella colonna `ST` vedi `PD`, il job e ancora in coda. Se vedi `R`, il job e in esecuzione.

Esempio buono:

```text
             JOBID PARTITION     NAME     USER ST       TIME  NODES NODELIST(REASON)
            486737      gpuq mass-vll g.dambro  R       0:27      1 gnode04
```

In questo esempio il nodo GPU e `gnode04`.

#### 9.5. Leggi il nodo GPU assegnato

Quando il job parte, lo script salva il nodo in:

```bash
cat ~/mass_vllm_node.txt
```

Output atteso:

```text
gnode04
```

Puoi anche leggerlo direttamente da Slurm:

```bash
squeue -j 123456 -o "%.18i %.2t %.10M %.20N %R"
```

#### 9.6. Segui il log finche vLLM e pronto

```bash
tail -f ~/mass_vllm_logs/vllm-486737.out
tail -n 120 ~/mass_vllm_logs/vllm-486737.err

```

Aspetta finche nel log compare una riga simile a:

```text
Application startup complete.
```

A quel punto il server vLLM e pronto. Puoi uscire dal `tail` con `Ctrl+C`.

#### 9.7. Apri il tunnel dal Mac

Questo comando va lanciato in un terminale del Mac, non dentro SSH.

Con VPN attiva, sostituisci `gnodeXX` con il nodo reale letto prima:

```bash
ssh -L 8003:gnode04:8003 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

Esempio, se Slurm ha assegnato `gnode04`:

```bash
ssh -L 8003:gnode09:8003 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

Lascia aperto il terminale del tunnel mentre usi MASS.

#### 9.8. Test dal Mac

In un altro terminale del Mac:

```bash
curl http://localhost:8003/v1/models
```

Se risponde, MASS puo usare:

```text
http://localhost:8003/v1
```

Il tunnel serve solo quando vuoi usare MASS dal Mac. Se spegni il Mac o chiudi il tunnel, il job batch e il server vLLM sul centro di calcolo restano attivi. Quando riaccendi il Mac, riapri VPN e tunnel verso lo stesso nodo, se il job e ancora entro le 6 ore.

#### 9.9. Ferma il server prima delle 6 ore

Dal login node, sostituendo `123456` con il tuo `JOBID`:

```bash
scancel 123456
```

### 10. Cosa deve restare aperto

Per far funzionare MASS servono:

1. VPN FortiClient attiva.
2. Job SLURM attivo su `gpuq`.
3. Server `vllm serve` attivo:
   - in modalita interattiva, il terminale vLLM deve restare aperto;
   - in modalita batch manuale con `sbatch`, il terminale vLLM non serve perche il processo vive dentro il job Slurm.
4. Tunnel SSH aperto sul Mac.
5. MASS aperto sul Mac.

### 11. Come fermare tutto

1. Ferma il benchmark/MASS.
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

### 12. Note per test larghi

La config `models_local_qwen36_27b_hpc_vllm.yaml` e coerente con il server avviato a `--max-model-len 32768`.

Se vuoi provare contesti piu larghi, riavvia vLLM aumentando:

```bash
--max-model-len 65536
```

oppure:

```bash
--max-model-len 131072
```

Poi va creata una config MASS separata con `max_context` e `max_tokens` coerenti. Non usare una config wide se il server e partito con `--max-model-len 32768`.

## 13. Variante partizione `aiq` (GPU H100/SM90) + contesto 262144

La partizione `gpuq` assegna A100-80GB (SM80). La partizione `aiq` assegna invece GPU
**H100 (SM90)**, e questo cambia tre cose rispetto al setup standard. Validato il 2026-06-20:
il modello `Qwen3.6-27B` e' **ibrido (layer Mamba)** e il suo contesto nativo e' **262144**
(`max_position_embeddings: 262144`, `rope_type: default` -> niente YaRN fino a 262k).

Tre accorgimenti necessari su `aiq`/H100:

1. **`--max-num-seqs 256`** — a 262144 di contesto la VRAM lascia pochi "Mamba cache blocks"
   (ognuno serve a una sequenza in decode). Il default `max_num_seqs=1024` supera i blocchi
   disponibili e la cattura dei CUDA graph fallisce con
   `ValueError: max_num_seqs (1024) exceeds available Mamba cache blocks`. Abbassare a 256
   (per MASS la concorrenza e' minima) risolve.
2. **`export VLLM_USE_DEEP_GEMM=0`** — su H100 vLLM tenta i kernel FP8 DeepGEMM, non
   installati, e muore con `RuntimeError: DeepGEMM backend is not available`. Il modello e'
   in bf16, DeepGEMM non serve: disabilitarlo. (Il warning `Could not find nvcc` sul kernel
   flashinfer GDN SM90 e' invece innocuo: fa fallback.)
3. **`#SBATCH --partition=aiq`** al posto di `gpuq`. Verifica prima con `sinfo -p aiq` e che
   l'account `did_tesi_nlp_330` sia ammesso.

Script `sbatch` pronto (riscrive `~/run_vllm_qwen36.sbatch`):

```bash
cat > ~/run_vllm_qwen36.sbatch <<'EOF'
#!/usr/bin/env bash
#SBATCH --job-name=mass-vllm-qwen36
#SBATCH --partition=aiq
#SBATCH -A did_tesi_nlp_330
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus-per-task=1
#SBATCH --time=06:00:00
#SBATCH --output=/home/G.DAMBROSIO65/mass_vllm_logs/vllm-%j.out
#SBATCH --error=/home/G.DAMBROSIO65/mass_vllm_logs/vllm-%j.err

set -euo pipefail

hostname | tee ~/mass_vllm_node.txt

source ~/venvs/vllm-qwen36-cu129/bin/activate

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub
export VLLM_USE_DEEP_GEMM=0

vllm serve ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --host 0.0.0.0 \
  --port 8003 \
  --dtype bfloat16 \
  --max-model-len 262144 \
  --max-num-seqs 256 \
  --gpu-memory-utilization 0.95 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --language-model-only
EOF

sbatch ~/run_vllm_qwen36.sbatch
```

Log di avvio riuscito: `GPU KV cache size: ~345k tokens`, `Maximum concurrency for 262,144
tokens per request: ~1.3x`, poi `Application startup complete.`.

### Config MASS per il contesto 262144

`max_context` nella config MASS NON limita l'input: e' usato solo come tetto sull'**output**
(clamp del `max_tokens` richiesto e tetto dell'escalation in caso di risposta troncata). La
finestra reale di 262144 la fornisce il server con `--max-model-len`. Poiche' i `max_tokens`
per-ruolo (<= 65536) sono gia' sotto 131072, alzare `max_context` a 262144 e' soprattutto una
questione di coerenza/correttezza (e serve se vuoi output molto lunghi). Tenere `max_context`
piu' basso del server e' sicuro; tenerlo piu' alto del server e' rischioso (l'escalation puo'
chiedere oltre il limite del server). Quindi, se a volte avvii il server a 131072/32768, NON
usare una config a 262144: meglio una config wide separata.
