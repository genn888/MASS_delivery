from __future__ import annotations
import html
import json
import os
import time
import streamlit as st
import streamlit.components.v1 as components
from app.ui_backend.agent_runner import AgentRunner
from app.ui_backend.config_manager import ConfigManager
from app.ui_backend.session_manager import SessionManager
from app.ui_backend.theme import init_page
init_page(page_title='Chat', page_icon=':material/chat:')
session_manager = SessionManager()
config_manager = ConfigManager()
agent_runner = AgentRunner(session_manager=session_manager)

def shorten_live_text(value: object, *, limit: int=40000) -> str:
    text = '' if value is None else str(value)
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit] + f'\n\n[... testo abbreviato nella vista live: {omitted} caratteri non mostrati ...]'

def agent_event_label(agent_name: object, role: object, iteration: int | None) -> str:
    agent = str(agent_name or '')
    if agent == 'RequirementAnalyzerAgent':
        return f'📋 Requirement analysis · iterazione {iteration or 1}'
    if agent == 'ArchitectAgent':
        return f'🏗️ Architecture · iterazione {iteration or 1}'
    if agent == 'PlanningReviewerAgent':
        return f'🔎 Planning review · iterazione {iteration or 1}'
    if agent == 'CoderAgent':
        return f'💻 Coding · iterazione {iteration or 1}'
    if agent == 'ReviewerAgent':
        return f'🧪 Reviewer · iterazione {iteration or 1}'
    if agent == 'TestWriterAgent':
        return f'📝 Dynamic tests · iterazione {iteration or 1}'
    if agent == 'BrowserTestWriterAgent':
        return f'🌐 Selenium browser tests · iterazione {iteration or 1}'
    if agent == 'static_analysis':
        return f'🧭 Static analysis · iterazione {iteration or 1}'
    if agent == 'workflow_finalizer':
        return '🏁 Workflow finalizer'
    return f"{agent or role or 'Agent'} · iterazione {iteration or 1}"

def collect_agent_interactions(events: list[dict[str, object]]) -> list[dict[str, object]]:
    interactions: list[dict[str, object]] = []
    current_by_agent: dict[str, dict[str, object]] = {}
    prompt_counts: dict[str, int] = {}
    for event in events:
        event_type = str(event.get('event_type', ''))
        if event_type not in {'prompt', 'output', 'end'}:
            continue
        metadata = event.get('metadata')
        if not isinstance(metadata, dict):
            metadata = {}
        agent_name = str(event.get('agent_name', 'agent'))
        if event_type == 'prompt':
            prompt_counts[agent_name] = prompt_counts.get(agent_name, 0) + 1
            interaction_id = f'agent-{len(interactions) + 1}'
            system_prompt = str(metadata.get('system_prompt') or '')
            user_prompt = str(metadata.get('user_prompt') or event.get('content') or '')
            current = {'id': interaction_id, 'agent_name': agent_name, 'role': metadata.get('role', ''), 'iteration': prompt_counts[agent_name], 'timestamp': event.get('timestamp', ''), 'prompt_path': metadata.get('prompt_path', ''), 'system_prompt': system_prompt, 'user_prompt': user_prompt, 'response_text': '', 'finish_reason': '', 'duration_ms': None, 'usage': {}, 'completed': False}
            current['label'] = agent_event_label(current['agent_name'], current['role'], int(current['iteration']))
            interactions.append(current)
            current_by_agent[agent_name] = current
        elif event_type == 'output':
            current = current_by_agent.get(agent_name)
            if current is None:
                interaction_id = f'agent-{len(interactions) + 1}'
                current = {'id': interaction_id, 'agent_name': agent_name, 'role': metadata.get('role', ''), 'iteration': prompt_counts.get(agent_name, 1), 'timestamp': event.get('timestamp', ''), 'prompt_path': '', 'system_prompt': '', 'user_prompt': '', 'response_text': '', 'finish_reason': '', 'duration_ms': None, 'usage': {}, 'completed': False}
                current['label'] = agent_event_label(current['agent_name'], current['role'], int(current['iteration']))
                interactions.append(current)
                current_by_agent[agent_name] = current
            current['response_text'] = str(event.get('content') or '')
            current['finish_reason'] = metadata.get('finish_reason', '')
            current['duration_ms'] = metadata.get('duration_ms')
            current['usage'] = metadata.get('usage') if isinstance(metadata.get('usage'), dict) else {}
        elif event_type == 'end':
            current = current_by_agent.get(agent_name)
            if current is not None:
                current['completed'] = True
                current['finish_reason'] = metadata.get('finish_reason', current.get('finish_reason', ''))
                current['duration_ms'] = metadata.get('duration_ms', current.get('duration_ms'))
    return interactions

