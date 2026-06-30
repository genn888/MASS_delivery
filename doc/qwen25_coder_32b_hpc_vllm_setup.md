# Qwen2.5-Coder 32B su HPC UNISA con vLLM

Questa guida descrive come servire `Qwen/Qwen2.5-Coder-32B-Instruct` sul cluster HPC UNISA con vLLM, esponendo un endpoint OpenAI-compatible da usare in MASS per gli esperimenti multiagente.

La guida copre due modalita:

1. **Standard 32k**: usa il `config.json` originale del modello, contesto `32768`, piu semplice e consigliata per il primo test.
2. **Wide 128k con YaRN**: usa una copia separata del modello con `rope_scaling` YaRN, contesto `131072`, consigliata quando il sistema multiagente deve passare molto codice, log, artefatti e feedback.

Setup consigliato iniziale:

- modello: `Qwen/Qwen2.5-Coder-32B-Instruct`
- backend: vLLM, usando l'ambiente gia creato per Qwen3.6 se disponibile
- GPU: 2 x NVIDIA A100 80GB
- parallelismo: `--tensor-parallel-size 2`
- dtype: `bfloat16`
- porta remota: `8004`
- endpoint locale Mac: `http://localhost:8004/v1`
- API key locale: dummy, via `.env`

## Note su contesto e YaRN

La model card di Qwen2.5-Coder 32B dichiara long-context fino a `131072` token, ma il `config.json` scaricato e impostato di default per `32768` token.

Per superare 32k, Qwen consiglia YaRN, cioe una configurazione di `rope_scaling` che estende la codifica posizionale del modello. In pratica:

- senza YaRN: usa `--max-model-len 32768`;
- con YaRN `factor: 4.0`: puoi usare `--max-model-len 131072`.

Importante: con vLLM YaRN e statico. Questo significa che resta attivo anche per prompt corti e puo peggiorare leggermente qualita o performance su input brevi. Per questo conviene mantenere due copie:

- copia standard 32k;
- copia wide 128k con YaRN.

## Setup da zero

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

### 2. Prepara le cartelle

```bash
cd ~
mkdir -p ~/tools ~/venvs ~/hf_cache ~/src ~/mass_vllm_logs
```

### 3. Attiva o crea l'ambiente vLLM

Se esiste gia l'ambiente usato per Qwen3.6:

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate
```

Verifica:

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

Sul login node `cuda_available: False` e normale. L'importante e che lo stack sia CUDA, non ROCm.

Se l'ambiente non esiste, crealo come nella guida Qwen3.6 vLLM:

```bash
python3 -m pip install --target ~/tools/virtualenv virtualenv
PYTHONPATH=~/tools/virtualenv python3 -m virtualenv ~/venvs/vllm-qwen36-cu129
source ~/venvs/vllm-qwen36-cu129/bin/activate
python -m pip install -U pip uv

uv pip install torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/cu129

uv pip install \
  "https://github.com/vllm-project/vllm/releases/download/v0.20.1/vllm-0.20.1+cu129-cp38-abi3-manylinux_2_31_x86_64.whl"

uv pip install -U git+https://github.com/huggingface/transformers.git
```

### 4. Scarica il modello standard 32k

Fallo dal login node, senza occupare GPU:

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate
python -m pip install -U "huggingface_hub[cli]"

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

hf download Qwen/Qwen2.5-Coder-32B-Instruct \
  --local-dir ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local \
  --max-workers 4
```

Path locale standard:

```text
/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local
```

Controlla:

```bash
du -sh ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local
ls ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local/model-*.safetensors | wc -l
ls ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local | head
df -h ~
```

Output atteso:

```text
69G    /home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local
14
```

Il valore `14` indica che sono presenti tutti gli shard `safetensors` del modello.

### 5. Se `/home` non ha abbastanza spazio

Durante il download puo comparire un errore simile:

```text
Not enough free disk space to download the file
```

