from __future__ import annotations
import html
import importlib
import json
import os
import time
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import app.ui_backend.benchmark_runner as benchmark_runner_module
import app.ui_backend.config_manager as config_manager_module
import app.ui_backend.models as models_module
from app.ui_backend.projecteval_data import load_projecteval_projects
from app.ui_backend.session_manager import SessionManager
from app.ui_backend.theme import init_page
models_module = importlib.reload(models_module)
config_manager_module = importlib.reload(config_manager_module)
benchmark_runner_module = importlib.reload(benchmark_runner_module)
BenchmarkRequest = models_module.BenchmarkRequest
RoleSettings = models_module.RoleSettings
BenchmarkRunner = benchmark_runner_module.BenchmarkRunner
BenchmarkRunHandle = benchmark_runner_module.BenchmarkRunHandle
ConfigManager = config_manager_module.ConfigManager
init_page(page_title='Benchmark', page_icon=':material/play_arrow:')
BENCHMARK_RUNNER_CACHE_VERSION = 'workflow_resume_v1'

@st.cache_resource
def get_benchmark_runner(cache_version: str):
    _ = cache_version
    sm = SessionManager()
    cm = ConfigManager()
    return BenchmarkRunner(session_manager=sm, config_manager=cm)
benchmark_runner = get_benchmark_runner(BENCHMARK_RUNNER_CACHE_VERSION)
session_manager = benchmark_runner.session_manager
config_manager = benchmark_runner.config_manager
active_anywhere = benchmark_runner.get_any_active_run()
if active_anywhere and 'selected_session' not in st.session_state:
    st.session_state['selected_session'] = active_anywhere.session_name
    st.info(f'✨ Rilevato benchmark attivo per la sessione: `{active_anywhere.session_name}`. Ripristino in corso...')
projects = load_projecteval_projects()
project_ids = [item['project_id'] for item in projects]
ROLE_WIDGET_FIELDS = ('model', 'temp', 'tokens')
AGENT_EVENT_STDOUT_PREFIX = '__MASS_AGENT_EVENT__ '
MONITOR_REFRESH_SECONDS = 2.0

def collect_config_errors(*, role_defaults: dict[str, dict[str, object]], global_model: str, role_settings: dict[str, RoleSettings]) -> list[str]:
    errors: list[str] = []
    if global_model.strip().startswith('mock-'):
        non_mock_roles = [role_name for role_name, defaults in role_defaults.items() if str(defaults.get('provider', '')).lower() != 'mock']
        if non_mock_roles:
            errors.append('Il modello globale inizia con `mock-`, ma il base config usa provider reali per: ' + ', '.join(non_mock_roles) + '.')
    for role_name, settings in role_settings.items():
        provider = str(role_defaults.get(role_name, {}).get('provider', '')).lower()
        model_name = settings.model.strip()
        if not model_name:
            errors.append(f'Il ruolo `{role_name}` ha un model vuoto.')
        if provider != 'mock' and model_name.startswith('mock-'):
            errors.append(f'Il ruolo `{role_name}` usa provider `{provider}` ma model `{model_name}`, che sembra un mock non valido.')
    return errors
st.title('Benchmark ProjectEval')
session_name = st.sidebar.text_input('Sessione', value=st.session_state.get('selected_session', 'projecteval-session'))
if st.sidebar.button('Crea / Aggiorna sessione') and session_name.strip():
    session_manager.create_session(session_name.strip())
    st.session_state['selected_session'] = session_name.strip()
session_name = session_name.strip() or 'projecteval-session'
session_manager.create_session(session_name)
st.session_state['selected_session'] = session_name
models_config_options = config_manager.list_model_config_paths()
default_base_config = st.session_state.get('benchmark_base_models_config_path') or os.getenv('MASS_MODELS_CONFIG', 'configs/models_nvidia_deepseek_v4_pro.yaml')
base_models_config_path = st.selectbox('Base models config', options=models_config_options, index=models_config_options.index(default_base_config) if default_base_config in models_config_options else 0)
role_defaults = config_manager.load_role_defaults(base_models_config_path)