def collect_timeline_items(events: list[dict[str, object]]) -> list[dict[str, object]]:
    prompt_counts: dict[str, int] = {}
    items: list[dict[str, object]] = []
    interaction_index = 0
    for event in events:
        event_type = str(event.get('event_type', ''))
        metadata = event.get('metadata')
        if not isinstance(metadata, dict):
            metadata = {}
        timestamp = str(event.get('timestamp') or '')
        if event_type == 'prompt':
            interaction_index += 1
            interaction_id = f'agent-{interaction_index}'
            agent_name = event.get('agent_name', 'agent')
            prompt_counts[str(agent_name)] = prompt_counts.get(str(agent_name), 0) + 1
            label = agent_event_label(agent_name, metadata.get('role', ''), prompt_counts[str(agent_name)])
            items.append({'kind': 'agent', 'id': interaction_id, 'timestamp': timestamp, 'label': label})
        elif event_type in {'start', 'end', 'error', 'warning', 'retry'}:
            items.append({'kind': 'event', 'timestamp': timestamp, 'label': str(event.get('content') or '')})
    return items

def render_agent_browser(placeholder, events: list[dict[str, object]]) -> None:
    interactions = collect_agent_interactions(events)
    timeline_items = collect_timeline_items(events)
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
    component_html = f'\n<div id="agent-browser-root" data-payload="{escaped_payload}">\n  <style>\n    html, body {{\n      background: transparent;\n      color: #e8edf2;\n    }}\n    #agent-browser-root {{\n      color: #e8edf2;\n      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;\n    }}\n    #agent-browser-root,\n    #agent-browser-root * {{\n      box-sizing: border-box;\n    }}\n    .ab-title {{\n      color: #f4f7fb;\n      font-weight: 700;\n      font-size: 1rem;\n      margin: 0 0 .55rem 0;\n    }}\n    .ab-timeline {{\n      max-height: 260px;\n      overflow-y: auto;\n      padding: .75rem 1rem;\n      border: 1px solid rgba(155, 176, 196, .36);\n      border-radius: 8px;\n      background: #111821;\n      margin-bottom: 1rem;\n    }}\n    .ab-row {{\n      display: block;\n      width: 100%;\n      background: transparent;\n      border: 0;\n      color: #dbe5ef;\n      text-align: left;\n      padding: .18rem 0;\n      margin: 0 0 .25rem 0;\n      font: inherit;\n    }}\n    .ab-row.agent {{\n      cursor: pointer;\n      color: #7dd3c7;\n      text-decoration: underline;\n      text-underline-offset: 2px;\n    }}\n    .ab-row.agent.active {{\n      color: #a7f3d0;\n      font-weight: 700;\n    }}\n    .ab-time {{\n      color: #9fb1c2;\n      margin-right: .25rem;\n    }}\n    .ab-caption {{\n      color: #b8c4d0;\n      font-size: .92rem;\n      margin: 0 0 .75rem 0;\n    }}\n    .ab-follow {{\n      color: #0b1118;\n      background: #7dd3c7;\n      border: 0;\n      border-radius: 8px;\n      cursor: pointer;\n      font-weight: 700;\n      padding: .35rem .65rem;\n      margin: -.2rem 0 .85rem 0;\n    }}\n    .ab-follow:hover {{\n      background: #a7f3d0;\n    }}\n    .ab-grid {{\n      display: grid;\n      grid-template-columns: repeat(2, minmax(0, 1fr));\n      gap: 1rem;\n    }}\n    .ab-pane-title {{\n      color: #f4f7fb;\n      font-weight: 700;\n      margin-bottom: .35rem;\n    }}\n    .ab-meta {{\n      color: #b8c4d0;\n      font-size: .82rem;\n      line-height: 1.35;\n      min-height: 1.15rem;\n      max-height: 4.6rem;\n      overflow: auto;\n      margin: -.15rem 0 .45rem 0;\n    }}\n    .ab-box {{\n      white-space: pre-wrap;\n      overflow: auto;\n      height: 640px;\n      padding: .75rem;\n      color: #e8edf2;\n      border: 1px solid rgba(155, 176, 196, .36);\n      border-radius: 8px;\n      background: #111821;\n      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;\n      font-size: .88rem;\n      line-height: 1.45;\n    }}\n    .ab-timeline::-webkit-scrollbar,\n    .ab-box::-webkit-scrollbar,\n    .ab-meta::-webkit-scrollbar {{\n      width: 10px;\n      height: 10px;\n    }}\n    .ab-timeline::-webkit-scrollbar-thumb,\n    .ab-box::-webkit-scrollbar-thumb,\n    .ab-meta::-webkit-scrollbar-thumb {{\n      background: #475569;\n      border-radius: 8px;\n    }}\n    .ab-timeline::-webkit-scrollbar-track,\n    .ab-box::-webkit-scrollbar-track,\n    .ab-meta::-webkit-scrollbar-track {{\n      background: #0b1118;\n    }}\n    @media (max-width: 800px) {{\n      .ab-grid {{\n        grid-template-columns: 1fr;\n      }}\n    }}\n  </style>\n  <div class="ab-title">Timeline consultabile</div>\n  <div class="ab-timeline" id="ab-timeline"></div>\n  <div class="ab-title">Prompt e risposta agente</div>\n  <div class="ab-caption" id="ab-caption">In attesa della prima richiesta a un agente...</div>\n  <button type="button" class="ab-follow" id="ab-follow-latest">Segui ultimo agente</button>\n  <div class="ab-grid">\n    <div>\n      <div class="ab-pane-title">Prompt inviato</div>\n      <div class="ab-box" id="ab-prompt">In attesa...</div>\n    </div>\n    <div>\n      <div class="ab-pane-title" id="ab-response-title">Risposta modello</div>\n      <div class="ab-meta" id="ab-response-meta"></div>\n      <div class="ab-box" id="ab-response">In attesa...</div>\n    </div>\n  </div>\n</div>\n<script>\n(function() {{\n  const root = document.getElementById("agent-browser-root");\n  const payload = JSON.parse(root.dataset.payload || "{{}}");\n  const interactions = payload.interactions || [];\n  const byId = new Map(interactions.map((item) => [item.id, item]));\n  const storageKey = "mass-chat-agent-browser-selected";\n  const storedId = window.localStorage.getItem(storageKey);\n  let selectedId = storedId && byId.has(storedId) ? storedId : payload.defaultId;\n  const timeline = document.getElementById("ab-timeline");\n  const caption = document.getElementById("ab-caption");\n  const promptBox = document.getElementById("ab-prompt");\n  const responseTitle = document.getElementById("ab-response-title");\n  const responseMeta = document.getElementById("ab-response-meta");\n  const responseBox = document.getElementById("ab-response");\n  const followLatest = document.getElementById("ab-follow-latest");\n\n  function text(value) {{\n    return value == null || value === "" ? "" : String(value);\n  }}\n\n  function renderSelected(id) {{\n    selectedId = id || selectedId;\n    if (selectedId) {{\n      window.localStorage.setItem(storageKey, selectedId);\n    }}\n    const item = byId.get(selectedId);\n    for (const button of timeline.querySelectorAll("button[data-agent-id]")) {{\n      button.classList.toggle("active", button.dataset.agentId === selectedId);\n    }}\n    if (!item) {{\n      caption.textContent = "In attesa della prima richiesta a un agente...";\n      promptBox.textContent = "In attesa...";\n      responseTitle.textContent = "Risposta modello";\n      responseMeta.textContent = "";\n      responseBox.textContent = "In attesa...";\n      return;\n    }}\n    caption.textContent = `${{item.label}} · ${{item.role || ""}} · ${{item.status || ""}}`;\n    promptBox.textContent = text(item.prompt);\n    responseTitle.textContent = "Risposta modello";\n    responseMeta.textContent = text(item.meta);\n    responseBox.textContent = text(item.response);\n  }}\n\n  followLatest.addEventListener("click", () => {{\n    selectedId = payload.defaultId;\n    if (selectedId) {{\n      window.localStorage.setItem(storageKey, selectedId);\n    }}\n    renderSelected(selectedId);\n  }});\n\n  function renderTimeline() {{\n    timeline.innerHTML = "";\n    const rows = payload.timeline || [];\n    if (!rows.length) {{\n      const empty = document.createElement("em");\n      empty.textContent = "In attesa di eventi...";\n      timeline.appendChild(empty);\n      return;\n    }}\n    for (const row of rows) {{\n      if (row.kind === "agent") {{\n        const button = document.createElement("button");\n        button.type = "button";\n        button.className = "ab-row agent";\n        button.dataset.agentId = row.id;\n        const time = document.createElement("span");\n        time.className = "ab-time";\n        time.textContent = `${{row.timestamp || ""}} |`;\n        const label = document.createElement("span");\n        label.textContent = ` ${{row.label || ""}}`;\n        button.appendChild(time);\n        button.appendChild(label);\n        button.addEventListener("click", () => renderSelected(row.id));\n        timeline.appendChild(button);\n      }} else {{\n        const div = document.createElement("div");\n        div.className = "ab-row";\n        const time = document.createElement("span");\n        time.className = "ab-time";\n        time.textContent = `${{row.timestamp || ""}} |`;\n        const label = document.createElement("span");\n        label.textContent = ` ${{row.label || ""}}`;\n        div.appendChild(time);\n        div.appendChild(label);\n        timeline.appendChild(div);\n      }}\n    }}\n  }}\n\n  renderTimeline();\n  renderSelected(selectedId);\n}})();\n</script>\n'
    with placeholder.container():
        components.html(component_html, height=1280, scrolling=False)

