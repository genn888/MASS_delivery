# Architecture Review — Sistema Multi-Agente LangGraph (MASS)

> Analisi statica del codice (`app/agents`, `app/graph`, `app/tools`) incrociata con la
> sessione di benchmark **`multi_agent_minimax2.7_1`** (ProjectEval, level 2, mode `direct`,
> modello `MiniMax-M2.7` locale via OpenAI-compatible, 31 mag → 2 giu 2026).
>
> **Scopo:** evidenziare criticità e ottimizzazioni evidenti. Nessun file è stato modificato.

---

## 1. Sintesi esecutiva

Il sistema è un grafo LangGraph lineare con loop di revisione/coding. Funziona, ma soffre di
**tre classi di problemi** che spiegano sia gli score bassi sia i tempi enormi:

1. **Tool usage non agentico** — gli LLM generano solo testo/JSON; i tool (`FileTool`,
   `TestTool`, static analyzer) sono chiamati dal codice di orchestrazione, non dal modello.
2. **Spreco di wall-clock enorme** dovuto alla logica di retry su `MAX_TOKENS` (retry inutili
   e deterministici, 120 s di sleep ciascuno).
3. **Disallineamento col judge ufficiale** — il sistema genera e valida *test propri*, ma lo
   scoring ProjectEval usa selettori/probe esterni che spesso non trovano gli elementi.

### Numeri chiave della sessione

| Metrica | Valore |
|---|---|
| Progetti completati | 8 / 20 (12 `pending`) |
| `local_pass_at_1` | 0.40 |
| `official_score` / `fixed_pass_at_1` | **0.461** (131/284 test) |
| `average_project_score` | 0.561 |
| Durata wall-clock | ~2 giorni (con resume/idle) |
| Retry `MAX_TOKENS` totali | **70** (di cui **18** finestre esaurite) |
| Timeout provider / API error | 14 / 9 |
| Website "home readiness check failed" (score ~0) | **7** |
| Parameter-solver JSON parse failed | 10 |

---

## 2. Architettura attuale (com'è)

### 2.1 Grafo (`app/graph/builder.py`)

```
START
 → requirement_analyzer (LLM)
 → benchmark_contract     (deterministico, no LLM)
 → architect (LLM) ⇄ planning_reviewer (LLM)     [loop planning, max 2]
 → coder (LLM + FileTool)
 → static_analysis (no LLM, static_analyzer)
 → test_writer (LLM + FileTool + TestTool: pytest)
 → browser_test_writer (LLM + FileTool + TestTool: Selenium)   [solo website]
 → reviewer (LLM + FileTool read-only) ⇄ coder    [loop coding, max 4]
 → finalizer (no LLM) → END
```

Limiti da `configs/system.yaml`: `max_planning_iterations=2`, `max_coding_iterations=4`,
`max_global_iterations=4`.

### 2.2 Tool per agente (riepilogo)

| Agente | LLM | Tool realmente usati |
|---|---|---|
| requirement_analyzer | ✅ | ❌ nessuno |
| benchmark_contract | ❌ | builder deterministico |
| architect | ✅ | ❌ nessuno |
| planning_reviewer | ✅ | ❌ nessuno |
| **coder** | ✅ | `FileTool` (write/remove/validate_python/validate_framework + django smoke), snapshot |
| static_analysis | ❌ | `analyze_generated_project` |
| **test_writer** | ✅ | `FileTool` + `TestTool` (`run_django_check`, `run_pytest_targets`) |
| **browser_test_writer** | ✅ | `FileTool` + `TestTool` (Selenium via subprocess) |
| reviewer | ✅ | `FileTool` **solo lettura** |
| finalizer | ❌ | ❌ |

---

## 3. Criticità principali

### 🔴 C1 — Retry `MAX_TOKENS` inutile e costosissimo *(ottimizzazione più ovvia)*

In `BaseAgent.generate_response` (`app/agents/base_agent.py:230-250`), quando la risposta
viene troncata (`finish_reason = MAX_TOKENS`), l'agente **dorme 120 s e ripete la stessa
identica richiesta**, senza aumentare `max_tokens` né cambiare i messaggi:

```python
response = self.llm.generate(messages=response_messages, response_format=response_format)
...
hit_output_limit = "MAX_TOKENS" in finish_reason ...
# → sleep(120) e retry con STESSO input, STESSO max_tokens
```

