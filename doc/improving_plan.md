# Improving Plan - sessione `clean_qwen3.5_27b_1`

## 1. Sintesi esecutiva

La sessione `clean_qwen3.5_27b_1` mostra che MASS e' gia' capace di generare progetti avviabili e spesso validati dai test interni, ma il punteggio ProjectEval resta instabile per tre ragioni principali:

1. i test locali verificano soprattutto il comportamento che gli agenti hanno gia' immaginato, non sempre il comportamento esatto atteso dal judge;
2. la conversione post-core verso `answer_parameter`, `answer_information` e `answer_startfile` e' utile ma ancora troppo affidata a inferenza LLM e normalizzazioni generiche;
3. i cicli di fix consumano molti token perche' `TestWriterAgent`, `BrowserTestWriterAgent` e `ReviewerAgent` ricevono snapshot molto ampi e vengono ripetuti anche quando basterebbe rieseguire test gia' generati o fare una riparazione mirata.

Evidenze principali:

- Nei 12 progetti locali della sessione, 6 risultano `completed/passed` nei test interni e 6 restano `running/failed_bug`.
- Nell'aggregato ufficiale ProjectEval sono presenti 20 progetti, con `judge_score` medio circa `0.417`, minimo `0.08`, massimo `1.0`.
- Progetti con test interni passati possono avere score ufficiale basso: ad esempio project 8 `0.1667`, project 9 `0.1538`, project 11 `0.375`.
- Progetti con test interni falliti possono comunque avere score ufficiale alto: project 1 `0.7273`, project 2 `1.0`, project 10 `0.5714`. Questo e' un segnale forte che alcuni test generati internamente sono piu' severi, fragili o disallineati rispetto al judge.
- Nei 12 progetti locali sono stati consumati circa `6.59M` token. I maggiori consumatori sono `BrowserTestWriterAgent` circa `2.30M`, `ReviewerAgent` circa `2.22M`, `TestWriterAgent` circa `0.96M`, `CoderAgent` circa `0.83M`.

La direzione consigliata e': trasformare MASS da workflow "generate -> self-test -> fix" a workflow "benchmark-contract -> implement -> deterministic validation -> judge-aligned parameterization", dove ogni agente usa tool espliciti e riceve contesto molto piu' piccolo ma piu' informativo.

## 2. Lettura della sessione

### 2.1 Cosa funziona

- Il ciclo `ArchitectAgent -> PlanningReviewerAgent -> ArchitectAgent` ha spesso intercettato problemi reali prima del coding: routing ambiguo, mancanza di migrazioni, test strategy, id stabili.
- La static analysis ha intercettato classi di problemi utili: sintassi Python, shape Django, migrazioni senza `__init__.py`, placeholder link, duplicate HTML id.
- I test dinamici e Selenium hanno trovato bug concreti: template syntax, missing middleware, errori di form, problemi di database, selettori instabili.
- Il post-core riesce a esportare i bundle ProjectEval e a riusare cache di workspace, parametri e startfile.

### 2.2 Cosa non funziona ancora abbastanza

- I test generati diventano parte del problema: project 6 ha avuto un browser test con `SyntaxError`; project 11 ha richiesto fix ai test stessi (`file: None`) invece che al progetto; project 10 ha avuto fixture con collisioni di `UserProfile`.
- Il reviewer a volte consiglia fix sui test generati quando il vero obiettivo dovrebbe essere massimizzare il judge ufficiale.
- Alcune implementazioni passano i test locali ma falliscono per selettori, testi, URL o stati applicativi attesi dal judge.
- L'uso di token cresce drasticamente nei progetti grandi: project 10 supera `1.12M` token, project 12 supera `1.26M`; in entrambi i casi `BrowserTestWriterAgent` e `ReviewerAgent` ricevono prompt enormi.
- La conversione post-core normalizza solo alcuni casi noti. Per esempio project 8 e' migliorato dopo la rigenerazione dei parametri da URL `http://example.com` a `http://127.0.0.1:8000/`, segno che il layer post-core incide direttamente sullo score.

## 3. Piano di miglioramento del workflow

