# Guida per gli Utenti (Human User Guide)

Benvenuto in MASS! Questa guida ti spiega passo dopo passo come configurare ed eseguire il progetto su macOS utilizzando esclusivamente modelli esterni tramite **OpenRouter**.

---

## 1. Preparazione dell'ambiente ed Avvio (Zero-Config)
Il progetto è configurato per installare automaticamente tutte le dipendenze e creare l'ambiente virtuale al primo avvio. Non è richiesto alcun comando da terminale.

> [!IMPORTANT]
> **Requisito Fondamentale**: È necessario avere **Python 3 (versione 3.9 o superiore)** installato sulla macchina (es. Python 3.10, 3.11, 3.12).

- **Su macOS (Mac)**: Fai doppio clic sul file `start_ui.command` o esegui `Start UI.app`.
- **Su Windows**: Fai doppio clic sul file `start_ui.bat`.

*(Al primo avvio, lo script rileverà l'assenza dell'ambiente virtuale, creerà la cartella `.venv` ed installerà automaticamente i requisiti. I successivi avvii saranno immediati).*

---

## 2. Configurazione delle credenziali OpenRouter
Il sistema necessita della tua chiave OpenRouter per interrogare i modelli esterni. Puoi inserirla in due modi:

- **Metodo A (Consigliato - Tramite Interfaccia Web)**:
  Una volta avviata l'interfaccia Streamlit nel browser, troverai nella barra laterale sinistra il pannello **Chiavi API (OpenRouter)**. Digita la tua chiave e clicca su **Salva Chiave**. La chiave verrà salvata automaticamente nel file `.env` locale in modo persistente.
  
- **Metodo B (Manuale)**:
  Crea un file di testo nella directory principale del progetto chiamato esattamente `.env` ed inserisci all'interno la seguente riga:
  ```env
  OPENROUTER_API_KEY=ghp_tua_chiave_personale_openrouter_qui
  ```

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

---

## 5. Risoluzione dei Problemi (Troubleshooting)

### A. Errore "command not found: python3" o "python"
- **Causa**: Python 3 non è installato sulla macchina o non è configurato nel PATH di sistema.
- **Soluzione**: Scarica l'installer per il tuo sistema operativo da [python.org/downloads](https://www.python.org/downloads/) e procedi all'installazione. *Su Windows, assicurati di spuntare la casella "Add Python to PATH" all'avvio dell'installazione.*

### B. Errore di connessione durante la prima installazione
- **Causa**: La prima esecuzione richiede una connessione internet attiva per scaricare le librerie necessarie (circa 100MB di pacchetti) tramite `pip`.
- **Soluzione**: Assicurati di essere connesso a internet prima di avviare il file per la prima volta.

### C. Errore di privilegi / permessi su macOS
- **Causa**: macOS blocca di default l'avvio di file eseguibili scaricati dal browser (mancanza del flag di esecuzione).
- **Soluzione**: Apri il Terminale, digita `chmod +x ` (lasciando uno spazio alla fine) e trascina il file `start_ui.command` all'interno della finestra del Terminale, poi premi Invio. Successivamente, il doppio clic funzionerà sempre.

### D. Versione di Python troppo vecchia
- **Causa**: Se sulla macchina è presente una versione di Python inferiore alla 3.9 (es. Python 3.7 o 3.8), l'installazione fallirà a causa di incompatibilità delle librerie.
- **Soluzione**: Installa una versione recente di Python (es. Python 3.10, 3.11 o 3.12) da python.org.
