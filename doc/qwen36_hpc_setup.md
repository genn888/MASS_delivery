# Qwen 3.6 27B su HPC UNISA per MASS

Questa guida riassume il setup fatto per usare `Qwen/Qwen3.6-27B` sul cluster HPC UNISA tramite una A100 e collegarlo a MASS come endpoint OpenAI-compatible.

## Setup

### 1. Accesso al cluster

1. Attiva FortiClient VPN come indicato dalla guida HPC UNISA.
2. Da Terminale sul Mac collegati al login node:

   ```bash
   ssh -l g.dambrosio65@studenti.unisa.it lnode.hpc.unisa.it
   ```

3. Verifica di essere sul login node:

   ```bash
   hostname
   ```

   Output atteso: un nodo tipo `lnode01` o `lnode02`.

### 2. Verifica account SLURM e GPU

1. Controlla gli account associati al tuo utente:

   ```bash
   sacctmgr show assoc user="$USER" format=User%35,Account%35,Partition%20,QOS%100
   ```

2. L'account tesi corretto trovato e usato e:

   ```text
   did_tesi_nlp_330
   ```

3. Controlla lo stato delle partizioni:

   ```bash
   sinfo
   ```

4. La partizione utile per le A100 NVIDIA e:

   ```text
   gpuq
   ```

### 3. Prima prova GPU interattiva

Per entrare su un nodo GPU tramite SLURM:

```bash
srun \
  --partition=gpuq \
  -A did_tesi_nlp_330 \
  --ntasks=1 \
  --cpus-per-task=8 \
  --gpus-per-task=1 \
  --time=00:30:00 \
  --pty bash
```

Quando il job parte, il prompt cambia da `lnode...` a un nodo tipo `gnode07` o `gnode14`.

Dentro il nodo GPU abbiamo verificato:

```bash
hostname
nvidia-smi
echo "$CUDA_VISIBLE_DEVICES"
```

Il valore di `CUDA_VISIBLE_DEVICES` indica la GPU assegnata da SLURM. Anche se `nvidia-smi` mostra piu GPU fisiche, i processi CUDA vedono solo quella assegnata.

### 4. Primo tentativo con vLLM

Abbiamo creato un ambiente Python per vLLM nella home utente:

```bash
cd ~
mkdir -p ~/tools ~/venvs ~/hf_cache
python3 -m pip install --target ~/tools/virtualenv virtualenv
PYTHONPATH=~/tools/virtualenv python3 -m virtualenv ~/venvs/vllm
source ~/venvs/vllm/bin/activate
python -m pip install --upgrade pip
python -m pip install "vllm==0.11.0"
```

Abbiamo poi allineato lo stack a CUDA 12.8, perche il cluster ha driver compatibili con CUDA 12.8:

```bash
source ~/venvs/vllm/bin/activate
python - <<'PY'
import torch, vllm
print("torch:", torch.__version__)
print("torch cuda:", torch.version.cuda)
print("vllm:", vllm.__version__)
PY
```

Output buono:

```text
torch: 2.8.0+cu128
torch cuda: 12.8
vllm: 0.11.0
```

Con questo ambiente abbiamo testato con successo un modello piccolo:

```bash
export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub
export VLLM_USE_FLASHINFER_SAMPLER=0

vllm serve Qwen/Qwen2.5-0.5B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype bfloat16 \
  --max-model-len 4096 \
  --enforce-eager
```

Questo ha confermato che:

- la GPU A100 funziona;
- il tunnel SSH funziona;
- MASS puo parlare con un endpoint OpenAI-compatible su `http://localhost:8000/v1`.

### 5. Perche non abbiamo usato vLLM per Qwen 3.6 27B

`Qwen/Qwen3.6-27B` usa una architettura nuova (`qwen3_5`). Lo stack `vllm==0.11.0` non la riconosce.

Abbiamo provato uno stack vLLM piu recente, ma quel binario cercava librerie CUDA 13:

```text
ImportError: libcudart.so.13: cannot open shared object file
```

Il cluster invece espone CUDA/driver 12.8. Per non compilare vLLM da sorgente e non chiedere moduli/container agli admin, abbiamo scelto una strada alternativa.

### 6. Soluzione usata: Transformers server