Controlla lo spazio:

```bash
df -h ~ ~/hf_cache /tmp 2>/dev/null
```

Poi guarda cosa occupa la home:

```bash
du -h --max-depth=1 ~ 2>/dev/null | sort -h | tail -n 20
```

Nel setup reale lo spazio era occupato soprattutto da `~/hf_cache`, `~/venvs` e `~/.cache`. Le cache ricostruibili che puoi rimuovere senza toccare gli ambienti gia installati sono:

```bash
rm -rf ~/.cache/uv
rm -rf ~/.cache/pip
```

Se hai un download incompleto di Qwen2.5-Coder, rimuovilo prima di riprovare:

```bash
rm -rf ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local
rm -rf ~/hf_cache/hub/models--Qwen--Qwen2.5-Coder-32B-Instruct
```

Se serve altro spazio, controlla gli ambienti:

```bash
du -h --max-depth=1 ~/venvs 2>/dev/null | sort -h
```

Non cancellare `~/venvs/vllm-qwen36-cu129`, perche e l'ambiente usato da questa guida. Nel setup reale sono stati rimossi vecchi ambienti come:

```bash
rm -rf ~/venvs/vllm
rm -rf ~/venvs/vllm-qwen36
```

Se hai gia la copia locale Qwen3.6 in `~/hf_cache/models--Qwen--Qwen3.6-27B-local`, puoi rimuovere la cache hub duplicata:

```bash
rm -rf ~/hf_cache/hub/models--Qwen--Qwen3.6-27B
```

Prima di rilanciare il download di Qwen2.5-Coder, prova ad avere almeno `65-70G` liberi:

```bash
df -h ~
```

## Modalita standard 32k

Usa questa modalita per il primo avvio e per verificare che tutto funzioni.

### 1. Richiedi 2 GPU

Dal login node:

```bash
srun \
  --partition=gpuq \
  -A did_tesi_nlp_330 \
  --ntasks=1 \
  --cpus-per-task=12 \
  --gpus-per-task=2 \
  --time=06:00:00 \
  --pty bash
```

Quando parte, il prompt diventa `gnode...`.

Controlla:

```bash
hostname
nvidia-smi
echo "$CUDA_VISIBLE_DEVICES"
```

### 2. Verifica vLLM sul nodo GPU

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

python - <<'PY'
import torch, vllm
print("cuda_available:", torch.cuda.is_available())
print("device_count:", torch.cuda.device_count())
print("gpu0:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
print("torch cuda:", torch.version.cuda)
print("vllm:", vllm.__version__)
PY
```

Output buono:

```text
cuda_available: True
device_count: 2
gpu0: NVIDIA A100-SXM4-80GB
vllm: 0.20.1
```

### 3. Avvia vLLM standard 32k

Sul nodo GPU:

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

vllm serve ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local \
  --served-model-name Qwen/Qwen2.5-Coder-32B-Instruct \
  --host 0.0.0.0 \
  --port 8004 \
  --dtype bfloat16 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 2
```

Aspetta:

```text
Application startup complete.
```

Note:

- non usare `--reasoning-parser qwen3`, perche questo modello e Qwen2.5-Coder, non Qwen3;
- `--served-model-name` permette a MASS e ai test `curl` di usare il nome Hugging Face invece del path locale.

### 4. Apri il tunnel SSH dal Mac

In un nuovo terminale sul Mac, sostituisci `gnodeXX` col nodo reale:

```bash
ssh -L 8004:gnodeXX:8004 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

Lascia aperto il terminale del tunnel.

### 5. Test dal Mac

Lista modelli:

```bash
curl http://localhost:8004/v1/models
```

Chat:

```bash
curl http://localhost:8004/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "messages": [{"role": "user", "content": "Scrivi esattamente: Qwen2.5 Coder operativo"}],
    "max_tokens": 80,
    "temperature": 0.2
  }'
