from __future__ import annotations
import streamlit as st
from app.ui_backend.theme import init_page
from app.ui_backend.session_manager import SessionManager
init_page(page_title='MAS Control Center', page_icon=':material/smart_toy:')
session_manager = SessionManager()
sessions = session_manager.list_sessions()
st.title('MAS Control Center')
st.caption('UI operativa per chat multi-agente, benchmark ProjectEval e gestione sessioni persistenti.')
official_scores = [item.official_score for item in sessions if item.official_score is not None]
col1, col2, col3, col4 = st.columns(4)
col1.metric('Sessioni', len(sessions))
col2.metric('Sessioni attive', sum((1 for item in sessions if item.status == 'running')))
col3.metric('Progetti completati', sum((item.completed_projects for item in sessions)))
col4.metric('Score ufficiale medio', f'{sum(official_scores) / len(official_scores):.3f}' if official_scores else '-')
st.subheader('Sessioni recenti')
if not sessions:
    st.info('Non ci sono ancora sessioni. Vai su Benchmark o Chat per crearne una.')
else:
    for session in sessions[:10]:
        with st.container(border=True):
            left, right = st.columns([3, 1])
            left.write(f'**{session.name}**')
            left.caption(f'Status: {session.status} | Completati: {session.completed_projects}/{session.total_projects} | Local pass@1: {session.local_pass_at_1:.3f}')
            if right.button('Apri', key=f'open_{session.name}'):
                st.session_state['selected_session'] = session.name
                st.switch_page('pages/4_Dettaglio_Sessione.py')
st.subheader('Navigazione')
st.page_link('pages/1_Chat.py', label='Chat', icon=':material/chat:')
st.page_link('pages/2_Benchmark.py', label='Benchmark', icon=':material/play_arrow:')
st.page_link('pages/3_Sessioni.py', label='Sessioni', icon=':material/folder:')
st.page_link('pages/4_Dettaglio_Sessione.py', label='Dettaglio sessione', icon=':material/insights:')
st.page_link('pages/5_Confronto_Sessioni.py', label='Confronto sessioni', icon=':material/balance:')