### 3.1 Introdurre un `BenchmarkContractAgent`

Prima dell'architettura, aggiungere un agente leggero che trasformi `mission.testcode` e descrizione ProjectEval in un contratto compatto:

- pagine richieste;
- URL attesi;
- selettori richiesti, divisi per `id`, `name`, `class_name`, `xpath`, testo;
- input literal da usare nei form;
- output osservabili attesi;
- dipendenze di stato tra funzioni del judge;
- segnali di rischio, ad esempio login, admin Django, download, file upload, CRUD, database.

Output ideale: JSON strutturato, non prosa lunga. Questo contratto diventa il documento primario passato ad architect, coder, test writer, reviewer e parameter solver. Riduce ambiguita' e token.

### 3.2 Rafforzare il loop di planning

Il loop `Architect -> PlanningReviewer -> Architect` e' utile, ma dovrebbe diventare condizionale:

- Progetti semplici: 1 review obbligatoria, come ora.
- Progetti con rischio alto dal `BenchmarkContractAgent` (`auth`, `admin`, `CRUD multi-step`, `download`, `file upload`, `batch I/O`): fino a 2 review di planning.
- La seconda review non deve rileggere tutta la prosa; deve verificare solo una checklist di contratto:
  - ogni funzione del judge ha una route o entrypoint;
  - ogni parametro richiesto ha un elemento o valore implementabile;
  - lo stato necessario e' precreato o producibile via UI;
  - i nomi dei campi coincidono con id/name attesi;
  - esiste una strategia di bootstrap DB.

### 3.3 Separare fix del progetto da fix dei test locali

Attualmente il reviewer puo' portare il coder a modificare test generati, come nei project 10 e 11. Serve una policy:

- I test locali sono strumenti diagnostici, non artefatti da ottimizzare.
- Il coder puo' modificare test generati solo se il test e' sintatticamente invalido o impedisce la diagnosi.
- Se il test locale e' disallineato dal contratto ProjectEval, il reviewer deve marcarlo come `local_test_false_positive` e chiedere di aggiornare il test writer o ignorare quel test nel routing, non consumare un ciclo coder sul progetto.

### 3.4 Nuovo routing consigliato

Workflow proposto:

1. `RequirementAnalyzerAgent`
2. `BenchmarkContractAgent`
3. `ArchitectAgent`
4. `PlanningReviewerAgent`
5. `ArchitectAgent` solo se richiesto
6. `CoderAgent`
7. deterministic validators: syntax, Django smoke, DOM contract, route map, migration check
8. `TestWriterAgent` solo per rischi non coperti dai validator deterministic
9. `BrowserTestWriterAgent` solo per flussi browser critici
10. `ReviewerAgent`
11. `CoderAgent` per fix mirato
12. al massimo 3 cicli completi; oltre soglia, passare a `FailureTriageAgent`
13. post-core deterministic extraction + parameter solver solo per i casi non risolti deterministicamente

Il punto chiave e' spostare quanto piu' possibile da LLM-test/reviewer a validator deterministici, perche' sono piu' economici, ripetibili e vicini al contratto.

## 4. Guardrail benchmark nei prompt

Aggiungere a `architect.txt`, `coder.txt`, `reviewer.txt`, `test_writer.txt` e `browser_test_writer.txt` una sezione comune chiamata `Guardrail benchmark`.

Contenuto consigliato:

- Il judge interagisce con il progetto tramite selettori, URL, testo visibile, file generati e comandi di startup. Ogni requisito osservabile deve essere presente nel DOM o nel filesystem nel momento in cui il judge lo cerca.
- Se un parametro ProjectEval contiene `*_id`, usare esattamente quell'id se il valore e' noto; non sostituire con classi, data attributes o testo vicino.
- Se un parametro contiene `*_field`, `*_input`, `*_select`, il controllo deve avere sia `id` sia `name` coerenti, salvo richiesta contraria.
- Per Django auth, preferire gli id nativi `id_username`, `id_password`, `id_password1`, `id_password2` quando il judge sembra aspettarsi form standard.
- Per URL e navigazione, preferire route dedicate e server-rendered, non UI nascosta o JS-only.
- Per admin Django, se il judge usa `/admin/...`, configurare davvero admin, superuser/bootstrap oppure percorso equivalente se previsto dal benchmark.
- Per download/output file, usare nomi stabili e path prevedibili.
- Per batch program, messaggi di errore e nomi output devono combaciare letteralmente con il contratto; evitare sinonimi creativi.
- Non generare test locali che assumano valori diversi da quelli del contratto ProjectEval.