def sync_role_widget_defaults(*, force: bool=False) -> None:
    previous_base_config = st.session_state.get('benchmark_base_models_config_path')
    base_config_changed = previous_base_config != base_models_config_path
    try:
        base_config_mtime = os.path.getmtime(base_models_config_path)
    except OSError:
        base_config_mtime = None
    previous_base_config_mtime = st.session_state.get('benchmark_base_models_config_mtime')
    base_config_file_changed = previous_base_config_mtime != base_config_mtime
    missing_keys = any((f'model_{role_name}' not in st.session_state for role_name in role_defaults.keys()))
    if not force and (not base_config_changed) and (not base_config_file_changed) and (not missing_keys):
        return
    for role_name, defaults in role_defaults.items():
        st.session_state[f'model_{role_name}'] = str(defaults['model'])
        st.session_state[f'temp_{role_name}'] = float(defaults['temperature'])
        st.session_state[f'tokens_{role_name}'] = int(defaults['max_tokens'])
    st.session_state['benchmark_base_models_config_path'] = base_models_config_path
    st.session_state['benchmark_base_models_config_mtime'] = base_config_mtime
sync_role_widget_defaults()
left, right = st.columns([2, 1])
with left:
    global_model = st.text_input('Modello globale', value='', help='Se lo compili, sovrascrive il model di tutti gli agenti per questa run. Lascia vuoto per usare i model del file base.')
    selected_project_ids = st.multiselect('Progetti', options=project_ids, default=project_ids[:3])
with right:
    core_mode_label = st.selectbox('Core', options=['Multi-agent MASS', 'Single agent baseline', 'opencode'], index=0, help='Scegli il framework di generazione. Export, parametri e judge restano uguali indipendentemente dal core scelto.')
    if core_mode_label == 'Single agent baseline':
        core_mode = 'single_agent'
    elif core_mode_label == 'opencode':
        core_mode = 'opencode'
    else:
        core_mode = 'multi_agent'
    single_agent_iterations = st.number_input('Iterazioni single agent', min_value=1, max_value=8, value=4, step=1, disabled=core_mode != 'single_agent', help='Numero massimo di giri generate -> validation -> repair per il baseline single-agent.')
    opencode_model_presets = {'MiniMax-M2.7 — locale vLLM (:8004)': 'local-minimax//mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7', 'Qwen3.6-27B — locale vLLM (:8003)': 'local-qwen//home/G.DAMBROSIO65/hf_cache/models--Qwen--Qwen3.6-27B-local', 'MiniMax-M2.7 — NVIDIA API': 'nvidia/minimaxai/minimax-m2.7', 'Custom…': ''}
    opencode_model_choice = st.selectbox('opencode model', options=list(opencode_model_presets.keys()), index=0, disabled=core_mode != 'opencode', help="Modello usato dal CLI opencode. Scegli un preset (Qwen / MiniMax) o 'Custom…' per inserirlo a mano.", key='opencode_model_choice')
    if opencode_model_choice == 'Custom…':
        opencode_model = st.text_input('opencode model (custom)', value=st.session_state.get('opencode_model_custom', 'local-minimax//mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7'), disabled=core_mode != 'opencode', help='Formato provider/model, es. local-minimax//mnt/beegfs/g.dambrosio65/models/MiniMax-M2.7.', key='opencode_model_custom')
    else:
        opencode_model = opencode_model_presets[opencode_model_choice]
        st.caption(f'`{opencode_model}`')
    opencode_timeout = st.number_input('opencode timeout (s)', min_value=60, max_value=3600, value=600, step=60, disabled=core_mode != 'opencode', help='Secondi massimi per progetto prima che opencode venga interrotto.')
    level = st.selectbox('Livello', options=[1, 2, 3], index=1)
    mode = st.selectbox('Mode', options=['direct', 'cascade'], index=0)
    run_judge = st.checkbox('Esegui judge ufficiale', value=True)
    run_static_analysis = st.checkbox('Esegui analisi statica', value=True)
    run_dynamic_analysis = st.checkbox('Esegui analisi dinamica (test + Selenium)', value=True, disabled=core_mode in {'single_agent', 'opencode'}, help='Non disponibile nel baseline single-agent né con opencode. Restano attivi syntax/framework/static checks.')
    if core_mode in {'single_agent', 'opencode'}:
        run_dynamic_analysis = False
    use_agentic_tools = st.checkbox('Agenti agentici (tool-calling LLM)', value=True, disabled=core_mode in {'single_agent', 'opencode'}, help='Reviewer e coder usano i tool via function-calling (read/write/grep/validate/test) invece di ricevere snapshot fissi. Richiede un server con tool-calling abilitato (es. Qwen 3.6 con --tool-call-parser qwen3_coder).')
    if core_mode in {'single_agent', 'opencode'}:
        use_agentic_tools = False
    agentic_context_compaction = st.checkbox('Compattazione contesto agentico', value=False, disabled=core_mode in {'single_agent', 'opencode'} or not use_agentic_tools, help="Nel loop dei tool elide i payload write_file superati e gli output dei tool superati (pytest/validate/grep) e inietta un manifesto del workspace, per evitare l'esplosione del contesto sui progetti grandi. Lossless: tutto resta ri-leggibile via read_file. Consigliata sui progetti con molti file/iterazioni.")
    if core_mode in {'single_agent', 'opencode'} or not use_agentic_tools:
        agentic_context_compaction = False
    reuse_completed = st.checkbox('Riusa workspaces già pronti per export/judge', value=True)
    resume_interrupted = st.checkbox('Riprendi generazioni interrotte', value=True, disabled=core_mode != 'multi_agent', help='Solo per multi-agent MASS: riprende dal workflow_checkpoint.json se disponibile. Non applicabile a single_agent o opencode.')
    if core_mode != 'multi_agent':
        resume_interrupted = False
    post_core_only = st.checkbox('Solo parametri + judge', value=False, help='Usa solo un progetto già generato nel workspace: non rilancia coder, analisi o test interni.')
    regenerate_parameters = st.checkbox('Rigenera parametri ProjectEval', value=False, help='Ignora projecteval_parameter_values.json già presente e rigenera i parametri prima del judge.')