```

Risposta attesa:

```text
Qwen2.5 Coder operativo
```

## Modalita wide 128k con YaRN

Usa questa modalita quando ti serve piu contesto per esperimenti multiagente lunghi.

### 1. Crea una copia separata del modello

Dal login node:

```bash
cp -r \
  ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local \
  ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-128k-yarn-local
```

Path locale wide:

```text
/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-128k-yarn-local
```

### 2. Modifica `config.json` per YaRN

Apri:

```bash
nano ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-128k-yarn-local/config.json
```

Aggiungi questa chiave al livello principale del JSON:

```json
"rope_scaling": {
  "factor": 4.0,
  "original_max_position_embeddings": 32768,
  "type": "yarn"
}
```

Esempio: se `config.json` finisce con:

```json
  "vocab_size": 152064
}
```

deve diventare:

```json
  "vocab_size": 152064,
  "rope_scaling": {
    "factor": 4.0,
    "original_max_position_embeddings": 32768,
    "type": "yarn"
  }
}
```

Verifica che il JSON sia valido:

```bash
python -m json.tool \
  ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-128k-yarn-local/config.json \
  >/dev/null
```

Se non stampa nulla, il JSON e valido.

### 3. Richiedi 2 GPU

```bash
srun \
  --partition=gpuq \
  -A did_tesi_nlp_330 \
  --ntasks=1 \
  --cpus-per-task=12 \
  --gpus-per-task=2 \
  --time=06:00:00 \
  --pty bash
```

### 4. Avvia vLLM wide 128k

Sul nodo GPU:

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

vllm serve ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-128k-yarn-local \
  --served-model-name Qwen/Qwen2.5-Coder-32B-Instruct-128K \
  --host 0.0.0.0 \
  --port 8004 \
  --dtype bfloat16 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 2
```

Se va in OOM, prova in quest'ordine:

```bash
--gpu-memory-utilization 0.95
```

oppure riduci il contesto:

```bash
--max-model-len 65536
```

Per 64k puoi usare la stessa copia YaRN, ma nella config MASS dovrai impostare `max_context: 65536`.

### 5. Test wide dal Mac

Tunnel:

```bash
ssh -L 8004:gnodeXX:8004 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

Test:

```bash
curl http://localhost:8004/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-32B-Instruct-128K",
    "messages": [{"role": "user", "content": "Scrivi esattamente: Qwen2.5 Coder 128K operativo"}],
    "max_tokens": 80,
    "temperature": 0.2
  }'
```

## Configurazione MASS

Nel file `.env` del progetto MASS sul Mac aggiungi:

```bash
LOCAL_QWEN25_CODER_API_KEY=dummy
```

### Config standard 32k

Nel repository MASS e stata creata:

```text
configs/models_local_qwen25_coder_32b_hpc_vllm.yaml
```

La config usa:

```yaml
model: Qwen/Qwen2.5-Coder-32B-Instruct
api_key_env: LOCAL_QWEN25_CODER_API_KEY
base_url: http://localhost:8004/v1
max_context: 32768
```

Limiti usati nella config standard:

- `requirement_analyzer`: `max_tokens: 8192`
- `architect`: `max_tokens: 12288`
- `planning_reviewer`: `max_tokens: 8192`
- `coder`: `max_tokens: 16384`
- `reviewer`: `max_tokens: 8192`
- `test_writer`: `max_tokens: 16384`
- `parameter_solver`: `max_tokens: 8192`
- `parameter_repairer`: `max_tokens: 8192`

Questi valori sono piu conservativi della vecchia config Qwen3.6 wide, perche il server standard parte a `--max-model-len 32768`.

### Config wide 128k

Crea:

```text
configs/models_local_qwen25_coder_32b_hpc_vllm_128k.yaml
```

Usa questa base:

```yaml
provider: openai_compatible
model: Qwen/Qwen2.5-Coder-32B-Instruct-128K
api_key_env: LOCAL_QWEN25_CODER_API_KEY
base_url: http://localhost:8004/v1
temperature: 0.0
max_tokens: 32768
request_timeout_seconds: 3600
hard_timeout_seconds: 3630
max_attempts: 1
capabilities:
  supports_tools: false
  supports_json: true
  supports_system_prompt: true
  max_context: 131072