## 5. Tool per singolo agente

Il professore ha ragione: la differenza tra modello e agente deve essere esplicita nei tool. Proposta di toolset:

### 5.1 `RequirementAnalyzerAgent`

Tool:

- dataset reader: legge descrizione progetto, stack, livello, `mission.testcode`;
- schema extractor: produce lista normalizzata di requisiti;
- no filesystem write.

Output:

- requisiti concisi;
- assunzioni;
- rischi.

### 5.2 `BenchmarkContractAgent`

Tool:

- ProjectEval testcode parser;
- selector classifier (`id`, `name`, `class`, `xpath`, URL, text, file path);
- dependency graph builder tra funzioni del judge;
- literal value extractor per input e expected output.

Output:

- `benchmark_contract.json`;
- score di rischio.

### 5.3 `ArchitectAgent`

Tool:

- contract reader;
- route planner;
- data model planner;
- optional template skeleton planner.

Non dovrebbe scrivere codice. Deve produrre un piano breve, verificabile e mappato 1:1 al contratto.

### 5.4 `PlanningReviewerAgent`

Tool:

- contract coverage checker;
- route/selector checklist;
- risk checklist per Django/auth/admin/download/batch.

Output:

- `Approved` oppure diff di planning molto puntuale;
- niente prosa lunga se mancano solo 2-3 punti.

### 5.5 `CoderAgent`

Tool:

- `FileTool.write_files`;
- snapshot reader focalizzato;
- syntax validator;
- Django smoke validator (`migrate --noinput`, `Client().get('/')`);
- optional route introspection tool;
- optional DOM inspector statico sui template.

Policy:

- prima iterazione: scrive solo progetto;
- iterazioni successive: modifica solo file necessari;
- non deve scrivere test salvo richiesta esplicita o fix di test diagnostico rotto.

### 5.6 `StaticAnalysisNode`

Tool:

- AST parser;
- Django settings/urls validator;
- migration validator;
- template compile validator;
- DOM id/name/class scanner;
- contract coverage validator;
- dependency/import scanner.

Deve restare deterministico e produrre issue con codice macchina, file e fix hint.

### 5.7 `TestWriterAgent`

Tool:

- contract reader;
- test template library per Django/CLI;
- pytest runner;
- syntax precheck dei test generati.

Policy:

- generare pochi test, non un clone completo del judge;
- mai introdurre assunzioni non presenti nel contratto;
- se il test fallisce per errore del test, segnalarlo come `test_invalid`, non come bug del progetto.

### 5.8 `BrowserTestWriterAgent`

Tool:

- Selenium template library;
- live server manager robusto;
- DOM snapshot after navigation;
- screenshot-on-failure opzionale;
- pytest syntax precheck.

Policy:

- usare Selenium solo per flussi davvero browser-level;
- limitare a 3-6 test ad alto valore;
- non generare suite da centinaia di migliaia di token.

### 5.9 `ReviewerAgent`

Tool:

- failure classifier;
- focused file reader;
- test false-positive detector;
- contract diff viewer;
- issue prioritizer.

Output:

- massimo 5 fix richiesti;
- ogni fix deve indicare file, causa, modifica concreta;
- separare `project_bug`, `local_test_bug`, `parameter_bug`, `judge_alignment_risk`.

### 5.10 `ParameterSolverAgent`

Tool:

- generated project JSON reader;
- DOM parser/static selector extractor;
- URL resolver;
- XPath validator;
- deterministic parameter resolver;
- LLM fallback solo per parametri semanticamente ambigui.

Output:

- `answer_parameter.json`;
- confidence per parametro;
- lista parametri non verificati.