actions_left, actions_right = st.columns([1, 3])
if actions_left.button('Ricarica default ruoli'):
    sync_role_widget_defaults(force=True)
    st.rerun()
actions_right.caption('I campi per agente vengono riallineati automaticamente quando cambi il file base.')
with st.expander('Config per agente', expanded=False):
    if core_mode == 'opencode':
        st.info('Nel core opencode la generazione è affidata al CLI opencode. I ruoli qui configurati vengono usati solo per `parameter_solver` e `parameter_repairer` (export ProjectEval).')
    elif core_mode == 'single_agent':
        st.info("Nel core single-agent la generazione usa il ruolo `coder`; `parameter_solver` e `parameter_repairer` restano usati per l'export ProjectEval.")
    role_settings: dict[str, RoleSettings] = {}
    for role_name, defaults in role_defaults.items():
        c1, c2, c3 = st.columns([2, 1, 1])
        model = c1.text_input(f'{role_name} model', key=f'model_{role_name}')
        temperature = c2.number_input(f'{role_name} temp', min_value=0.0, max_value=2.0, step=0.1, key=f'temp_{role_name}')
        max_tokens = c3.number_input(f'{role_name} max_tokens', min_value=256, max_value=131072, step=256, key=f'tokens_{role_name}')
        role_settings[role_name] = RoleSettings(role=role_name, model=model, temperature=float(temperature), max_tokens=int(max_tokens))
config_errors = collect_config_errors(role_defaults=role_defaults, global_model=global_model, role_settings=role_settings)
for error in config_errors:
    st.error(error)
session_detail = session_manager.get_session_detail(session_name)
resumable_projects = [project for project in session_detail.get('projects', []) if project.get('final_status') == 'interrupted_resumable' and project.get('workflow_checkpoint')]
if resumable_projects:
    with st.expander('Generazioni riprendibili', expanded=True):
        rows = []
        for project in resumable_projects:
            checkpoint = project.get('workflow_checkpoint') if isinstance(project.get('workflow_checkpoint'), dict) else {}
            rows.append({'project_id': project.get('project_id'), 'resume_node': checkpoint.get('resume_node'), 'next_iteration': checkpoint.get('next_iteration'), 'last_completed_node': checkpoint.get('last_completed_node'), 'planning_iteration': checkpoint.get('planning_iteration'), 'coding_iteration': checkpoint.get('coding_iteration'), 'updated_at': checkpoint.get('updated_at')})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption('Se avvii un benchmark includendo questi progetti e lasci attiva la ripresa, il core multi-agent riparte dal nodo indicato.')
with st.expander('🛠️ Gestione Avanzata Sessione'):
    st.markdown('Usa questa sezione per resettare progetti che sono andati male o che vuoi rieseguire da zero.')
    reset_project_ids = {str(project_id) for project_id in session_detail.get('results', {}).get('reset_projects', {})}
    existing_projects = [project for project in session_detail.get('projects', []) if str(project.get('project_id')) not in reset_project_ids]
    if not existing_projects:
        st.info('Nessun progetto ancora eseguito in questa sessione.')
    else:
        project_options = [f"{p['project_id']} - {p['final_status']} (Test: {p['test_status']})" for p in existing_projects]
        to_reset = st.multiselect('Seleziona i progetti da cancellare:', project_options)
        if st.button('🔄 Resetta progetti selezionati', type='secondary'):
            if to_reset:
                ids_to_del = [opt.split(' - ')[0] for opt in to_reset]
                session_manager.delete_projects(session_name, ids_to_del)
                st.success(f'Progetti {ids_to_del} resettati con successo!')
                time.sleep(1)
                st.rerun()
            else:
                st.warning('Seleziona almeno un progetto da resettare.')