**Perché è grave:**
- I ruoli `requirement_analyzer`, `architect`, `planning_reviewer`, `coder`,
  `parameter_solver` girano a **`temperature = 0.0`** → output **deterministico**.
  Ripetere la stessa richiesta dà **lo stesso troncamento**. Il retry non può cambiare esito.
- Costo: **70 retry × 120 s ≈ 2.3 ore di puro sleep** in questa sessione, oltre al tempo di
  ri-generazione. **18 finestre** sono andate in timeout (16 min ciascuna) restituendo
  comunque la risposta troncata.
- Offender principale: **ReviewerAgent (35 hit, 9 finestre esaurite)** e
  RequirementAnalyzer (15), BrowserTestWriter (12), PlanningReviewer (5), Coder (4).

**Causa a monte:** MiniMax-M2.7 è un modello *reasoning* che consuma token in "pensiero";
budget come `planning_reviewer.max_tokens = 4096` o `reviewer = 16384` si esauriscono prima
di chiudere l'output.

**Fix ovvio:** al primo `MAX_TOKENS`, **aumentare `max_tokens`** (es. ×1.5/×2 fino al cap di
contesto) e/o **non ritentare i ruoli a temp=0**; ridurre lo sleep da 120 s. In più,
separare il budget "reasoning" da quello di output se il provider lo supporta.

---

### 🔴 C2 — Metà dei siti web non si avvia per il judge (score ~0)

7 progetti website falliscono il **`Website home readiness check failed: http://localhost:…`**
del judge ProjectEval → **score 0 sull'intero progetto**, indipendentemente dalla qualità del
resto. Nei report del judge si vedono **11 righe `pass:0, score:0`**.

**Implicazione:** il collo di bottiglia non è la "qualità" del codice ma la **runnability a
freddo** (migrate + homepage GET su DB vuoto, `ALLOWED_HOSTS`, porta, settings). Le regole
"contract-lock" nei prompt puntano già a questo, ma evidentemente il `coder` non le rispetta
in modo affidabile su MiniMax.

**Nota architetturale:** `coder.validate_framework_sanity` *già* esegue un migrate + homepage
smoke test (`app/tools/file_tools.py:157`). Ma il suo esito confluisce in `lint_results`/
`reviewer` come *advisory*: se il coding budget si esaurisce, il progetto viene finalizzato
comunque "rotto". Manca un **gate bloccante**: "non finalizzare un website finché la homepage
non risponde < 500".

---

### 🟠 C3 — Disallineamento tra test auto-generati e judge ufficiale

Il sistema spende 2 agenti (`test_writer`, `browser_test_writer`) per **scrivere ed eseguire
test propri**, ma lo scoring usa i **testcode ufficiali di ProjectEval**. I due insiemi non
coincidono:

- I log del judge sono pieni di `no such element: Unable to locate element` su selettori/XPath
  attesi (`//a[contains(text(),'Add Post')]`, `[id="purchase_link"]`,
  `[id="task_input_box_id"]`, `//button[@type='submit']`, …).
- Esempio progetto 8: i test *interni* riportano "27 failed, 21 passed" mentre il punteggio
  ufficiale è un altro → il lavoro di test interno **non predice** lo score.

**Conseguenza:** gran parte del tempo (e dei retry/token) va in test che **non muovono lo
score**. Il `reviewer` riceve feedback dai test sbagliati e guida il `coder` verso il bersaglio
sbagliato.

**Direzione di ottimizzazione:** allineare i test auto-generati al **contratto di selettori**
(`benchmark_contract` / `projecteval_parameter_values`) — già parzialmente previsto nei prompt
— oppure ridurre il peso dei test interni a favore di un check di contratto deterministico
(presenza dei selettori mappati nel DOM renderizzato).

---

### 🟠 C4 — I progetti che falliscono non convergono: bruciano sempre 4 iterazioni

Tutti i progetti `failed_bug` mostrano `iterations.coding = 4` (il massimo) e
`final_status = "running"`: il loop `reviewer ⇄ coder` **non converge**, si limita a esaurire
il budget. Combinato con C1 (retry lenti) e C3 (feedback sul bersaglio sbagliato), ogni
progetto fallito costa il massimo del tempo possibile senza guadagno.

**Ottimizzazione:** early-stop quando il reviewer non produce diff utili tra iterazioni
consecutive (feedback ripetuto / stesso set di errori), invece di insistere fino a 4.

