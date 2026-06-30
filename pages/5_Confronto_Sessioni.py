from __future__ import annotations
from typing import Any
import pandas as pd
import streamlit as st
from app.ui_backend.session_manager import PROJECTEVAL_FIXED_TEST_TOTAL, SessionManager
from app.ui_backend.theme import init_page
init_page(page_title='Confronto sessioni', page_icon=':material/balance:')
session_manager = SessionManager()
sessions = session_manager.list_sessions()
session_names = sorted((item.name for item in sessions))

def coerce_float(value: Any) -> float | None:
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == '':
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None

def project_sort_key(project_id: Any) -> tuple[int, Any]:
    try:
        return (0, int(str(project_id)))
    except (TypeError, ValueError):
        return (1, str(project_id))

def format_score(value: Any) -> str:
    score = coerce_float(value)
    return '-' if score is None else f'{score:.3f}'

def project_map(detail: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(project['project_id']): project for project in detail.get('projects', [])}

def total_project_tests(projects: list[dict[str, Any]], key: str) -> int:
    return sum((coerce_int(project.get(key)) or 0 for project in projects))

def keep_valid_session_selection(options: list[str]) -> list[str]:
    selection_key = 'comparison_selected_sessions'
    initialized_key = 'comparison_session_selection_initialized'
    current = st.session_state.get(selection_key)
    if isinstance(current, list):
        selected = [name for name in current if name in options]
    else:
        selected = []
    if not selected and (not st.session_state.get(initialized_key)):
        selected = options[:min(2, len(options))]
    st.session_state[initialized_key] = True
    st.session_state[selection_key] = selected
    return selected

def keep_valid_project_selection(options: list[str], session_signature: str) -> list[str]:
    selection_key = 'comparison_selected_projects'
    signature_key = 'comparison_project_selection_signature'
    previous_signature = st.session_state.get(signature_key)
    current = st.session_state.get(selection_key)
    if previous_signature != session_signature or not isinstance(current, list):
        selected = list(options)
    else:
        selected = [project_id for project_id in current if project_id in options]
    st.session_state[signature_key] = session_signature
    st.session_state[selection_key] = selected
    return selected