def render_monitoring_ui(handle: BenchmarkRunHandle):
    status = st.empty()
    progress = st.empty()
    summary_metrics = st.empty()
    timeline_area = st.empty()
    log_area = st.empty()
    agent_panel_area = st.empty()
    collected = handle.get_history()
    selected_project_ids = handle.request.project_ids
    selected_set = set(selected_project_ids)
    while True:
        new_events = handle.drain_events()
        if new_events:
            collected.extend(new_events)
        session_state = session_manager.get_session_detail(handle.session_name, sync_workspace=False)
        selected_projects = [project for project in session_state.get('projects', []) if str(project.get('project_id')) in selected_set]
        selected_completed = sum((1 for project in selected_projects if project.get('final_status') == 'completed'))
        progress_value = min(selected_completed / max(len(selected_project_ids), 1), 1.0)
        if handle.status in {'queued', 'running'}:
            status.info(f'Benchmark `{handle.run_id}` in esecuzione. PID: {handle.process_id}')
        elif handle.status == 'completed':
            status.success(f'Benchmark completato con return code {handle.returncode}.')
        else:
            status.error(f'Benchmark terminato con stato: {handle.status}. Errore: {handle.error}')
        progress.progress(progress_value, text=f'Completati {selected_completed} / {len(selected_project_ids)}')
        rate_limit_events = [event for event in collected if event['event_type'] in {'warning', 'retry'}]
        current_completed = sum((1 for p in selected_projects if p.get('final_status') == 'completed'))
        current_failed_val = sum((1 for p in selected_projects if p.get('validation_status') == 'failed'))
        current_waiting = max(len(selected_project_ids) - (current_completed + current_failed_val), 0)
        with summary_metrics.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric('Completati', current_completed)
            c2.metric('In attesa', current_waiting)
            c3.metric('Validation fail', current_failed_val)
            c4.metric('Rate limit', len(rate_limit_events))
        display_events = expand_agent_events(collected)
        timeline_area.empty()
        recent_logs = '\n'.join((str(event['content']) for event in collected[-40:] if event['event_type'] == 'log' and (not str(event.get('content', '')).lstrip().startswith(AGENT_EVENT_STDOUT_PREFIX))))
        log_area.code(recent_logs or 'In attesa di log...', language=None)
        render_agent_browser_panel(agent_panel_area, display_events, selected_set)
        if handle.status not in {'queued', 'running'}:
            break
        time.sleep(MONITOR_REFRESH_SECONDS)

def shorten_live_text(value: object, *, limit: int=40000) -> str:
    text = '' if value is None else str(value)
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit] + f'\n\n[... testo abbreviato nella vista live: {omitted} caratteri non mostrati ...]'

def parse_agent_event_from_log_content(content: object) -> dict[str, object] | None:
    text = str(content or '').lstrip()
    if not text.startswith(AGENT_EVENT_STDOUT_PREFIX):
        return None
    raw_payload = text[len(AGENT_EVENT_STDOUT_PREFIX):].strip()
    try:
        import json
        payload = json.loads(raw_payload)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    metadata = payload.get('metadata')
    if not isinstance(metadata, dict):
        metadata = {}
    return {'agent_name': str(payload.get('agent_name') or 'agent'), 'event_type': str(payload.get('event_type') or 'event'), 'content': str(payload.get('content') or ''), 'timestamp': str(payload.get('timestamp') or ''), 'metadata': metadata}

def expand_agent_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    expanded: list[dict[str, object]] = []
    for event in events:
        parsed = parse_agent_event_from_log_content(event.get('content')) if event.get('event_type') == 'log' else None
        expanded.append(parsed or event)
    return expanded