Abbiamo creato un secondo ambiente dedicato a Qwen 3.6 via Hugging Face Transformers:

```bash
cd ~
PYTHONPATH=~/tools/virtualenv python3 -m virtualenv ~/venvs/qwen36-transformers
source ~/venvs/qwen36-transformers/bin/activate

python -m pip install --upgrade pip uv
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
uv pip install "transformers[serving]" accelerate pillow sentencepiece protobuf requests
```

Controllo:

```bash
python - <<'PY'
import torch, transformers
print("torch:", torch.__version__)
print("torch cuda:", torch.version.cuda)
print("transformers:", transformers.__version__)
PY
```

### 7. Download controllato del modello

Il primo tentativo di download direttamente da `transformers serve` si era bloccato. Abbiamo quindi scaricato il modello prima, dal login node, senza occupare GPU.

Con venv attivo:

```bash
source ~/venvs/qwen36-transformers/bin/activate
export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub
python -m pip install -U "huggingface_hub[cli]"
```

Download:

```bash
hf download Qwen/Qwen3.6-27B \
  --local-dir ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --max-workers 4
```

Il download completo ha creato:

```text
/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local
```

Dimensione scaricata osservata:

```text
55.6GB
```

### 8. Avvio server Qwen 3.6 27B

Dentro un job GPU lungo:

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

Sul nodo GPU:

```bash
source ~/venvs/qwen36-transformers/bin/activate
export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

transformers serve ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --port 8000 \
  --continuous-batching
```

Output buono:

```text
Application startup complete.
Uvicorn running on http://localhost:8000
```

Nota: il server Transformers ascolta su `localhost` del nodo GPU, quindi per raggiungerlo dal Mac serve un tunnel SSH via jump host.

### 9. Tunnel dal Mac al nodo GPU

Se il nodo GPU e `gnode14`, dal Mac:

```bash
ssh -J g.dambrosio65@studenti.unisa.it@lnode.hpc.unisa.it \
  -L 8000:127.0.0.1:8000 \
  g.dambrosio65@studenti.unisa.it@gnode14
```

Se la porta locale `8000` e gia occupata:

```bash
ssh -J g.dambrosio65@studenti.unisa.it@lnode.hpc.unisa.it \
  -L 8001:127.0.0.1:8000 \
  g.dambrosio65@studenti.unisa.it@gnode14
```

### 10. Test dal Mac

Lista modelli:

```bash
curl http://localhost:8000/v1/models
```

Richiesta chat:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local",
    "messages": [
      {"role": "user", "content": "Scrivi esattamente queste tre parole e nient altro: Qwen operativo ora"}
    ],
    "max_tokens": 120
  }'
```

Nota importante: quando il server e avviato da path locale, nella richiesta `model` bisogna usare il path locale:

```text
/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local
```

Non basta usare:

```text
Qwen/Qwen3.6-27B
```

### 11. Configurazione MASS

Nel progetto MASS e stata creata la configurazione:

```text
configs/models_local_qwen36_27b_hpc.yaml
```

La config usa:

```yaml
provider: openai_compatible
model: /home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local
api_key_env: LOCAL_QWEN_API_KEY
base_url: http://localhost:8000/v1
```

Nel file `.env` del progetto MASS e stata aggiunta:

```bash
LOCAL_QWEN_API_KEY=dummy
```






























## Uso

Questa sezione descrive cosa fare ogni volta che vuoi riusare Qwen 3.6 27B con MASS, partendo da quando hai gia fatto SSH al centro di calcolo.

### 1. Controlla di essere sul login node

```bash
hostname
```

Output atteso: `lnode01`, `lnode02` o simile.

### 2. Controlla se hai job attivi

```bash
squeue -u "$USER"
```

Se vedi un job vecchio che vuoi fermare:

```bash
scancel JOBID
```

Sostituisci `JOBID` con il numero nella prima colonna.

### 3. Richiedi una A100 con SLURM

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

Se resta fermo, sei in coda. Da un secondo terminale puoi controllare:

```bash
squeue -u "$USER"
```

Quando parte, il prompt cambia in `gnode...`.

### 4. Segna il nome del nodo GPU

Dentro il job:

```bash
hostname
```

Esempio:

```text
gnode14
```

Questo nome serve per il tunnel dal Mac.

### 5. Avvia Qwen 3.6 27B sul nodo GPU

Sempre dentro il nodo GPU:

```bash
source ~/venvs/qwen36-transformers/bin/activate
export HF_HOME=~/hf_cache
export HUGGINGFACE_HUB_CACHE=~/hf_cache/hub