def ensure_session() -> str:
    sessions = session_manager.list_sessions()
    options = [item.name for item in sessions]
    if 'selected_session' in st.session_state and st.session_state['selected_session'] not in options:
        del st.session_state['selected_session']
    create_name = st.sidebar.text_input('Nuova sessione', value=st.session_state.get('selected_session', ''))
    if st.sidebar.button('Crea / Usa sessione') and create_name.strip():
        session_manager.create_session(create_name.strip())
        st.session_state['selected_session'] = create_name.strip()
        st.rerun()
    if options:
        current = st.sidebar.selectbox('Sessione attiva', options=options, index=options.index(st.session_state['selected_session']) if st.session_state.get('selected_session') in options else 0)
        st.session_state['selected_session'] = current
        return current
    st.info('Crea una sessione dal sidebar per iniziare.')
    st.stop()
session_name = ensure_session()
detail = session_manager.get_session_detail(session_name)
st.title('Chat Multi-Agente')
st.caption(f'Sessione attiva: `{session_name}`')
models_config_options = config_manager.list_model_config_paths()
default_models_config = detail['config'].get('last_models_config_path') or os.getenv('MASS_MODELS_CONFIG', 'configs/models_nvidia_deepseek_v4_pro.yaml')
models_config_path = st.sidebar.selectbox('Config modelli', options=models_config_options, index=models_config_options.index(default_models_config) if default_models_config in models_config_options else 0)
system_config_path = st.sidebar.text_input('System config', value=detail['config'].get('last_system_config_path', 'configs/system.yaml'))
for chat_run in detail['results'].get('chat_runs', [])[-5:]:
    with st.chat_message('assistant'):
        st.markdown(chat_run.get('implementation_summary') or f"Run `{chat_run.get('run_id')}` completata con stato `{chat_run.get('final_status')}`.")