def agent_event_label(agent_name: object, project_id: object, role: object, iteration: int | None) -> str:
    agent = str(agent_name or '')
    project = str(project_id or '?')
    if agent == 'RequirementAnalyzerAgent':
        return f'📋 Requirement analysis · project {project}'
    if agent == 'ArchitectAgent':
        return f'🏗️ Architecture iteration {iteration or 1} · project {project}'
    if agent == 'PlanningReviewerAgent':
        return f'🔎 Planning review · project {project}'
    if agent == 'CoderAgent':
        return f'💻 Coding iteration {iteration or 1} · project {project}'
    if agent == 'ReviewerAgent':
        return f'🧪 Reviewer checking implementation · project {project}'
    if agent == 'TestWriterAgent':
        return f'📝 Dynamic generated tests · project {project}'
    if agent == 'BrowserTestWriterAgent':
        return f'🌐 Selenium browser tests · project {project}'
    if agent == 'OpenCodeAgent':
        return f'🤖 opencode generation · project {project}'
    if agent == 'static_analysis':
        return f'🧭 Static code analysis · project {project}'
    return f"{agent or role or 'Agent'} · project {project}"

def collect_agent_interactions(events: list[dict[str, object]], selected_project_ids: set[str]) -> list[dict[str, object]]:
    interactions: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    prompt_counts: dict[tuple[str, str], int] = {}
    for event in events:
        event_type = str(event.get('event_type', ''))
        if event_type not in {'prompt', 'output', 'end'}:
            continue
        metadata = event.get('metadata')
        if not isinstance(metadata, dict):
            metadata = {}
        project_id = metadata.get('project_id')
        if project_id and str(project_id) not in selected_project_ids:
            continue
        if event_type == 'prompt':
            agent_name = event.get('agent_name', 'agent')
            project_key = str(project_id or '')
            count_key = (str(agent_name), project_key)
            prompt_counts[count_key] = prompt_counts.get(count_key, 0) + 1
            interaction_id = f'agent-{len(interactions) + 1}'
            system_prompt = str(metadata.get('system_prompt') or '')
            user_prompt = str(metadata.get('user_prompt') or event.get('content') or '')
            current = {'id': interaction_id, 'agent_name': agent_name, 'role': metadata.get('role', ''), 'project_id': project_id, 'iteration': prompt_counts[count_key], 'timestamp': event.get('timestamp', ''), 'prompt_path': metadata.get('prompt_path', ''), 'system_prompt': system_prompt, 'user_prompt': user_prompt, 'response_text': '', 'finish_reason': '', 'duration_ms': None, 'usage': {}, 'completed': False}
            current['label'] = agent_event_label(current['agent_name'], current['project_id'], current['role'], int(current['iteration']))
            interactions.append(current)
        elif event_type == 'output':
            if current is None:
                interaction_id = f'agent-{len(interactions) + 1}'
                current = {'id': interaction_id, 'agent_name': event.get('agent_name', 'agent'), 'role': metadata.get('role', ''), 'project_id': project_id, 'iteration': 1, 'timestamp': event.get('timestamp', ''), 'prompt_path': '', 'system_prompt': '', 'user_prompt': '', 'response_text': '', 'finish_reason': '', 'duration_ms': None, 'usage': {}, 'completed': False}
                current['label'] = agent_event_label(current['agent_name'], current['project_id'], current['role'], 1)
                interactions.append(current)
            current['response_text'] = str(event.get('content') or '')
            current['finish_reason'] = metadata.get('finish_reason', '')
            current['duration_ms'] = metadata.get('duration_ms')
            current['usage'] = metadata.get('usage') if isinstance(metadata.get('usage'), dict) else {}
        elif event_type == 'end' and current is not None:
            current['completed'] = True
            current['finish_reason'] = metadata.get('finish_reason', current.get('finish_reason', ''))
            current['duration_ms'] = metadata.get('duration_ms', current.get('duration_ms'))
    return interactions

def timeline_event_allowed(event: dict[str, object], selected_project_ids: set[str]) -> bool:
    metadata = event.get('metadata')
    if not isinstance(metadata, dict):
        metadata = {}
    project_id = metadata.get('project_id')
    return not project_id or str(project_id) in selected_project_ids