transformers serve ~/hf_cache/models--Qwen--Qwen3.6-27B-local \
  --port 8000 \
  --continuous-batching
```

Lascia aperto questo terminale. Il modello resta attivo finche:

- il terminale resta aperto;
- il job SLURM resta attivo;
- non premi `Ctrl+C`;
- non scade il limite di tempo del job.

### 6. Apri il tunnel dal Mac

In un terminale nuovo sul Mac, sostituendo `gnode14` con il nodo ottenuto da `hostname`:

```bash
ssh -J g.dambrosio65@studenti.unisa.it@lnode.hpc.unisa.it \
  -L 8000:127.0.0.1:8000 \
  g.dambrosio65@studenti.unisa.it@gnode09
```

Lascia aperto anche questo terminale.

Se ottieni:

```text
bind [127.0.0.1]:8000: Address already in use
```

usa la porta locale 8001:

```bash
ssh -J g.dambrosio65@studenti.unisa.it@lnode.hpc.unisa.it \
  -L 8001:127.0.0.1:8000 \
  g.dambrosio65@studenti.unisa.it@gnode14
```

In quel caso anche MASS dovra usare `http://localhost:8001/v1` invece di `http://localhost:8000/v1`.

### 7. Test rapido dal Mac

Se usi porta 8000:

```bash
curl http://localhost:8000/v1/models
```

Se usi porta 8001:

```bash
curl http://localhost:8001/v1/models
```

Se risponde JSON e vedi il modello, il tunnel funziona.

### 8. Avvia MASS

Nel progetto MASS, assicurati che `.env` contenga:

```bash
LOCAL_QWEN_API_KEY=dummy
```

Poi usa la config:

```text
configs/models_local_qwen36_27b_hpc.yaml
```

Da interfaccia Streamlit, seleziona quella config nel menu dei modelli.

Da CLI:

```bash
python -m app.main \
  --models-config configs/models_local_qwen36_27b_hpc.yaml \
  --task "Build a CLI TODO app with tests"
```

### 9. Cosa deve restare aperto

Per usare MASS con Qwen 3.6 27B devono restare attivi:

1. FortiClient VPN.
2. Il job SLURM sul nodo GPU.
3. Il terminale con `transformers serve`.
4. Il terminale con il tunnel SSH.
5. MASS sul Mac.

Se uno di questi cade, MASS non riesce piu a raggiungere il modello.

### 10. Come fermare tutto

1. Ferma MASS se lo stai usando.
2. Nel terminale del tunnel SSH premi:

   ```text
   Ctrl+C
   ```

   oppure:

   ```bash
   exit
   ```

3. Nel terminale del server `transformers serve` premi:

   ```text
   Ctrl+C
   ```

4. Esci dal job GPU:

   ```bash
   exit
   ```

5. Controlla che non siano rimasti job:

   ```bash
   squeue -u "$USER"
   ```

6. Se serve annullare un job rimasto:

   ```bash
   scancel JOBID
   ```

### 11. Problemi comuni

#### Porta locale occupata

Errore:

```text
Address already in use
```

Soluzione: usa `8001` nel tunnel e cambia `base_url` in MASS a:

```text
http://localhost:8001/v1
```

#### Il server dice che il model richiesto non corrisponde

Errore simile:

```text
Server is pinned to '/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local'
```

Soluzione: usa sempre come model:

```text
/home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local
```

#### Qwen produce molto ragionamento

Qwen 3.6 tende a ragionare prima della risposta. Con il server Transformers locale non siamo riusciti a disabilitare il thinking via API OpenAI-compatible. Per questo nella config MASS sono stati messi timeout lunghi e token di output abbastanza ampi.

#### Il job scade

Quando scade il tempo SLURM, il server si spegne. Bisogna ripetere la procedura dalla sezione "Uso", partendo dalla richiesta `srun`.
