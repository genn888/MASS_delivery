from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from app.ui_backend.session_manager import SessionManager
from app.ui_backend.theme import init_page
from app.ui_backend.project_server import ProjectServerManager
init_page(page_title='Dettaglio sessione', page_icon=':material/insights:')
session_manager = SessionManager()
sessions = session_manager.list_sessions()
session_names = [item.name for item in sessions]
if not session_names:
    st.info('Nessuna sessione disponibile.')
    st.stop()
selected = st.sidebar.selectbox('Sessione', options=session_names, index=session_names.index(st.session_state['selected_session']) if st.session_state.get('selected_session') in session_names else 0)
st.session_state['selected_session'] = selected
detail = session_manager.get_session_detail(selected)
st.title(f'Dettaglio sessione: {selected}')
aggregate = detail['aggregate']
fixed_pass_at_1 = aggregate.get('fixed_pass_at_1')
if fixed_pass_at_1 is None:
    fixed_pass_at_1 = aggregate.get('official_score')
fixed_passed_tests = aggregate.get('fixed_passed_tests')
fixed_total_tests = aggregate.get('fixed_total_tests') or 284
col1, col2, col3 = st.columns(3)
col1.metric('Progetti Completati', aggregate['completed_projects'])
col2.metric('Progetti Totali', aggregate['total_projects'])
col3.metric('Judge Pass@1', '-' if fixed_pass_at_1 is None else f'{fixed_pass_at_1:.3f}', help='Calcolato come test passati / 284, il denominatore fisso del benchmark ProjectEval.')
if fixed_passed_tests is not None:
    st.caption(f'Pass@1 ufficiale: {fixed_passed_tests}/{fixed_total_tests}. La media dei punteggi per progetto resta disponibile nella tabella/risultati come metrica secondaria.')
else:
    st.caption('Pass@1 ufficiale calcolato su denominatore fisso 284. Per le sessioni precedenti al nuovo calcolo, viene usato il miglior valore ufficiale disponibile.')
with st.expander('Configurazione sessione', expanded=True):
    st.json(detail['config'])
projects = detail['projects']
st.subheader('Progetti')
if projects:
    df = pd.DataFrame(projects)
    cols_order = ['project_id', 'final_status', 'test_status', 'validation_status', 'test_passed', 'test_failed', 'test_total', 'score', 'trace_count', 'updated_at']
    display_cols = [c for c in cols_order if c in df.columns]
    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
    project_id = st.selectbox('Apri progetto', options=[item['project_id'] for item in projects])
    row = next((p for p in projects if str(p['project_id']) == str(project_id)))
    project_dir = Path(detail['session_dir']) / f'project_{project_id}'
    st.caption(f'Directory progetto: `{project_dir}`')
    report_path = project_dir / 'artifacts' / 'final_report.json'
    if report_path.exists():
        st.json(json.loads(report_path.read_text(encoding='utf-8')))
    else:
        st.warning('Final report non trovato per questo progetto.')
    st.divider()
    st.subheader('🌐 Live Preview')
    server_manager = ProjectServerManager()
    workspace_path = row.get('workspace')
    if workspace_path and (Path(workspace_path) / 'generated_project' / 'manage.py').exists():
        is_running = server_manager.is_running(str(project_id))
        if is_running:
            port = server_manager.get_port(str(project_id))
            url = f'http://127.0.0.1:{port}'
            st.success(f'Serfver attivo sulla porta {port}')
            c1, c2 = st.columns(2)
            c1.link_button('👉 Apri nel Browser', url, use_container_width=True)
            if c2.button('🛑 Ferma Server', type='primary', use_container_width=True):
                server_manager.stop_server(str(project_id))
                st.rerun()
        else:
            st.info('Questo progetto è un sito web Django. Puoi avviarlo per vederlo in azione.')
            if st.button('🚀 Avvia Anteprima Live', use_container_width=True):
                with st.spinner('Avvio del server Django in corso...'):
                    try:
                        port = server_manager.start_server(str(project_id), workspace_path)
                        st.success(f'Server avviato con successo!')
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore durante l'avvio: {e}")
    else:
        st.info('Anteprima non disponibile per questo tipo di progetto (nessun `manage.py` trovato).')
else:
    st.info('Nessun progetto ancora sincronizzato nella sessione.')
st.subheader('Benchmark runs')
benchmark_runs = detail['results'].get('benchmark_runs', [])
if benchmark_runs:
    st.json(benchmark_runs[-5:])
st.subheader('Chat runs')
chat_runs = detail['results'].get('chat_runs', [])
if chat_runs:
    st.json(chat_runs[-5:])
st.subheader('Log')
st.text_area('Benchmark log', value=session_manager.read_log(selected, 'benchmark'), height=320)