```

Regola pratica:

- usa la config 32k se vuoi confronti piu stabili e prompt medi;
- usa la config 128k quando sai che MASS passera molti artefatti agli agenti.

## Avvio MASS

Da CLI:

```bash
python -m app.main \
  --models-config configs/models_local_qwen25_coder_32b_hpc_vllm.yaml \
  --task "Build a CLI TODO app with tests"
```

Per la versione wide:

```bash
python -m app.main \
  --models-config configs/models_local_qwen25_coder_32b_hpc_vllm_128k.yaml \
  --task "Build a CLI TODO app with tests"
```

Benchmark ProjectEval:

```bash
python -m app.benchmark.projecteval_runner \
  --models-config configs/models_local_qwen25_coder_32b_hpc_vllm_128k.yaml \
  --system-config configs/system.yaml \
  --projecteval-root external/ProjectEval \
  --archive-root benchmark_archives/projecteval \
  --level 2 \
  --mode direct \
  --project-ids 1
```

Se usi la UI Streamlit, seleziona la config nel campo "Config modelli".

## Uso dopo il setup

Questa e la procedura breve da usare quando il modello e gia scaricato e vuoi solo riavviare il server per una nuova sessione di esperimenti.

### 1. Collegati al login node

Dal Mac, con VPN attiva:

```bash
ssh -l g.dambrosio65@studenti.unisa.it lnode.hpc.unisa.it
```

Attiva l'ambiente:

```bash
source ~/venvs/vllm-qwen36-cu129/bin/activate
```

Controlla eventuali job gia attivi:

```bash
squeue -u "$USER"
```

Se c'e un vecchio job da fermare:

```bash
scancel JOBID
```

### 2. Avvia il server in batch

Se lo script esiste gia:

```bash
ls -l ~/run_vllm_qwen25_coder_32b.sbatch
```

Lancialo:

```bash
sbatch ~/run_vllm_qwen25_coder_32b.sbatch
```

Output atteso:

```text
Submitted batch job 491892
```

Sostituisci `491892` con il tuo `JOBID` reale nei comandi successivi.

### 3. Controlla nodo e stato

```bash
squeue -j 491892 -o "%.18i %.2t %.10M %.20N %R"
```

Esempio buono:

```text
             JOBID ST       TIME             NODELIST NODELIST(REASON)
            491892  R       0:16              gnode06 gnode06
```

In alternativa, quando il job parte, lo script salva il nodo qui:

```bash
cat ~/mass_vllm_qwen25_node.txt
```

### 4. Aspetta che vLLM sia pronto

```bash
tail -f ~/mass_vllm_logs/qwen25-vllm-491892.out
```

Aspetta:

```text
Application startup complete.
```

Poi esci dal `tail` con `Ctrl+C`. Questo non ferma il server.

### 5. Apri il tunnel dal Mac

Questo comando va lanciato sul Mac, non dentro SSH. Sostituisci `gnode06` col nodo reale:

```bash
ssh -L 8004:gnode06:8004 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

Lascia aperto il terminale del tunnel mentre usi MASS.

### 6. Testa dal Mac

In un altro terminale Mac:

```bash
curl http://localhost:8004/v1/models
```

Poi:

```bash
curl http://localhost:8004/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "messages": [{"role": "user", "content": "Scrivi esattamente: Qwen2.5 Coder operativo"}],
    "max_tokens": 80,
    "temperature": 0.2
  }'
```

Se risponde, MASS puo usare:

```text
configs/models_local_qwen25_coder_32b_hpc_vllm.yaml
```