### 5.11 `ParameterRepairerAgent`

Tool:

- JSON schema validator;
- parameter schema repair;
- DOM existence checker;
- judge dry-run metadata reader.

Non deve solo riparare JSON: deve riparare valori impossibili, ad esempio URL non localhost, XPath non valido, id inesistente, classi con spazi.

## 6. Migliorare static analysis e test Selenium

### 6.1 Static analysis

Aggiungere controlli deterministici:

- template compile per tutte le view principali, non solo homepage;
- URL resolver: verifica che ogni route nel contratto risponda < 500;
- DOM contract scanner: per ogni parametro `*_id`, `*_name`, `*_class_name`, controlla presenza nei template o nel DOM renderizzato;
- Django auth/admin checker: se il contratto nomina admin o login standard, verifica `django.contrib.admin`, middleware, template id standard;
- migration completeness: `makemigrations --check --dry-run` o fallback che segnali modelli senza migration;
- form contract checker: id e name coerenti, opzioni select con value letterali;
- download checker: `href="#"`, route non esistente, filename instabile;
- batch checker: entrypoint, messaggi errore letterali, output filenames.

### 6.2 Test dinamici

I test dinamici devono diventare piu' piccoli e piu' contrattuali:

- un test startup;
- un test route map;
- un test DOM contract;
- 1-2 test di funzione core.

Non devono scrivere fixture troppo complesse quando il judge usa la UI. Nei project 10 e 12, molta fragilita' e' nata da fixture database e auth locali.

### 6.3 Test Selenium

Migliorie:

- syntax precheck immediato sui test generati prima di eseguirli;
- usare helper standard condivisi per avvio server, login, wait, teardown;
- fallire con messaggi compatti;
- non testare oltre il comportamento descritto dal contratto;
- salvare DOM snapshot minimale per failure (`current_url`, title, body text primi 2000 char, ids presenti).

Questo renderebbe il reviewer molto piu' economico: invece di leggere stdout enorme, riceverebbe una failure normalizzata.

## 7. Analisi post-core

### 7.1 Stato attuale

Il post-core fa quattro cose:

- converte `generated_project` in `answer_code.json`;
- inferisce `answer_startfile.json`;
- inferisce `answer_information.json`;
- genera o riusa `answer_parameter.json`, con LLM solver + repair + normalizzazione.

E' una buona base, ma non e' ancora il metodo migliore per ProjectEval perche':

- passa al parameter solver l'intero progetto JSON, spesso troppo grande;
- usa LLM anche quando i parametri sono ricavabili deterministicamente dal DOM o dai file;
- non assegna confidence per parametro;
- non verifica sistematicamente che ogni id/xpath/class/url esista davvero;
- `answer_information` usa `sys.executable` assoluto della macchina locale nei comandi. Funziona localmente, ma sarebbe piu' portabile usare comando relativo/ambiente del runner quando ProjectEval lo consente;
- la cache dei parametri puo' conservare valori vecchi o peggiori se il progetto cambia e `regenerate_parameters` e' false.

### 7.2 Metodo migliore proposto

Implementare un `ProjectEvalExportValidator` post-core:

1. esporta codice filtrato;
2. renderizza o analizza staticamente le pagine principali;
3. estrae automaticamente id, name, classi, href, testi, form, option value;
4. risolve deterministicamente i parametri:
   - URL: normalizzati a `http://127.0.0.1:8000/...`;
   - id/name/class: scelti solo se presenti;
   - XPath: validati con parser HTML;
   - expected text/output: da contratto o da esecuzione controllata;
5. usa LLM solo sui parametri non risolti;
6. salva `parameter_confidence.json`;
7. se confidence bassa, invoca un micro-fix: o corregge parametri, o segnala al coder che manca un elemento.

### 7.3 Validazione prima del judge

Prima di chiamare il judge ufficiale:

- eseguire `manage.py migrate --noinput`;
- avviare server;
- per ogni `test_url`, fare GET;
- per ogni id/name/class/xpath in `answer_parameter`, verificare presenza;
- per ogni download path, verificare route o filename;
- per batch, eseguire entrypoint con casi minimi di errore file mancante.

