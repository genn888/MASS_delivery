from __future__ import annotations
import pandas as pd
import streamlit as st
from app.ui_backend.session_manager import SessionManager
from app.ui_backend.theme import init_page
init_page(page_title='Sessioni', page_icon=':material/folder:')
session_manager = SessionManager()
sessions = session_manager.list_sessions()
st.title('Sessioni')
new_session_name = st.text_input('Nuova sessione')
if st.button('Crea sessione') and new_session_name.strip():
    session_manager.create_session(new_session_name.strip())
    st.session_state['selected_session'] = new_session_name.strip()
    st.toast(f'Sessione `{new_session_name.strip()}` creata.', icon='✅')
    st.rerun()
if not sessions:
    st.info('Nessuna sessione disponibile.')
    st.stop()
rows = [{'name': item.name, 'status': item.status, 'created_at': item.created_at, 'updated_at': item.updated_at, 'projects': f'{item.completed_projects}/{item.total_projects}', 'judge_pass_at_1': item.official_score} for item in sessions]
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
st.subheader('Azioni rapide')
for item in sessions:
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.write(f'**{item.name}**')
        c1.caption(f'Status: {item.status} | {item.completed_projects}/{item.total_projects} completati')
        if c2.button('Dettaglio', key=f'detail_{item.name}'):
            st.session_state['selected_session'] = item.name
            st.switch_page('pages/4_Dettaglio_Sessione.py')
        if c3.button('Benchmark', key=f'bench_{item.name}'):
            st.session_state['selected_session'] = item.name
            st.switch_page('pages/2_Benchmark.py')