### 7. Cosa resta acceso se chiudi il Mac

Il job batch e il server vLLM restano attivi sul cluster fino alla scadenza delle 6 ore, anche se chiudi SSH, spegni il Mac o chiudi il tunnel.

Quando riaccendi il Mac, riapri:

1. VPN FortiClient.
2. Tunnel SSH verso lo stesso nodo, se il job e ancora attivo.

Per controllare:

```bash
squeue -j 491892
```

Per fermare prima delle 6 ore:

```bash
scancel 491892
```

## Modalita batch con `sbatch`

Usa `sbatch` se vuoi che il server resti attivo anche chiudendo SSH o il terminale.

Se hai un server interattivo avviato con `srun --pty bash`, fermalo prima di lanciare il batch:

1. Nel terminale dove gira `vllm serve`, premi `Ctrl+C`.
2. Quando torna il prompt del nodo GPU, esegui:

   ```bash
   exit
   ```

3. Verifica dal login node:

   ```bash
   squeue -u "$USER"
   ```

### Batch standard 32k

Dal login node:

```bash
mkdir -p ~/mass_vllm_logs
```

Crea lo script:

```bash
cat > ~/run_vllm_qwen25_coder_32b.sbatch <<'EOF'
#!/usr/bin/env bash
#SBATCH --job-name=mass-vllm-qwen25
#SBATCH --partition=gpuq
#SBATCH -A did_tesi_nlp_330
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=12
#SBATCH --gpus-per-task=2
#SBATCH --time=06:00:00
#SBATCH --output=/home/G.DAMBROSIO65/mass_vllm_logs/qwen25-vllm-%j.out
#SBATCH --error=/home/G.DAMBROSIO65/mass_vllm_logs/qwen25-vllm-%j.err

set -euo pipefail

hostname | tee ~/mass_vllm_qwen25_node.txt

source ~/venvs/vllm-qwen36-cu129/bin/activate

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

vllm serve ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local \
  --served-model-name Qwen/Qwen2.5-Coder-32B-Instruct \
  --host 0.0.0.0 \
  --port 8004 \
  --dtype bfloat16 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 2
EOF
```

Lancia:

```bash
sbatch ~/run_vllm_qwen25_coder_32b.sbatch
```

### Batch wide 128k

Crea lo script:

```bash
cat > ~/run_vllm_qwen25_coder_32b_128k.sbatch <<'EOF'
#!/usr/bin/env bash
#SBATCH --job-name=mass-vllm-qwen25-128k
#SBATCH --partition=gpuq
#SBATCH -A did_tesi_nlp_330
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=12
#SBATCH --gpus-per-task=2
#SBATCH --time=06:00:00
#SBATCH --output=/home/G.DAMBROSIO65/mass_vllm_logs/qwen25-128k-vllm-%j.out
#SBATCH --error=/home/G.DAMBROSIO65/mass_vllm_logs/qwen25-128k-vllm-%j.err

set -euo pipefail

hostname | tee ~/mass_vllm_qwen25_node.txt

source ~/venvs/vllm-qwen36-cu129/bin/activate

export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

vllm serve ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-128k-yarn-local \
  --served-model-name Qwen/Qwen2.5-Coder-32B-Instruct-128K \
  --host 0.0.0.0 \
  --port 8004 \
  --dtype bfloat16 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 2
EOF
```

Lancia:

```bash
sbatch ~/run_vllm_qwen25_coder_32b_128k.sbatch
```

### Controllo job batch

Controlla stato:

```bash
squeue -u "$USER"
```

Leggi il nodo:

```bash
cat ~/mass_vllm_qwen25_node.txt
```

Segui i log, sostituendo `JOBID`:

```bash
tail -f ~/mass_vllm_logs/qwen25-vllm-JOBID.out
tail -n 120 ~/mass_vllm_logs/qwen25-vllm-JOBID.err
```