def collect_timeline_items(events: list[dict[str, object]], selected_project_ids: set[str]) -> list[dict[str, object]]:
    prompt_counts: dict[tuple[str, str], int] = {}
    items: list[dict[str, object]] = []
    interaction_index = 0
    for event in events:
        event_type = str(event.get('event_type', ''))
        if not timeline_event_allowed(event, selected_project_ids):
            continue
        metadata = event.get('metadata')
        if not isinstance(metadata, dict):
            metadata = {}
        timestamp = str(event.get('timestamp') or '')
        if event_type == 'prompt':
            interaction_index += 1
            interaction_id = f'agent-{interaction_index}'
            agent_name = event.get('agent_name', 'agent')
            project_id = metadata.get('project_id')
            count_key = (str(agent_name), str(project_id or ''))
            prompt_counts[count_key] = prompt_counts.get(count_key, 0) + 1
            label = agent_event_label(agent_name, project_id, metadata.get('role', ''), prompt_counts[count_key])
            items.append({'kind': 'agent', 'id': interaction_id, 'timestamp': timestamp, 'label': label})
        elif event_type in {'milestone', 'project_status', 'warning', 'retry', 'start', 'end', 'error'}:
            items.append({'kind': 'event', 'timestamp': timestamp, 'label': str(event.get('content') or '')})
    return items