Questo non sostituisce il judge, ma intercetta parametri impossibili a costo basso.

## 8. Riduzione drastica dei token

Obiettivo realistico: ridurre del 50-70% i token senza perdere performance.

Interventi prioritari:

1. **Contract-first context**: passare agli agenti il `benchmark_contract.json` compatto invece di tutta la descrizione + testcode + progetto quando non serve.
2. **Snapshot differenziali**: dopo la prima iterazione, passare solo file toccati, file falliti e route/template collegati. Non passare test file generati al browser writer se non sono necessari.
3. **Test writer single-shot**: generare test dinamici e browser una volta sola; nelle iterazioni successive rieseguire gli stessi test, salvo cambio sostanziale del contratto.
4. **Failure summaries normalizzate**: comprimere pytest/Selenium output in JSON con top 5 failure, file, linea, eccezione, selector, current URL. Il reviewer non deve leggere 100k token di stdout.
5. **Reviewer micro-prompt**: reviewer riceve contratto, failure summary e soli file coinvolti. Limite massimo di file e caratteri.
6. **No repeated full architecture**: planning reviewer produce patch/checklist, non una seconda architettura lunga; architect revision deve modificare solo sezioni richieste.
7. **Deterministic parameter extraction**: riduce prompt enormi al parameter solver.
8. **Caching semantic snapshots**: salvare hash dei file e riusare DOM/route analysis se invariati.
9. **Budget-aware routing**: se un progetto supera soglia token o cicli, passare a triage deterministico invece di altri LLM round completi.

Dato il profilo token osservato, la prima area da colpire e' `BrowserTestWriterAgent + ReviewerAgent`: insieme valgono circa `4.51M` token sui 12 progetti locali, cioe' circa il 68% del totale.

## 9. Roadmap operativa

### Fase 1 - Basso rischio, alto impatto

- Aggiungere sezione `Guardrail benchmark` ai prompt.
- Aggiungere syntax precheck per test generati.
- Normalizzare failure pytest/Selenium in JSON compatto.
- Limitare il browser writer a massimo 6 test.
- Rigenerare parametri quando hash del progetto cambia.

### Fase 2 - Contract e validator

- Implementare `BenchmarkContractAgent`.
- Implementare DOM contract scanner.
- Integrare route map e form checker nella static analysis.
- Far leggere al reviewer il contract diff invece dello stdout completo.

### Fase 3 - Post-core robusto

- Implementare deterministic parameter resolver.
- Aggiungere confidence e validator di `answer_parameter`.
- Fare pre-judge dry-run su URL/selettori/startfile.
- Rendere `answer_information` piu' portabile e meno dipendente da path assoluti.

### Fase 4 - Workflow adattivo

- Routing basato su rischio e confidence.
- Seconda iterazione di planning solo per progetti complessi.
- `FailureTriageAgent` dopo 3 cicli o oltre soglia token.
- Dashboard per confrontare test interni vs judge ufficiale e individuare falsi positivi/negativi.

## 10. Metriche da monitorare

- `judge_score` per progetto e per categoria di benchmark.
- delta tra test interni e score ufficiale.
- percentuale di parametri risolti deterministicamente.
- confidence media dei parametri.
- token per agente e per progetto.
- numero di cicli coder/reviewer.
- failure class: `project_bug`, `local_test_bug`, `parameter_bug`, `workflow_bug`.
- tempo post-core e numero di parametri impossibili intercettati prima del judge.

## 11. Conclusione

La sessione suggerisce che aggiungere semplicemente piu' iterazioni `coder -> reviewer` non basta. Aiuta nei bug runtime semplici, ma diventa costoso e puo' inseguire test locali disallineati. La leva piu' forte e' introdurre un contratto ProjectEval esplicito, validarlo deterministicamente lungo tutto il workflow e rendere il post-core molto piu' verificabile.

La seconda leva e' economica: ridurre il contesto che gira tra test writer, browser writer e reviewer. Il sistema non deve leggere ogni volta l'intero progetto e lunghi stdout; deve leggere il contratto, una failure normalizzata e i pochi file responsabili.