Per la variante wide:

```bash
tail -f ~/mass_vllm_logs/qwen25-128k-vllm-JOBID.out
tail -n 120 ~/mass_vllm_logs/qwen25-128k-vllm-JOBID.err
```

Aspetta:

```text
Application startup complete.
```

Poi apri il tunnel dal Mac verso il nodo indicato.

Ferma il server:

```bash
scancel JOBID
```

## Variante 1 GPU

Se hai solo una A100 80GB, puoi provare il setup standard 32k senza tensor parallel:

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

Avvio:

```bash
vllm serve ~/hf_cache/models--Qwen--Qwen2.5-Coder-32B-Instruct-local \
  --served-model-name Qwen/Qwen2.5-Coder-32B-Instruct \
  --host 0.0.0.0 \
  --port 8004 \
  --dtype bfloat16 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90
```

Per la modalita 128k, usa 2 GPU. Una sola GPU potrebbe non bastare per pesi, KV cache e concorrenza del sistema multiagente.

## Checklist operativa

Prima di avviare MASS:

1. VPN FortiClient attiva.
2. Job SLURM attivo su `gpuq`.
3. Server `vllm serve` avviato sul nodo GPU.
4. Log con `Application startup complete`.
5. Tunnel SSH aperto dal Mac:

   ```bash
   ssh -L 8004:gnodeXX:8004 \
     -l g.dambrosio65@studenti.unisa.it \
     lnode.hpc.unisa.it
   ```

6. Test `curl http://localhost:8004/v1/models` funzionante.
7. `.env` MASS contiene:

   ```bash
   LOCAL_QWEN25_CODER_API_KEY=dummy
   ```

8. Config MASS coerente con il server:
   - server 32k -> `max_context: 32768`;
   - server 128k -> `max_context: 131072`;
   - model standard -> `Qwen/Qwen2.5-Coder-32B-Instruct`;
   - model wide -> `Qwen/Qwen2.5-Coder-32B-Instruct-128K`.

## Troubleshooting

### `curl /v1/models` non risponde

Controlla:

```bash
squeue -u "$USER"
cat ~/mass_vllm_qwen25_node.txt
```

Poi verifica che il tunnel punti al nodo giusto:

```bash
ssh -L 8004:gnodeXX:8004 \
  -l g.dambrosio65@studenti.unisa.it \
  lnode.hpc.unisa.it
```

### Il server dice che il modello richiesto non esiste

Controlla il nome usato nella richiesta:

- server standard:

  ```text
  Qwen/Qwen2.5-Coder-32B-Instruct
  ```

- server wide:

  ```text
  Qwen/Qwen2.5-Coder-32B-Instruct-128K
  ```

Deve coincidere con `--served-model-name` e con `model:` nella config MASS.

### OOM all'avvio 128k

Prova:

```bash
--gpu-memory-utilization 0.95
```

Se non basta, riduci:

```bash
--max-model-len 65536
```

e usa una config MASS con:

```yaml
max_context: 65536
```

### Le risposte sono lente

E normale per prompt lunghi e molti agenti. Per ridurre latenza:

- usa la config 32k quando non serve long-context;
- riduci `max_tokens` nei ruoli che non devono produrre codice lungo;
- evita di lanciare troppe run concorrenti sullo stesso server;
- usa `sbatch` per evitare che il server muoia se chiudi il terminale.

### Il JSON mode non e perfetto

La config MASS puo indicare:

```yaml
supports_json: true
```

ma i modelli locali possono comunque produrre testo extra in casi difficili. Se succede spesso, riduci temperatura a `0.0`, limita output non necessari e usa i repairer gia presenti nel workflow.

## Fonti

- Hugging Face model card: `Qwen/Qwen2.5-Coder-32B-Instruct`
- vLLM OpenAI-compatible server documentation
- Guida locale MASS: `doc/qwen36_hpc_vllm_setup.md`