def build_summary_rows(details_by_session: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for session_name, detail in details_by_session.items():
        aggregate = detail['aggregate']
        config = detail['config']
        projects = detail['projects']
        fixed_passed = coerce_int(aggregate.get('fixed_passed_tests'))
        fixed_total = coerce_int(aggregate.get('fixed_total_tests')) or PROJECTEVAL_FIXED_TEST_TOTAL
        project_passed = total_project_tests(projects, 'test_passed')
        project_failed = total_project_tests(projects, 'test_failed')
        scored_projects = sum((1 for project in projects if coerce_float(project.get('score')) is not None))
        rows.append({'sessione': session_name, 'status': config.get('status', 'idle'), 'progetti_completati': aggregate.get('completed_projects', 0), 'progetti_totali': aggregate.get('total_projects', len(projects)), 'progetti_con_score': scored_projects, 'judge_pass_at_1': coerce_float(aggregate.get('fixed_pass_at_1') or aggregate.get('official_score')), 'test_passati_ufficiali': fixed_passed, 'test_falliti_ufficiali': None if fixed_passed is None else max(fixed_total - fixed_passed, 0), 'denominatore_ufficiale': fixed_total, 'test_passati_progetti': project_passed, 'test_falliti_progetti': project_failed, 'score_medio_progetti': coerce_float(aggregate.get('average_project_score')), 'level': config.get('last_level'), 'mode': config.get('last_mode'), 'config_modelli': config.get('last_models_config_path')})
    return rows

def build_project_rows(details_by_session: dict[str, dict[str, Any]], project_ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    maps = {session_name: project_map(detail) for session_name, detail in details_by_session.items()}
    for project_id in project_ids:
        scores = {session_name: coerce_float(projects.get(project_id, {}).get('score')) for session_name, projects in maps.items() if projects.get(project_id, {}).get('score') is not None}
        best_score = max(scores.values()) if scores else None
        worst_score = min(scores.values()) if scores else None
        best_sessions = [session_name for session_name, score in scores.items() if best_score is not None and score == best_score]
        row: dict[str, Any] = {'project_id': project_id, 'migliore_sessione': ', '.join(best_sessions) if best_sessions else '-', 'delta_score': None if best_score is None or worst_score is None else best_score - worst_score}
        known_totals = [coerce_int(project.get('test_total')) for projects in maps.values() for project in [projects.get(project_id, {})] if coerce_int(project.get('test_total')) is not None]
        row['test_totali'] = max(known_totals) if known_totals else None
        for session_name in details_by_session:
            project = maps[session_name].get(project_id, {})
            row[f'{session_name} score'] = coerce_float(project.get('score'))
            row[f'{session_name} passati'] = coerce_int(project.get('test_passed'))
            row[f'{session_name} falliti'] = coerce_int(project.get('test_failed'))
            row[f'{session_name} status'] = project.get('final_status') or '-'
        rows.append(row)
    return rows

def official_project_ids() -> list[str]:
    counts = getattr(session_manager, '_project_test_counts', {})
    if isinstance(counts, dict) and counts:
        return sorted((str(project_id) for project_id in counts), key=project_sort_key)
    return [str(project_id) for project_id in range(1, 21)]

def official_project_total(project_id: str) -> int | None:
    counts = getattr(session_manager, '_project_test_counts', {})
    if not isinstance(counts, dict):
        return None
    functions = coerce_int(counts.get(str(project_id)))
    return functions + 1 if functions is not None else None

def build_official_20_rows(details_by_session: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    maps = {session_name: project_map(detail) for session_name, detail in details_by_session.items()}
    for project_id in official_project_ids():
        total = official_project_total(project_id)
        row: dict[str, Any] = {'project_id': project_id, 'test_totali_ufficiali': total}
        for session_name, projects in maps.items():
            project = projects.get(project_id)
            evaluated = isinstance(project, dict)
            score = coerce_float((project or {}).get('score'))
            passed = coerce_int((project or {}).get('test_passed')) if evaluated else None
            failed = coerce_int((project or {}).get('test_failed')) if evaluated else None
            if passed is None:
                passed = 0
            if failed is None and total is not None:
                failed = max(total - passed, 0)
            if score is None and evaluated:
                score = 0.0
            row[f'{session_name} score'] = score
            row[f'{session_name} passati'] = passed
            row[f'{session_name} falliti'] = failed
            row[f'{session_name} status'] = (project or {}).get('final_status') if evaluated else 'non valutato'
        rows.append(row)
    return rows

def build_official_20_summary(official_rows: list[dict[str, Any]], session_names: list[str]) -> list[dict[str, Any]]:
    denominator = sum((coerce_int(row.get('test_totali_ufficiali')) or 0 for row in official_rows))
    rows: list[dict[str, Any]] = []
    for session_name in session_names:
        passed = sum((coerce_int(row.get(f'{session_name} passati')) or 0 for row in official_rows))
        failed = sum((coerce_int(row.get(f'{session_name} falliti')) or 0 for row in official_rows))
        scored = sum((1 for row in official_rows if coerce_float(row.get(f'{session_name} score')) is not None))
        rows.append({'sessione': session_name, 'test_passati': passed, 'test_falliti': failed, 'denominatore': denominator, 'pass_at_1_20_progetti': passed / denominator if denominator else None, 'progetti_con_score': scored})
    return rows
st.title('Confronto sessioni')
if not session_names:
    st.info('Nessuna sessione disponibile.')
    st.stop()
keep_valid_session_selection(session_names)
selected = st.multiselect('Seleziona sessioni', options=session_names, key='comparison_selected_sessions')
if not selected:
    st.info('Seleziona almeno una sessione.')
    st.stop()
with st.spinner('Sincronizzo risultati e metriche delle sessioni selezionate...'):
    details_by_session = {session_name: session_manager.get_session_detail(session_name) for session_name in selected}
summary_rows = build_summary_rows(details_by_session)
summary_df = pd.DataFrame(summary_rows)
all_project_ids = sorted({str(project['project_id']) for detail in details_by_session.values() for project in detail.get('projects', [])}, key=project_sort_key)
tab_summary, tab_projects, tab_official_20, tab_scores, tab_config = st.tabs(['Riepilogo', 'Per progetto', 'Ufficiale 20 progetti', 'Score', 'Configurazioni'])
with tab_summary:
    best_row = max(summary_rows, key=lambda row: coerce_float(row.get('judge_pass_at_1')) if coerce_float(row.get('judge_pass_at_1')) is not None else -1)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric('Sessioni', len(selected))
    col2.metric('Migliore Judge Pass@1', format_score(best_row.get('judge_pass_at_1')))
    col3.metric('Migliore sessione', best_row['sessione'])
    col4.metric('Progetti confrontati', len(all_project_ids))
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
    st.caption('Nel riepilogo ufficiale i test falliti sono calcolati come denominatore fisso ProjectEval meno test passati. Nel confronto per progetto sono invece i fallimenti del singolo progetto.')
    chart_df = summary_df.set_index('sessione')[['judge_pass_at_1', 'score_medio_progetti']]
    st.bar_chart(chart_df)
with tab_projects:
    if not all_project_ids:
        st.info('Nessun progetto disponibile nelle sessioni selezionate.')
    else:
        only_common = st.checkbox('Mostra solo progetti presenti in tutte le sessioni', value=False)
        if only_common:
            session_project_sets = [{str(project['project_id']) for project in detail.get('projects', [])} for detail in details_by_session.values()]
            available_project_ids = sorted(set.intersection(*session_project_sets), key=project_sort_key)
        else:
            available_project_ids = all_project_ids
        keep_valid_project_selection(available_project_ids, '|'.join(selected))
        selected_projects = st.multiselect('Progetti', options=available_project_ids, key='comparison_selected_projects')
        if not selected_projects:
            st.info('Seleziona almeno un progetto.')
        else:
            project_df = pd.DataFrame(build_project_rows(details_by_session, selected_projects))
            st.dataframe(project_df, use_container_width=True, hide_index=True)
            st.download_button('Scarica confronto per progetto CSV', data=project_df.to_csv(index=False).encode('utf-8'), file_name='confronto_sessioni_per_progetto.csv', mime='text/csv')
with tab_official_20:
    official_rows = build_official_20_rows(details_by_session)
    official_summary = pd.DataFrame(build_official_20_summary(official_rows, selected))
    official_df = pd.DataFrame(official_rows)
    st.caption('Questa vista usa sempre tutti i 20 progetti ProjectEval. I progetti non valutati in una sessione contano come 0 test passati sul totale ufficiale del progetto.')
    col1, col2, col3 = st.columns(3)
    col1.metric('Progetti ufficiali', len(official_rows))
    col2.metric('Denominatore', int(official_summary['denominatore'].max()) if not official_summary.empty else PROJECTEVAL_FIXED_TEST_TOTAL)
    best_official = None
    if not official_summary.empty:
        best_official = official_summary.sort_values('pass_at_1_20_progetti', ascending=False).iloc[0]
    col3.metric('Migliore Pass@1', '-' if best_official is None else format_score(best_official['pass_at_1_20_progetti']))
    st.subheader('Totali ufficiali sulle 20 task')
    st.dataframe(official_summary, use_container_width=True, hide_index=True)
    st.subheader('Dettaglio per progetto')
    st.dataframe(official_df, use_container_width=True, hide_index=True)
    score_columns = [column for column in official_df.columns if column.endswith(' score')]
    passed_columns = [column for column in official_df.columns if column.endswith(' passati')]
    failed_columns = [column for column in official_df.columns if column.endswith(' falliti')]
    if score_columns:
        chart_df = official_df.set_index('project_id')[score_columns]
        chart_df.columns = [column.removesuffix(' score') for column in chart_df.columns]
        st.subheader('Score ufficiale per progetto')
        st.bar_chart(chart_df)
    if passed_columns or failed_columns:
        st.subheader('Test ufficiali passati e falliti per progetto')
        test_columns = ['project_id', *passed_columns, *failed_columns]
        st.dataframe(official_df[test_columns], use_container_width=True, hide_index=True)
    st.download_button('Scarica confronto ufficiale 20 progetti CSV', data=official_df.to_csv(index=False).encode('utf-8'), file_name='confronto_ufficiale_20_progetti.csv', mime='text/csv')
with tab_scores:
    score_rows = []
    for session_name, detail in details_by_session.items():
        for project in detail.get('projects', []):
            score = coerce_float(project.get('score'))
            if score is None:
                continue
            score_rows.append({'project_id': str(project['project_id']), 'sessione': session_name, 'score': score, 'test_passati': coerce_int(project.get('test_passed')) or 0, 'test_falliti': coerce_int(project.get('test_failed')) or 0})
    if not score_rows:
        st.info('Nessuno score disponibile per le sessioni selezionate.')
    else:
        score_df = pd.DataFrame(score_rows)
        score_matrix = score_df.pivot_table(index='project_id', columns='sessione', values='score', aggfunc='max')
        score_matrix = score_matrix.reindex(sorted(score_matrix.index, key=project_sort_key))
        st.dataframe(score_matrix, use_container_width=True)
        st.bar_chart(score_matrix)
        tests_matrix = score_df.pivot_table(index='project_id', columns='sessione', values=['test_passati', 'test_falliti'], aggfunc='max')
        tests_matrix = tests_matrix.reindex(sorted(tests_matrix.index, key=project_sort_key))
        st.subheader('Test passati e falliti')
        st.dataframe(tests_matrix, use_container_width=True)
with tab_config:
    for session_name in selected:
        detail = details_by_session[session_name]
        with st.expander(session_name, expanded=False):
            st.json(detail['config'])