def render_agent_browser_panel(placeholder, events: list[dict[str, object]], selected_project_ids: set[str]) -> None:
    interactions = collect_agent_interactions(events, selected_project_ids)
    timeline_items = collect_timeline_items(events, selected_project_ids)
    browser_interactions: list[dict[str, object]] = []
    for interaction in interactions:
        prompt_bits = []
        system_prompt = interaction.get('system_prompt')
        user_prompt = interaction.get('user_prompt')
        if system_prompt:
            prompt_bits.append('### System prompt\n' + str(system_prompt))
        if user_prompt:
            prompt_bits.append('### User/context prompt\n' + str(user_prompt))
        usage = interaction.get('usage')
        meta_parts = []
        if interaction.get('finish_reason'):
            meta_parts.append(f"finish_reason={interaction['finish_reason']}")
        if interaction.get('duration_ms') is not None:
            meta_parts.append(f"duration_ms={interaction['duration_ms']}")
        if isinstance(usage, dict) and usage:
            meta_parts.append('usage=' + str(usage))
        browser_interactions.append({'id': interaction.get('id'), 'label': interaction.get('label') or interaction.get('agent_name') or 'Agent', 'role': interaction.get('role') or '', 'status': 'completato' if interaction.get('completed') else 'in corso', 'prompt': shorten_live_text('\n\n'.join(prompt_bits) or 'Prompt non disponibile.'), 'response': shorten_live_text(str(interaction.get('response_text') or 'In attesa della risposta del modello...')), 'meta': '; '.join(meta_parts)})
    payload = {'timeline': timeline_items, 'interactions': browser_interactions, 'defaultId': browser_interactions[-1]['id'] if browser_interactions else None}
    escaped_payload = html.escape(json.dumps(payload, ensure_ascii=False))
    component_html = f'\n<div id="agent-browser-root" data-payload="{escaped_payload}">\n  <style>\n    html, body {{\n      background: transparent;\n      color: #e8edf2;\n    }}\n    #agent-browser-root {{\n      color: #e8edf2;\n      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;\n    }}\n    #agent-browser-root,\n    #agent-browser-root * {{\n      box-sizing: border-box;\n    }}\n    .ab-title {{\n      color: #f4f7fb;\n      font-weight: 700;\n      font-size: 1rem;\n      margin: 0 0 .55rem 0;\n    }}\n    .ab-timeline {{\n      max-height: 260px;\n      overflow-y: auto;\n      padding: .75rem 1rem;\n      border: 1px solid rgba(155, 176, 196, .36);\n      border-radius: 8px;\n      background: #111821;\n      margin-bottom: 1rem;\n    }}\n    .ab-row {{\n      display: block;\n      width: 100%;\n      background: transparent;\n      border: 0;\n      color: #dbe5ef;\n      text-align: left;\n      padding: .18rem 0;\n      margin: 0 0 .25rem 0;\n      font: inherit;\n    }}\n    .ab-row.agent {{\n      cursor: pointer;\n      color: #7dd3c7;\n      text-decoration: underline;\n      text-underline-offset: 2px;\n    }}\n    .ab-row.agent.active {{\n      color: #a7f3d0;\n      font-weight: 700;\n    }}\n    .ab-time {{\n      color: #9fb1c2;\n      margin-right: .25rem;\n    }}\n    .ab-caption {{\n      color: #b8c4d0;\n      font-size: .92rem;\n      margin: 0 0 .75rem 0;\n    }}\n    .ab-follow {{\n      color: #0b1118;\n      background: #7dd3c7;\n      border: 0;\n      border-radius: 8px;\n      cursor: pointer;\n      font-weight: 700;\n      padding: .35rem .65rem;\n      margin: -.2rem 0 .85rem 0;\n    }}\n    .ab-follow:hover {{\n      background: #a7f3d0;\n    }}\n    .ab-grid {{\n      display: grid;\n      grid-template-columns: repeat(2, minmax(0, 1fr));\n      gap: 1rem;\n    }}\n    .ab-pane-title {{\n      color: #f4f7fb;\n      font-weight: 700;\n      margin-bottom: .35rem;\n    }}\n    .ab-meta {{\n      color: #b8c4d0;\n      font-size: .82rem;\n      line-height: 1.35;\n      min-height: 1.15rem;\n      max-height: 4.6rem;\n      overflow: auto;\n      margin: -.15rem 0 .45rem 0;\n    }}\n    .ab-box {{\n      white-space: pre-wrap;\n      overflow: auto;\n      height: 640px;\n      padding: .75rem;\n      color: #e8edf2;\n      border: 1px solid rgba(155, 176, 196, .36);\n      border-radius: 8px;\n      background: #111821;\n      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;\n      font-size: .88rem;\n      line-height: 1.45;\n    }}\n    .ab-timeline::-webkit-scrollbar,\n    .ab-box::-webkit-scrollbar,\n    .ab-meta::-webkit-scrollbar {{\n      width: 10px;\n      height: 10px;\n    }}\n    .ab-timeline::-webkit-scrollbar-thumb,\n    .ab-box::-webkit-scrollbar-thumb,\n    .ab-meta::-webkit-scrollbar-thumb {{\n      background: #475569;\n      border-radius: 8px;\n    }}\n    .ab-timeline::-webkit-scrollbar-track,\n    .ab-box::-webkit-scrollbar-track,\n    .ab-meta::-webkit-scrollbar-track {{\n      background: #0b1118;\n    }}\n    @media (max-width: 800px) {{\n      .ab-grid {{\n        grid-template-columns: 1fr;\n      }}\n    }}\n  </style>\n  <div class="ab-title">Timeline consultabile</div>\n  <div class="ab-timeline" id="ab-timeline"></div>\n  <div class="ab-title">Prompt e risposta agente</div>\n  <div class="ab-caption" id="ab-caption">In attesa della prima richiesta a un agente...</div>\n  <button type="button" class="ab-follow" id="ab-follow-latest">Segui ultimo agente</button>\n  <div class="ab-grid">\n    <div>\n      <div class="ab-pane-title">Prompt inviato</div>\n      <div class="ab-box" id="ab-prompt">In attesa...</div>\n    </div>\n    <div>\n      <div class="ab-pane-title" id="ab-response-title">Risposta modello</div>\n      <div class="ab-meta" id="ab-response-meta"></div>\n      <div class="ab-box" id="ab-response">In attesa...</div>\n    </div>\n  </div>\n</div>\n<script>\n(function() {{\n  const root = document.getElementById("agent-browser-root");\n  const payload = JSON.parse(root.dataset.payload || "{{}}");\n  const interactions = payload.interactions || [];\n  const byId = new Map(interactions.map((item) => [item.id, item]));\n  const storageKey = "mass-benchmark-agent-browser-selected";\n  const storedId = window.localStorage.getItem(storageKey);\n  let selectedId = storedId && byId.has(storedId) ? storedId : payload.defaultId;\n  const timeline = document.getElementById("ab-timeline");\n  const caption = document.getElementById("ab-caption");\n  const promptBox = document.getElementById("ab-prompt");\n  const responseTitle = document.getElementById("ab-response-title");\n  const responseMeta = document.getElementById("ab-response-meta");\n  const responseBox = document.getElementById("ab-response");\n  const followLatest = document.getElementById("ab-follow-latest");\n\n  function text(value) {{\n    return value == null || value === "" ? "" : String(value);\n  }}\n\n  function renderSelected(id) {{\n    selectedId = id || selectedId;\n    if (selectedId) {{\n      window.localStorage.setItem(storageKey, selectedId);\n    }}\n    const item = byId.get(selectedId);\n    for (const button of timeline.querySelectorAll("button[data-agent-id]")) {{\n      button.classList.toggle("active", button.dataset.agentId === selectedId);\n    }}\n    if (!item) {{\n      caption.textContent = "In attesa della prima richiesta a un agente...";\n      promptBox.textContent = "In attesa...";\n      responseTitle.textContent = "Risposta modello";\n      responseMeta.textContent = "";\n      responseBox.textContent = "In attesa...";\n      return;\n    }}\n    caption.textContent = `${{item.label}} · ${{item.role || ""}} · ${{item.status || ""}}`;\n    promptBox.textContent = text(item.prompt);\n    responseTitle.textContent = "Risposta modello";\n    responseMeta.textContent = text(item.meta);\n    responseBox.textContent = text(item.response);\n  }}\n\n  followLatest.addEventListener("click", () => {{\n    selectedId = payload.defaultId;\n    if (selectedId) {{\n      window.localStorage.setItem(storageKey, selectedId);\n    }}\n    renderSelected(selectedId);\n  }});\n\n  function renderTimeline() {{\n    timeline.innerHTML = "";\n    const rows = payload.timeline || [];\n    if (!rows.length) {{\n      const empty = document.createElement("em");\n      empty.textContent = "In attesa di eventi...";\n      timeline.appendChild(empty);\n      return;\n    }}\n    for (const row of rows) {{\n      if (row.kind === "agent") {{\n        const button = document.createElement("button");\n        button.type = "button";\n        button.className = "ab-row agent";\n        button.dataset.agentId = row.id;\n        const time = document.createElement("span");\n        time.className = "ab-time";\n        time.textContent = `${{row.timestamp || ""}} |`;\n        const label = document.createElement("span");\n        label.textContent = ` ${{row.label || ""}}`;\n        button.appendChild(time);\n        button.appendChild(label);\n        button.addEventListener("click", () => renderSelected(row.id));\n        timeline.appendChild(button);\n      }} else {{\n        const div = document.createElement("div");\n        div.className = "ab-row";\n        const time = document.createElement("span");\n        time.className = "ab-time";\n        time.textContent = `${{row.timestamp || ""}} |`;\n        const label = document.createElement("span");\n        label.textContent = ` ${{row.label || ""}}`;\n        div.appendChild(time);\n        div.appendChild(label);\n        timeline.appendChild(div);\n      }}\n    }}\n  }}\n\n  renderTimeline();\n  renderSelected(selectedId);\n}})();\n</script>\n'
    with placeholder.container():
        components.html(component_html, height=1280, scrolling=False)