prompt = st.chat_input('Scrivi una richiesta per il sistema multi-agente')
if prompt:
    with st.chat_message('user'):
        st.write(prompt)
    handle = agent_runner.start_chat_run(session_name=session_name, user_task=prompt, models_config_path=models_config_path, system_config_path=system_config_path, initial_overrides={})
    status_placeholder = st.empty()
    event_container = st.empty()
    collected_events: list[dict[str, object]] = []
    while handle.status in {'queued', 'running'}:
        collected_events.extend(handle.drain_events())
        status_placeholder.info(f'Run `{handle.run_id}` in esecuzione. Eventi: {len(collected_events)}')
        render_agent_browser(event_container, collected_events)
        time.sleep(1)
    collected_events.extend(handle.drain_events())
    render_agent_browser(event_container, collected_events)
    if handle.status == 'completed':
        status_placeholder.success(f'Run `{handle.run_id}` completata.')
        final_state = handle.final_state or {}
        with st.chat_message('assistant'):
            st.markdown(final_state.get('implementation_summary', 'Nessun summary disponibile.'))
            st.caption(f"Final status: {final_state.get('final_status')} | Test status: {final_state.get('test_status')}")
    else:
        status_placeholder.error(f'Run `{handle.run_id}` fallita: {handle.error}')