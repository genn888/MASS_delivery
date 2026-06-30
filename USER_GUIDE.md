# Guida per gli Utenti (Human User Guide)

Benvenuto in MASS! Questa guida ti spiega passo dopo passo come configurare ed eseguire il progetto su macOS utilizzando esclusivamente modelli esterni tramite **OpenRouter**.

---

## 1. Preparazione dell'ambiente
1. Apri il **Terminale** del tuo Mac.
2. Posizionati nella cartella del progetto:
   ```bash
   cd "/Users/gennaro/Desktop/MASS_delivery"
   ```
   *(o digita `cd` seguito da uno spazio e trascina la cartella del progetto nella finestra del Terminale).*
3. Crea un ambiente virtuale per isolare le dipendenze:
   ```bash
   python3 -m venv .venv
   ```
4. Attiva l'ambiente virtuale:
   ```bash
   source .venv/bin/activate
   ```
5. Aggiorna `pip` ed installa tutte le dipendenze richieste:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

---

## 2. Configurazione delle credenziali OpenRouter
Il sistema necessita della tua chiave OpenRouter per interrogare i modelli esterni.
1. Crea un file di testo nella directory principale del progetto chiamato esattamente `.env`.
2. All'interno del file, scrivi la seguente riga sostituendo la chiave di esempio con la tua:
   ```env
   OPENROUTER_API_KEY=ghp_tua_chiave_personale_openrouter_qui
   ```
*(Nota: per i comandi diretti da terminale puoi anche digitare `export OPENROUTER_API_KEY="tua_chiave"` prima di lanciare gli script).*

---

## 3. Modalità d'uso 1: Interfaccia Grafica (Web UI)
Questa interfaccia (basata su Streamlit) ti permette di avviare chat interattive ed eseguire/visualizzare benchmark.

### Come avviarla:
- **Metodo veloce**: Fai doppio clic sul file `start_ui.command`. Si aprirà automaticamente un terminale che avvia il server.
- **Metodo manuale** (da Terminale attivo con `.venv` attivato):
  ```bash
  streamlit run streamlit_app.py
  ```
Il browser si aprirà automaticamente su `http://localhost:8501`.

### Come usarla per una Chat Multi-Agente:
1. Nella barra laterale di sinistra, clicca su **Chat**.
2. Nel menu a comparsa delle impostazioni della chat, seleziona una configurazione basata su OpenRouter (es. `configs/models_openrouter_qwen36plus.yaml`).
3. Inserisci la tua richiesta (es. *"Crea uno script in python per scaricare immagini da un URL"*) e premi **Invia**.
4. Vedrai in tempo reale lo scambio di messaggi e le azioni compiute dal team di agenti (Analisi requisiti -> Architettura -> Coder -> Revisore).

### Come provarla su un Benchmark (ProjectEval):
1. Nella barra laterale, clicca su **Benchmark**.
2. Seleziona la configurazione OpenRouter (es. `configs/models_openrouter_qwen36plus.yaml`).
3. Seleziona il livello di difficoltà del test (Level 1, 2, 3) e premi **Avvia Sessione**.
4. Potrai monitorare l'andamento di ciascun test e vedere il punteggio locale stimato (Pass@1) calcolato in automatico al termine della sessione.

---

## 4. Modalità d'uso 2: Riga di Comando (CLI)
Se preferisci non usare l'interfaccia grafica, puoi invocare direttamente gli script dal Terminale (assicurati che l'ambiente virtuale sia attivo tramite `source .venv/bin/activate`).

### Per avviare una Chat / Task singolo:
```bash
python3 -m app.main --models-config configs/models_openrouter_qwen36plus.yaml --task "La tua richiesta qui"
```

### Per eseguire un Benchmark (ProjectEval):
```bash
python3 -m app.benchmark.projecteval_runner --models-config configs/models_openrouter_qwen36plus.yaml --level 1 --project-ids 1,2 --mode direct
```
*(Questo comando avvierà i test di ProjectEval per i progetti ID 1 e 2 al livello 1, salvando i report di esecuzione locali nella directory del workspace).*