active_run = benchmark_runner.get_latest_run_for_session(session_name)
if active_run and active_run.status in {'queued', 'running'}:
    col1, col2, col3 = st.columns([2.5, 1, 1])
    with col1:
        st.warning(f"C'è già un benchmark in corso per questa sessione ({active_run.run_id}).")
    with col2:
        if st.button('Interrompi e conserva', type='secondary', use_container_width=True, help='Ferma il processo lasciando checkpoint e workspace parziali riprendibili'):
            with st.spinner('Interruzione in corso...'):
                success = benchmark_runner.stop(active_run.run_id)
                if success:
                    session_manager.ingest_workspace_results(session_name)
                    st.success('Benchmark interrotto. I checkpoint disponibili sono stati conservati.')
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("Errore durante l'interruzione del processo.")
    with col3:
        if st.button('Interrompi e pulisci', type='primary', use_container_width=True, help='Ferma il processo e cancella i dati parziali di questa run'):
            with st.spinner('Interruzione in corso...'):
                success = benchmark_runner.stop(active_run.run_id)
                if success:
                    session_manager.delete_projects(session_name, active_run.request.project_ids)
                    st.success('Benchmark interrotto e dati puliti!')
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("Errore durante l'interruzione del processo.")
    render_monitoring_ui(active_run)
elif st.button('Avvia benchmark', type='primary', disabled=not selected_project_ids or bool(config_errors)):
    request = BenchmarkRequest(session_name=session_name, project_ids=selected_project_ids, level=level, mode=mode, base_models_config_path=base_models_config_path, global_model=global_model or None, role_settings=role_settings, run_judge=run_judge, run_static_analysis=run_static_analysis, run_dynamic_analysis=run_dynamic_analysis, use_agentic_tools=use_agentic_tools, agentic_context_compaction=agentic_context_compaction, core_mode=core_mode, single_agent_iterations=int(single_agent_iterations), reuse_completed_workspaces=reuse_completed or post_core_only, post_core_only=post_core_only, regenerate_parameters=regenerate_parameters, resume_interrupted_workspaces=resume_interrupted, opencode_model=opencode_model, opencode_timeout_seconds=int(opencode_timeout))
    handle = benchmark_runner.start(request)
    render_monitoring_ui(handle)
st.subheader('Catalogo progetti')
st.dataframe(pd.DataFrame(projects), use_container_width=True, hide_index=True)