---

### 🟠 C5 — Browser test (Selenium) lentissimi

I test browser auto-generati sono un sink di tempo: **progetto 7 → 369 s (6 min)**,
progetto 13 → 86 s. Per giunta spesso falliscono per problemi d'ambiente, non dell'app
(es. `ValueError: I/O operation on closed file` nel progetto 20).
Visto C3, il loro ROI sullo score è basso.

**Ottimizzazione:** ridurre/contingentare i browser test interni (timeout aggressivo, un solo
smoke di contratto) o eseguirli solo come gate di runnability, non come suite ampia.

---

### 🟡 C6 — Tool usage non agentico (rilevante per il requisito "gli agenti usano tool")

Gli LLM **non invocano tool** via function-calling: producono testo/JSON e il grafo esegue i
tool deterministicamente. `capabilities.supports_tools` è `true` solo per il profilo
`x_local_minimax_m27_tools`, ma **nessun ruolo del grafo lo usa** (tutti puntano a `*id001`,
`supports_tools: false`), tranne il `coder` che riferisce `*id002` ma comunque non fa
tool-calling reale nel codice.

**Implicazione:** se il requisito è "tool-calling agentico", oggi **non è soddisfatto**.
I 3 agenti pure-LLM (requirement_analyzer, architect, planning_reviewer) non toccano alcun
tool. Vedi §5 per la proposta.

---

### 🟡 C7 — Stabilità del provider locale

14 timeout e 9 API error verso MiniMax locale, più 10 fallimenti di parsing JSON nel
parameter-solver. Parte degli "errori" del sistema sono **infrastrutturali** (modello locale
instabile / lento), non logici. Vanno separati nelle metriche per non inquinare l'analisi di
qualità.

---

## 4. Quick wins (ordinati per rapporto impatto/sforzo)

| # | Intervento | Sforzo | Impatto |
|---|---|---|---|
| 1 | **C1**: su `MAX_TOKENS`, aumentare `max_tokens` invece di ripetere uguale; saltare retry a temp=0; ridurre sleep 120 s | Basso | **Alto** (ore di wall-clock + meno troncamenti) |
| 2 | **C2**: gate bloccante "homepage < 500" per i website prima della finalizzazione | Medio | **Alto** (recupera 7 progetti a score 0) |
| 3 | **C4**: early-stop loop coding su feedback ripetuto | Basso | Medio (tempo) |
| 4 | **C5**: timeout aggressivo + suite browser ridotta | Basso | Medio (tempo) |
| 5 | **C3**: allineare test interni ai selettori del contratto / contract-check deterministico | Medio | **Alto** (score) |
| 6 | **C7**: classificare errori provider vs logici nelle metriche | Basso | Medio (diagnosi) |
| 7 | Alzare `planning_reviewer.max_tokens` (4096 è troppo basso per un reasoning model) | Banale | Medio |

---

## 5. Nota sul tool-calling agentico (se il prof lo richiede esplicitamente)

Due strade:

1. **Documentale** — argomentare che i tool esistono e sono integrati nel workflow
   (vero, ma non è LLM-driven).
2. **Strutturale** — convertire almeno `coder`, `test_writer`/`reviewer` a veri tool LangGraph
   (`ToolNode` + `bind_tools`) esponendo `read_file`, `write_file`, `run_tests`,
   `django_check` come tool che **il modello sceglie** di chiamare in un loop ReAct.
   MiniMax dichiara già `supports_tools: true` nel profilo `_tools`, quindi è fattibile.

---

## 6. Appendice — evidenze dai log

- Retry `MAX_TOKENS`: `grep -c "hit MAX_TOKENS"` → **70**; `"exhausted MAX_TOKENS retry window"` → **18**.
- Reviewer è l'offender principale: 35 hit, 9 finestre esaurite.
- Judge readiness: `"Website home readiness check failed"` → **7**.
- Report judge con `score:0`: 11 righe `{'pass':0,'score':0,...}`.
- Selettori non trovati: numerose `Judge - WARNING - Testcode runtime exception: no such element …`.
- Timeout provider: 14; API error: 9; parameter-solver JSON parse failed: 10.
- Tutti i `failed_bug` hanno `iterations.coding = 4` (budget esaurito senza convergenza).

---

*Report generato da analisi statica + log della sessione `multi_agent_minimax2.7_1`. Nessuna
modifica applicata al codice o ai prompt.*
