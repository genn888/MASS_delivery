from __future__ import annotations
import json
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from app.ui_backend.models import SessionSummary
from app.graph.checkpoint import checkpoint_summary, load_checkpoint
PROJECTEVAL_FIXED_TEST_TOTAL = 284

class SessionManager:
    _WRITE_LOCK = threading.RLock()

    def __init__(self, root: str | Path='sessions') -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._project_test_counts = self._load_official_test_counts()

    def _load_official_test_counts(self) -> dict[str, int]:
        """Carica il numero di funzioni ufficiali per ogni progetto dal dataset."""
        try:
            path = Path('external/ProjectEval/data/project_eval_project.json')
            if not path.exists():
                return {}
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return {str(p['project_id']): sum((len(page.get('function', [])) for page in p.get('testcode', []))) for p in data}
        except Exception:
            return {}

    def list_sessions(self) -> list[SessionSummary]:
        sessions: list[SessionSummary] = []
        for session_dir in sorted(self.root.iterdir(), key=lambda path: path.name):
            if not session_dir.is_dir():
                continue
            config = self._read_json(session_dir / 'config.json', default={})
            results = self._read_json(session_dir / 'results.json', default={})
            aggregate = self._compute_aggregate(results)
            sessions.append(SessionSummary(name=session_dir.name, created_at=config.get('created_at', ''), updated_at=config.get('updated_at', config.get('created_at', '')), status=config.get('status', 'idle'), completed_projects=aggregate['completed_projects'], total_projects=aggregate['total_projects'], local_pass_at_1=aggregate['local_pass_at_1'], official_score=aggregate.get('official_score'), workspace_root=str((session_dir / 'workspace').resolve())))
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def create_session(self, name: str, *, description: str='') -> Path:
        with self._WRITE_LOCK:
            session_dir = self.root / name
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / 'logs').mkdir(exist_ok=True)
            (session_dir / 'workspace').mkdir(exist_ok=True)
            now = self._now()
            config = self._read_json(session_dir / 'config.json', default={})
            config.setdefault('name', name)
            config.setdefault('description', description)
            config.setdefault('created_at', now)
            config['updated_at'] = now
            config.setdefault('status', 'idle')
            config['workspace_root'] = str((session_dir / 'workspace').resolve())
            self._write_json_atomic(session_dir / 'config.json', config)
            results = self._read_json(session_dir / 'results.json', default={'projects': {}, 'chat_runs': [], 'benchmark_runs': [], 'aggregate': {}, 'last_benchmark': {}})
            self._write_json_atomic(session_dir / 'results.json', results)
            return session_dir

    def get_session_dir(self, name: str) -> Path:
        return self.create_session(name)

    def get_session_detail(self, name: str, *, sync_workspace: bool=True) -> dict[str, Any]:
        if sync_workspace:
            self.ingest_workspace_results(name)
        session_dir = self.root / name
        config = self._read_json(session_dir / 'config.json', default={})
        results = self._read_json(session_dir / 'results.json', default={})
        aggregate = self._compute_aggregate(results)
        projects = self._collect_project_details(session_dir, results)
        return {'config': config, 'results': results, 'aggregate': aggregate, 'projects': projects, 'session_dir': str(session_dir)}

    def update_session_config(self, name: str, updates: dict[str, Any]) -> None:
        with self._WRITE_LOCK:
            session_dir = self.create_session(name)
            config = self._read_json(session_dir / 'config.json', default={})
            config.update(updates)
            config['updated_at'] = self._now()
            self._write_json_atomic(session_dir / 'config.json', config)

    def append_session_log(self, name: str, log_name: str, line: str) -> None:
        with self._WRITE_LOCK:
            session_dir = self.create_session(name)
            target = session_dir / 'logs' / f'{log_name}.log'
            with target.open('a', encoding='utf-8') as handle:
                handle.write(line.rstrip() + '\n')

    def record_chat_run(self, name: str, payload: dict[str, Any]) -> None:
        with self._WRITE_LOCK:
            session_dir = self.create_session(name)
            results = self._read_json(session_dir / 'results.json', default={})
            results.setdefault('chat_runs', []).append(payload)
            results['aggregate'] = self._compute_aggregate(results)
            self._write_json_atomic(session_dir / 'results.json', results)
            self.update_session_config(name, {'status': 'idle'})

    def delete_projects(self, name: str, project_ids: list[str]) -> None:
        """Removes projects from results and deletes their workspace/artifacts folders."""
        with self._WRITE_LOCK:
            session_dir = self.root / name
            if not session_dir.exists():
                return
            results = self._read_json(session_dir / 'results.json', default={})
            projects = results.get('projects', {})
            official = results.get('official')
            reset_at = self._now()
            reset_projects = results.setdefault('reset_projects', {})
            if not isinstance(reset_projects, dict):
                reset_projects = {}
                results['reset_projects'] = reset_projects
            for pid in project_ids:
                pid_str = str(pid)
                reset_projects[pid_str] = reset_at
                if pid_str in projects:
                    ws_path = projects[pid_str].get('workspace')
                    if ws_path:
                        try:
                            shutil.rmtree(ws_path, ignore_errors=True)
                        except Exception:
                            pass
                    del projects[pid_str]
                local_project_dir = session_dir / f'project_{pid_str}'
                if local_project_dir.exists():
                    shutil.rmtree(local_project_dir, ignore_errors=True)
                workspace_root = session_dir / 'workspace' / name
                for workspace_project_dir in workspace_root.glob(f'level_*/{pid_str}'):
                    if workspace_project_dir.exists():
                        shutil.rmtree(workspace_project_dir, ignore_errors=True)
                if isinstance(official, dict):
                    judge_scores = official.get('judge_scores')
                    if isinstance(judge_scores, dict):
                        if pid_str in judge_scores:
                            del judge_scores[pid_str]
                        if f'score_{pid_str}' in judge_scores:
                            del judge_scores[f'score_{pid_str}']
                        projects_payload = judge_scores.get('projects')
                        if isinstance(projects_payload, dict):
                            projects_payload.pop(pid_str, None)
                    mas_report = official.get('mas_report')
                    if isinstance(mas_report, dict):
                        per_project = mas_report.get('per_project_results')
                        if isinstance(per_project, dict):
                            per_project.pop(pid_str, None)
                        official_scores = mas_report.get('official_scores')
                        if isinstance(official_scores, dict):
                            project_scores = official_scores.get('judge_project_scores')
                            if isinstance(project_scores, dict):
                                project_scores.pop(pid_str, None)
                            function_details = official_scores.get('judge_function_details')
                            if isinstance(function_details, dict):
                                function_details.pop(pid_str, None)
            self._remove_projects_from_payload(results, project_ids)
            self._prune_empty_official_results(results)
            self._prune_projecteval_session_files(name, project_ids)
            last_benchmark = results.get('last_benchmark')
            if isinstance(last_benchmark, dict) and (not self._extract_selected_project_ids(last_benchmark)):
                results['last_benchmark'] = {}
            results['projects'] = projects
            results['aggregate'] = self._compute_aggregate(results)
            self._write_json_atomic(session_dir / 'results.json', results)
            self.update_session_config(name, {})

    def record_benchmark_run(self, name: str, payload: dict[str, Any]) -> None:
        with self._WRITE_LOCK:
            session_dir = self.create_session(name)
            results = self._read_json(session_dir / 'results.json', default={})
            runs = list(results.setdefault('benchmark_runs', []))
            run_id = payload.get('run_id')
            if run_id:
                previous_payload: dict[str, Any] = {}
                deduped_runs = []
                for item in runs:
                    if isinstance(item, dict) and item.get('run_id') == run_id:
                        previous_payload = {**previous_payload, **item}
                    else:
                        deduped_runs.append(item)
                payload = {**previous_payload, **payload}
                deduped_runs.append(payload)
                results['benchmark_runs'] = deduped_runs
            else:
                results['benchmark_runs'] = runs + [payload]
            results['last_benchmark'] = payload
            self._mark_running_benchmark_projects(session_dir, results, payload)
            results['aggregate'] = self._compute_aggregate(results)
            self._write_json_atomic(session_dir / 'results.json', results)
            self.update_session_config(name, {'status': payload.get('status', 'idle')})

    def ingest_workspace_results(self, name: str) -> dict[str, Any]:
        with self._WRITE_LOCK:
            session_dir = self.create_session(name)
            results = self._read_json(session_dir / 'results.json', default={})
            workspace_root = session_dir / 'workspace' / name
            if not workspace_root.exists():
                return results
            reset_ids = self._reset_project_ids(results)
            if reset_ids:
                self._prune_projecteval_session_files(name, reset_ids)
            for report_path in workspace_root.glob('level_*/*/artifacts/final_report.json'):
                project_id = report_path.parent.parent.name
                reset_at = self._project_reset_time(results, project_id)
                if reset_at is not None:
                    try:
                        report_mtime = datetime.fromtimestamp(report_path.stat().st_mtime, timezone.utc)
                    except OSError:
                        report_mtime = None
                    if report_mtime is None or report_mtime <= reset_at:
                        continue
                    self._clear_reset_marker(results, project_id)
                workspace_project_dir = report_path.parent.parent
                artifacts_dir = report_path.parent
                report = self._read_json(report_path, default={})
                test_results = report.get('test_results', {})
                passed = test_results.get('passed', 0)
                failed = test_results.get('failed', 0)
                score = report.get('judge_score', {}).get('score') if isinstance(report.get('judge_score'), dict) else None
                generated_file_count = self._count_generated_project_files(workspace_project_dir / 'generated_project')
                project_record = {'project_id': project_id, 'workspace': str(workspace_project_dir), 'artifacts_dir': str(artifacts_dir), 'final_report': str(report_path), 'final_status': 'completed' if report.get('final_status') in ['completed', 'incomplete'] and (passed > 0 or score is not None) else report.get('final_status', 'unknown'), 'test_status': report.get('test_status', 'unknown'), 'validation_status': report.get('validation_status', 'unknown'), 'test_passed': passed, 'test_failed': failed, 'score': score, 'updated_at': self._now(), 'trace_count': len(report.get('traces', [])), 'generated_file_count': generated_file_count}
                results.setdefault('projects', {})[project_id] = project_record
                self._mirror_project_artifacts(session_dir, project_id, artifacts_dir, workspace_project_dir)
            for checkpoint_file in workspace_root.glob('level_*/*/artifacts/workflow_checkpoint.json'):
                project_id = checkpoint_file.parent.parent.name
                if str(project_id) in reset_ids:
                    continue
                existing = results.setdefault('projects', {}).get(project_id, {})
                if isinstance(existing, dict) and existing.get('final_status') == 'completed':
                    continue
                checkpoint = load_checkpoint(checkpoint_file.parent.parent)
                if not isinstance(checkpoint, dict) or checkpoint.get('status') == 'completed':
                    continue
                summary = checkpoint_summary(checkpoint)
                state = checkpoint.get('state') if isinstance(checkpoint.get('state'), dict) else {}
                workspace_project_dir = checkpoint_file.parent.parent
                generated_file_count = self._count_generated_project_files(workspace_project_dir / 'generated_project')
                project_record = {'project_id': project_id, 'workspace': str(workspace_project_dir), 'artifacts_dir': str(checkpoint_file.parent), 'final_report': str(workspace_project_dir / 'artifacts' / 'final_report.json') if (workspace_project_dir / 'artifacts' / 'final_report.json').exists() else None, 'final_status': 'interrupted_resumable', 'test_status': state.get('test_status', 'interrupted'), 'validation_status': state.get('validation_status', 'interrupted'), 'test_passed': 0, 'test_failed': 0, 'score': None, 'updated_at': self._now(), 'trace_count': summary.get('trace_count', 0), 'generated_file_count': generated_file_count, 'workflow_checkpoint': summary}
                results.setdefault('projects', {})[project_id] = project_record
                self._mirror_project_artifacts(session_dir, project_id, checkpoint_file.parent, workspace_project_dir)
            project_eval_experiments = Path('external/ProjectEval/experiments') / name / name
            aggregate_candidates = sorted(project_eval_experiments.glob('*/session_aggregate.json'))
            index_candidates = sorted(project_eval_experiments.glob('*/session_index.json'))
            if aggregate_candidates:
                aggregate_data = self._read_json(aggregate_candidates[-1], default={})
                if isinstance(aggregate_data, dict):
                    projects_payload = aggregate_data.get('projects', {})
                    if isinstance(projects_payload, dict):
                        for p_id, p_data in projects_payload.items():
                            if str(p_id) in reset_ids or str(p_id) in self._active_benchmark_project_ids(results):
                                continue
                            if p_id not in results.get('projects', {}):
                                continue
                            rec = results['projects'][p_id]
                            judge_score = p_data.get('judge_score')
                            if judge_score is None:
                                judge_score = p_data.get('score')
                            if judge_score is None and isinstance(p_data.get('judge_details'), dict):
                                judge_score = p_data.get('judge_details', {}).get('score')
                            if judge_score is not None:
                                rec['score'] = judge_score
                            counts = None
                            if isinstance(p_data.get('judge_details'), dict):
                                counts = p_data.get('judge_details', {}).get('counts')
                            if counts is None:
                                counts = p_data.get('counts')
                            if isinstance(counts, dict):
                                rec['test_passed'] = counts.get('passed', rec['test_passed'])
                                rec['test_failed'] = counts.get('failed', rec['test_failed'])
                            if p_data.get('source_run_id'):
                                rec['source_run_id'] = p_data.get('source_run_id')
                    results.setdefault('official', {})['judge_scores'] = aggregate_data
                    results['official']['export_dir'] = str(aggregate_candidates[-1].parent)
            if index_candidates:
                results.setdefault('official', {})['session_index'] = self._read_json(index_candidates[-1], default={})
            self._remove_reset_projects_from_payload(results)
            results['aggregate'] = self._compute_aggregate(results)
            self._write_json_atomic(session_dir / 'results.json', results)
            self.update_session_config(name, {})
            return results

    def update_official_results(self, name: str, *, mas_report: dict[str, Any] | None, judge_scores: dict[str, Any] | None, export_dir: str | None) -> None:
        with self._WRITE_LOCK:
            session_dir = self.create_session(name)
            results = self._read_json(session_dir / 'results.json', default={})
            if mas_report is not None:
                results.setdefault('official', {})['mas_report'] = mas_report
            if judge_scores is not None:
                results.setdefault('official', {})['judge_scores'] = judge_scores
            if export_dir is not None:
                results.setdefault('official', {})['export_dir'] = export_dir
            self._clear_reset_markers_for_payload(results, {'mas_report': mas_report, 'judge_scores': judge_scores})
            self._remove_reset_projects_from_payload(results)
            self._prune_empty_official_results(results)
            results['aggregate'] = self._compute_aggregate(results)
            self._write_json_atomic(session_dir / 'results.json', results)

    def compare_sessions(self, names: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name in names:
            detail = self.get_session_detail(name)
            config = detail['config']
            aggregate = detail['aggregate']
            projects = detail['projects']
            passed_tests = sum((self._coerce_int(p.get('test_passed')) or 0 for p in projects))
            failed_tests = sum((self._coerce_int(p.get('test_failed')) or 0 for p in projects))
            scored_projects = sum((1 for p in projects if p.get('score') is not None))
            rows.append({'session': name, 'status': config.get('status', 'idle'), 'completed_projects': aggregate['completed_projects'], 'total_projects': aggregate['total_projects'], 'local_pass_at_1': aggregate['local_pass_at_1'], 'judge_pass_at_1': aggregate.get('fixed_pass_at_1') or aggregate.get('official_score'), 'fixed_passed_tests': aggregate.get('fixed_passed_tests'), 'fixed_total_tests': aggregate.get('fixed_total_tests'), 'project_tests_passed': passed_tests, 'project_tests_failed': failed_tests, 'scored_projects': scored_projects, 'average_project_score': aggregate.get('average_project_score'), 'last_model_config': config.get('last_models_config_path'), 'level': config.get('last_level'), 'mode': config.get('last_mode')})
        return rows

    def read_log(self, name: str, log_name: str) -> str:
        session_dir = self.create_session(name)
        target = session_dir / 'logs' / f'{log_name}.log'
        return target.read_text(encoding='utf-8') if target.exists() else ''

    def _collect_project_details(self, session_dir: Path, results: dict[str, Any]) -> list[dict[str, Any]]:
        projects = []
        result_projects = results.get('projects', {})
        if not isinstance(result_projects, dict):
            result_projects = {}
        official_projects = self._collect_official_project_payloads(results)
        project_ids = set(result_projects.keys()) | set(official_projects.keys())
        for project_id in sorted(project_ids, key=self._project_sort_key):
            payload = result_projects.get(project_id, {})
            official_payload = official_projects.get(project_id, {})
            project_dir = session_dir / f'project_{project_id}'
            row = {}
            if isinstance(official_payload, dict):
                row.update(official_payload)
            if isinstance(payload, dict):
                row.update(payload)
            row['project_id'] = str(row.get('project_id') or project_id)
            row['project_dir'] = str(project_dir)
            row['has_artifacts'] = (project_dir / 'artifacts').exists()
            official_functions = self._project_test_counts.get(str(project_id), 0)
            if official_functions > 0:
                row['test_total'] = official_functions + 1
            report_path = project_dir / 'artifacts' / 'final_report.json'
            if report_path.exists():
                try:
                    report = self._read_json(report_path, default={})
                    test_results = report.get('test_results', {})
                    rep_passed = test_results.get('passed', 0)
                    rep_failed = test_results.get('failed', 0)
                    if row.get('test_passed', 0) == 0:
                        row['test_passed'] = rep_passed
                    if row.get('test_failed', 0) == 0:
                        row['test_failed'] = rep_failed
                    if row.get('score') is not None or row.get('test_passed', 0) > 0:
                        row['test_passed'] = row.get('test_passed', 0) + 1
                    js = report.get('judge_score')
                    if row.get('score') is None:
                        if isinstance(js, dict):
                            row['score'] = js.get('score')
                        elif isinstance(js, (int, float)):
                            row['score'] = js
                    if row.get('score') is None:
                        row['score'] = report.get('official_scores', {}).get('score')
                except Exception:
                    pass
            if row.get('score') is None:
                global_scores = results.get('official', {}).get('judge_scores', {})
                if isinstance(global_scores, dict) and isinstance(global_scores.get('projects'), dict):
                    proj_data = global_scores.get('projects', {}).get(str(project_id))
                elif isinstance(global_scores, dict):
                    proj_data = global_scores.get(str(project_id))
                else:
                    proj_data = None
                if isinstance(proj_data, dict):
                    row['score'] = proj_data.get('score') or proj_data.get('judge_score')
                else:
                    row['score'] = proj_data
            self._apply_official_project_counts(row, project_id)
            projects.append(row)
        return projects

    def _collect_official_project_payloads(self, results: dict[str, Any]) -> dict[str, dict[str, Any]]:
        official = results.get('official', {})
        if not isinstance(official, dict):
            return {}
        collected: dict[str, dict[str, Any]] = {}
        reset_ids = self._reset_project_ids(results)
        active_ids = self._active_benchmark_project_ids(results)

        def merge_project(project_id: Any, payload: dict[str, Any]) -> None:
            pid = str(project_id)
            if pid in reset_ids or pid in active_ids:
                return
            target = collected.setdefault(pid, {'project_id': pid})
            target.update(payload)
        judge_scores = official.get('judge_scores')
        if isinstance(judge_scores, dict):
            projects_payload = judge_scores.get('projects')
            if isinstance(projects_payload, dict):
                for project_id, payload in projects_payload.items():
                    if isinstance(payload, dict):
                        merge_project(project_id, payload)
        mas_report = official.get('mas_report')
        if isinstance(mas_report, dict):
            per_project = mas_report.get('per_project_results')
            if isinstance(per_project, dict):
                for project_id, payload in per_project.items():
                    if isinstance(payload, dict):
                        merge_project(project_id, payload)
            official_scores = mas_report.get('official_scores')
            selected_ids = {str(item) for item in mas_report.get('selected_project_ids') or []}
            if isinstance(official_scores, dict):
                project_scores = official_scores.get('judge_project_scores')
                if isinstance(project_scores, dict):
                    for project_id, score in project_scores.items():
                        merge_project(project_id, {'judge_score': score})
                function_details = official_scores.get('judge_function_details')
                if isinstance(function_details, dict):
                    for project_id, details in function_details.items():
                        if not isinstance(details, dict):
                            continue
                        counts = details.get('counts') if isinstance(details.get('counts'), dict) else {}
                        has_observed_tests = bool((counts or {}).get('total')) or details.get('score') is not None
                        if str(project_id) in selected_ids or has_observed_tests:
                            merge_project(project_id, {'judge_details': details})
        return collected

    def _apply_official_project_counts(self, row: dict[str, Any], project_id: str) -> None:
        details = row.get('judge_details') if isinstance(row.get('judge_details'), dict) else {}
        counts = details.get('counts') if isinstance(details.get('counts'), dict) else row.get('counts')
        if not isinstance(counts, dict):
            return
        function_passed = self._coerce_int(counts.get('passed')) or 0
        function_failed = self._coerce_int(counts.get('failed')) or 0
        function_total = self._coerce_int(counts.get('total'))
        score = self._coerce_float(row.get('score'))
        if score is None:
            score = self._coerce_float(row.get('judge_score'))
        if score is None:
            score = self._coerce_float(details.get('score'))
        if score is not None:
            row['score'] = score
        official_functions = self._project_test_counts.get(str(project_id), 0)
        total = official_functions + 1 if official_functions > 0 else None
        if total is None and function_total is not None:
            total = function_total + 1
        if total is not None:
            row['test_total'] = total
        runnable_passed = 1 if score and score > 0 else 0
        passed = function_passed + runnable_passed
        row['test_passed'] = passed
        if total is not None:
            row['test_failed'] = max(total - passed, function_failed)
        else:
            row['test_failed'] = function_failed

    @staticmethod
    def _project_sort_key(project_id: Any) -> tuple[int, Any]:
        try:
            return (0, int(str(project_id)))
        except (TypeError, ValueError):
            return (1, str(project_id))

    def _mirror_project_artifacts(self, session_dir: Path, project_id: str, artifacts_dir: Path, workspace_project_dir: Path) -> None:
        project_dir = session_dir / f'project_{project_id}'
        project_dir.mkdir(parents=True, exist_ok=True)
        target_artifacts = project_dir / 'artifacts'
        source_report = artifacts_dir / 'final_report.json'
        target_report = target_artifacts / 'final_report.json'
        if target_artifacts.exists() and source_report.exists() and target_report.exists():
            try:
                if target_report.stat().st_mtime >= source_report.stat().st_mtime:
                    (project_dir / 'workspace_path.txt').write_text(str(workspace_project_dir), encoding='utf-8')
                    return
            except OSError:
                pass
            shutil.rmtree(target_artifacts)
        elif target_artifacts.exists():
            shutil.rmtree(target_artifacts)
        shutil.copytree(artifacts_dir, target_artifacts)
        (project_dir / 'workspace_path.txt').write_text(str(workspace_project_dir), encoding='utf-8')

    @staticmethod
    def _count_generated_project_files(generated_root: Path) -> int:
        if not generated_root.exists():
            return 0
        count = 0
        for path in generated_root.rglob('*'):
            if not path.is_file():
                continue
            if '__pycache__' in path.parts:
                continue
            count += 1
        return count

    def _reset_project_ids(self, results: dict[str, Any]) -> set[str]:
        reset_projects = results.get('reset_projects')
        if not isinstance(reset_projects, dict):
            return set()
        return {str(project_id) for project_id in reset_projects}

    def _project_reset_time(self, results: dict[str, Any], project_id: Any) -> datetime | None:
        reset_projects = results.get('reset_projects')
        if not isinstance(reset_projects, dict):
            return None
        value = reset_projects.get(str(project_id))
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _clear_reset_marker(self, results: dict[str, Any], project_id: Any) -> None:
        reset_projects = results.get('reset_projects')
        if isinstance(reset_projects, dict):
            reset_projects.pop(str(project_id), None)
            if not reset_projects:
                results.pop('reset_projects', None)

    def _clear_reset_markers_for_payload(self, results: dict[str, Any], payload: Any) -> None:
        selected_ids = self._extract_selected_project_ids(payload)
        if not selected_ids:
            return
        for project_id in selected_ids:
            self._clear_reset_marker(results, project_id)

    def _mark_running_benchmark_projects(self, session_dir: Path, results: dict[str, Any], payload: dict[str, Any]) -> None:
        if payload.get('status') != 'running':
            return
        run_id = payload.get('run_id')
        project_ids = sorted(self._extract_selected_project_ids(payload), key=self._project_sort_key)
        if not run_id or not project_ids:
            return
        level = None
        request = payload.get('request')
        if isinstance(request, dict):
            level = request.get('level')
        if level is None:
            level = results.get('last_benchmark', {}).get('request', {}).get('level')
        projects = results.setdefault('projects', {})
        if not isinstance(projects, dict):
            projects = {}
            results['projects'] = projects
        for project_id in project_ids:
            workspace = None
            if level is not None:
                workspace = session_dir / 'workspace' / session_dir.name / f'level_{level}' / str(project_id)
            projects[str(project_id)] = {'project_id': str(project_id), 'workspace': str(workspace) if workspace is not None else None, 'final_status': 'running', 'test_status': 'running', 'validation_status': None, 'test_passed': 0, 'test_failed': 0, 'score': None, 'trace_count': 0, 'active_run_id': str(run_id), 'updated_at': self._now()}

    def _active_benchmark_project_ids(self, results: dict[str, Any]) -> set[str]:
        last_benchmark = results.get('last_benchmark')
        if not isinstance(last_benchmark, dict) or last_benchmark.get('status') != 'running':
            return set()
        return self._extract_selected_project_ids(last_benchmark)

    def _remove_reset_projects_from_payload(self, results: dict[str, Any]) -> None:
        reset_ids = self._reset_project_ids(results)
        if reset_ids:
            self._remove_projects_from_payload(results, list(reset_ids))
            self._prune_empty_official_results(results)

    def _prune_projecteval_session_files(self, name: str, project_ids: list[str] | set[str]) -> None:
        remove_ids = {str(project_id) for project_id in project_ids}
        if not remove_ids:
            return
        experiments_root = Path('external/ProjectEval/experiments') / name / name
        if not experiments_root.exists():
            return
        for aggregate_path in experiments_root.glob('*/session_aggregate.json'):
            aggregate = self._read_json(aggregate_path, default={})
            if not isinstance(aggregate, dict):
                continue
            projects = aggregate.get('projects')
            if isinstance(projects, dict):
                for project_id in remove_ids:
                    projects.pop(project_id, None)
                aggregate['fixed_pass_at_1'] = self._fixed_pass_at_1_from_project_payloads(projects)
            self._write_json_atomic(aggregate_path, aggregate)
        latest_run_ids_by_dir: dict[Path, Any] = {}
        for index_path in experiments_root.glob('*/session_index.json'):
            index = self._read_json(index_path, default={})
            if not isinstance(index, dict):
                continue
            runs = index.get('runs')
            if not isinstance(runs, list):
                continue
            kept_runs = []
            for run in runs:
                if not isinstance(run, dict):
                    kept_runs.append(run)
                    continue
                selected_ids = [str(item) for item in run.get('selected_project_ids') or []]
                project_ids_value = [str(item) for item in run.get('project_ids') or []]
                run_project_ids = set(selected_ids) | set(project_ids_value)
                if run_project_ids and run_project_ids.issubset(remove_ids):
                    run_id = run.get('run_id')
                    if run_id:
                        shutil.rmtree(index_path.parent / 'runs' / str(run_id), ignore_errors=True)
                    continue
                if selected_ids:
                    run['selected_project_ids'] = [item for item in selected_ids if item not in remove_ids]
                if project_ids_value:
                    run['project_ids'] = [item for item in project_ids_value if item not in remove_ids]
                judge_scores = run.get('judge_project_scores')
                if isinstance(judge_scores, dict):
                    for project_id in remove_ids:
                        judge_scores.pop(project_id, None)
                kept_runs.append(run)
            latest_run_id = kept_runs[-1].get('run_id') if kept_runs and isinstance(kept_runs[-1], dict) else None
            index['runs'] = kept_runs
            index['latest_run_id'] = latest_run_id
            latest_run_ids_by_dir[index_path.parent] = latest_run_id
            self._write_json_atomic(index_path, index)
        for aggregate_path in experiments_root.glob('*/session_aggregate.json'):
            if aggregate_path.parent not in latest_run_ids_by_dir:
                continue
            aggregate = self._read_json(aggregate_path, default={})
            if not isinstance(aggregate, dict):
                continue
            aggregate['latest_run_id'] = latest_run_ids_by_dir[aggregate_path.parent]
            self._write_json_atomic(aggregate_path, aggregate)
        for run_dir in experiments_root.glob('*/runs/*'):
            if not run_dir.is_dir():
                continue
            run_project_ids: set[str] = set()
            for metadata_path in (run_dir / 'summary' / 'run_manifest.json', run_dir / 'summary' / 'run_metadata.json', run_dir / 'summary' / 'run_summary.json'):
                metadata = self._read_json(metadata_path, default={})
                run_project_ids.update(self._extract_selected_project_ids(metadata))
            if not run_project_ids and '_projects_' in run_dir.name:
                project_suffix = run_dir.name.rsplit('_projects_', 1)[-1]
                run_project_ids.update((part for part in project_suffix.replace(',', '-').split('-') if part))
            if run_project_ids and run_project_ids.issubset(remove_ids):
                shutil.rmtree(run_dir, ignore_errors=True)

    def _fixed_pass_at_1_from_project_payloads(self, projects: dict[str, Any]) -> dict[str, Any]:
        passed = 0
        has_counts = False
        for project in projects.values():
            if not isinstance(project, dict):
                continue
            details = project.get('judge_details') if isinstance(project.get('judge_details'), dict) else {}
            counts = details.get('counts') if isinstance(details.get('counts'), dict) else project.get('counts')
            if not isinstance(counts, dict):
                continue
            has_counts = True
            passed += self._coerce_int(counts.get('passed')) or 0
            score = self._coerce_float(project.get('judge_score'))
            if score is None:
                score = self._coerce_float(project.get('score'))
            if score is None:
                score = self._coerce_float(details.get('score'))
            if score and score > 0:
                passed += 1
        return {'passed': passed if has_counts else 0, 'denominator': PROJECTEVAL_FIXED_TEST_TOTAL, 'score': passed / PROJECTEVAL_FIXED_TEST_TOTAL if has_counts else 0.0}

    def _remove_projects_from_payload(self, payload: Any, project_ids: list[str] | set[str]) -> None:
        remove_ids = {str(project_id) for project_id in project_ids}
        if not remove_ids:
            return
        seen: set[int] = set()

        def clean(value: Any) -> None:
            if not isinstance(value, dict):
                return
            value_id = id(value)
            if value_id in seen:
                return
            seen.add(value_id)
            for key in ('projects', 'per_project_results', 'judge_project_scores', 'judge_function_details'):
                nested = value.get(key)
                if isinstance(nested, dict):
                    for project_id in remove_ids:
                        nested.pop(project_id, None)
            selected = value.get('selected_project_ids')
            if isinstance(selected, list):
                value['selected_project_ids'] = [item for item in selected if str(item) not in remove_ids]
            for key in ('project_ids', 'included_project_ids', 'last_project_ids'):
                selected = value.get(key)
                if isinstance(selected, list):
                    value[key] = [item for item in selected if str(item) not in remove_ids]
            for project_id in remove_ids:
                value.pop(project_id, None)
                value.pop(f'score_{project_id}', None)
            for key, nested in value.items():
                if key == 'reset_projects':
                    continue
                if isinstance(nested, dict):
                    clean(nested)
                elif isinstance(nested, list):
                    cleaned_items = []
                    for item in nested:
                        if isinstance(item, dict):
                            item_ids = self._extract_selected_project_ids(item)
                            if item_ids and item_ids.issubset(remove_ids):
                                continue
                            clean(item)
                        cleaned_items.append(item)
                    value[key] = cleaned_items
        clean(payload)

    def _prune_empty_official_results(self, results: dict[str, Any]) -> None:
        official = results.get('official')
        if not isinstance(official, dict):
            return
        mas_report = official.get('mas_report')
        if isinstance(mas_report, dict):
            per_project_results = mas_report.get('per_project_results')
            selected_project_ids = mas_report.get('selected_project_ids')
            if isinstance(per_project_results, dict) and (not per_project_results):
                official.pop('mas_report', None)
            elif isinstance(selected_project_ids, list) and (not selected_project_ids):
                official.pop('mas_report', None)
        judge_scores = official.get('judge_scores')
        if isinstance(judge_scores, dict):
            projects_payload = judge_scores.get('projects')
            judge_project_scores = judge_scores.get('judge_project_scores')
            judge_function_details = judge_scores.get('judge_function_details')
            if isinstance(projects_payload, dict) and (not projects_payload) and isinstance(judge_project_scores, dict) and (not judge_project_scores) and isinstance(judge_function_details, dict) and (not judge_function_details):
                official.pop('judge_scores', None)
        if not official:
            results.pop('official', None)

    def _extract_selected_project_ids(self, payload: Any) -> set[str]:
        selected: set[str] = set()
        seen: set[int] = set()

        def collect(value: Any) -> None:
            if not isinstance(value, dict):
                return
            value_id = id(value)
            if value_id in seen:
                return
            seen.add(value_id)
            raw_ids = value.get('selected_project_ids')
            if isinstance(raw_ids, list):
                selected.update((str(item) for item in raw_ids))
            for key in ('project_ids', 'projects'):
                raw = value.get(key)
                if isinstance(raw, list):
                    selected.update((str(item) for item in raw))
            for nested in value.values():
                if isinstance(nested, dict):
                    collect(nested)
                elif isinstance(nested, list):
                    for item in nested:
                        collect(item)
        collect(payload)
        return selected

    def _compute_aggregate(self, results: dict[str, Any]) -> dict[str, Any]:
        result_projects = results.get('projects', {})
        if not isinstance(result_projects, dict):
            result_projects = {}
        projects = self._collect_official_project_payloads(results)
        for project_id, payload in result_projects.items():
            if isinstance(payload, dict):
                projects[str(project_id)] = {**projects.get(str(project_id), {}), **payload}
        total = len(projects)
        completed_projects = [p for p in projects.values() if p.get('final_status') == 'completed']
        completed_count = len(completed_projects)
        failed_validation = sum((1 for p in projects.values() if p.get('test_status') == 'failed_validation'))
        scores = []
        for project in projects.values():
            score = project.get('score')
            if score is None:
                score = project.get('judge_score')
            if score is None and isinstance(project.get('judge_details'), dict):
                score = project.get('judge_details', {}).get('score')
            if score is None:
                continue
            try:
                scores.append(float(score))
            except (TypeError, ValueError):
                continue
        avg_score = sum(scores) / len(scores) if scores else None
        fixed_pass_at_1 = self._extract_fixed_pass_at_1(results)
        official_score = fixed_pass_at_1.get('score')
        official = results.get('official', {})
        if official_score is None and isinstance(official, dict):
            judge_scores = official.get('judge_scores', {})
            score_row = judge_scores.get('judge_score_row') if isinstance(judge_scores, dict) else None
            if isinstance(score_row, dict):
                try:
                    official_score = float(score_row.get('score'))
                except (TypeError, ValueError):
                    official_score = None
        if official_score is None:
            official_score = avg_score
        return {'completed_projects': completed_count, 'total_projects': total, 'pending_projects': max(total - completed_count, 0), 'failed_validation_projects': failed_validation, 'local_pass_at_1': round(completed_count / total, 4) if total else 0.0, 'official_score': official_score, 'fixed_pass_at_1': fixed_pass_at_1.get('score'), 'fixed_passed_tests': fixed_pass_at_1.get('passed'), 'fixed_total_tests': fixed_pass_at_1.get('denominator', PROJECTEVAL_FIXED_TEST_TOTAL), 'average_project_score': avg_score}

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    def _extract_fixed_pass_at_1(self, results: dict[str, Any]) -> dict[str, Any]:
        official = results.get('official', {})
        if not isinstance(official, dict):
            return {'passed': None, 'denominator': PROJECTEVAL_FIXED_TEST_TOTAL, 'score': None}
        reset_ids = self._reset_project_ids(results)
        candidates: list[dict[str, Any]] = []
        judge_scores = official.get('judge_scores')
        if isinstance(judge_scores, dict):
            candidates.append(judge_scores)
        mas_report = official.get('mas_report')
        if isinstance(mas_report, dict) and isinstance(mas_report.get('official_scores'), dict):
            candidates.append(mas_report['official_scores'])
        for candidate in candidates:
            projects_payload = candidate.get('projects')
            if isinstance(projects_payload, dict):
                passed = 0
                has_counts = False
                for project_id, project in projects_payload.items():
                    if str(project_id) in reset_ids:
                        continue
                    if not isinstance(project, dict):
                        continue
                    details = project.get('judge_details') if isinstance(project.get('judge_details'), dict) else {}
                    counts = details.get('counts') if isinstance(details, dict) else project.get('counts')
                    if not isinstance(counts, dict):
                        continue
                    has_counts = True
                    function_passed = self._coerce_int(counts.get('passed')) or 0
                    project_score = self._coerce_float(project.get('judge_score'))
                    if project_score is None:
                        project_score = self._coerce_float(details.get('score'))
                    runnable_passed = 1 if project_score and project_score > 0 else 0
                    passed += function_passed + runnable_passed
                if has_counts:
                    return {'passed': passed, 'denominator': PROJECTEVAL_FIXED_TEST_TOTAL, 'score': passed / PROJECTEVAL_FIXED_TEST_TOTAL}
            metric = candidate.get('fixed_pass_at_1')
            if isinstance(metric, dict):
                passed = self._coerce_int(metric.get('passed'))
                denominator = self._coerce_int(metric.get('denominator')) or PROJECTEVAL_FIXED_TEST_TOTAL
                score = self._coerce_float(metric.get('score'))
                if score is None and passed is not None:
                    score = passed / denominator
                if score is not None:
                    return {'passed': passed, 'denominator': denominator, 'score': score}
            score_row = candidate.get('judge_score_row')
            if isinstance(score_row, dict):
                passed = self._coerce_int(score_row.get('passed'))
                if passed is not None:
                    return {'passed': passed, 'denominator': PROJECTEVAL_FIXED_TEST_TOTAL, 'score': passed / PROJECTEVAL_FIXED_TEST_TOTAL}
        return {'passed': None, 'denominator': PROJECTEVAL_FIXED_TEST_TOTAL, 'score': None}

    def _read_json(self, path: Path, *, default: Any) -> Any:
        if not path.exists():
            return default
        last_error: Exception | None = None
        for _ in range(5):
            try:
                content = path.read_text(encoding='utf-8')
                return json.loads(content)
            except (PermissionError, OSError) as e:
                last_error = e
                time.sleep(0.1)
            except json.JSONDecodeError:
                return default
        if last_error:
            self.logger.warning(f'Failed to read json at {path} after retries: {last_error}')
        return default

    def _write_json_atomic(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + '.tmp')
        serialized = json.dumps(payload, indent=2)
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                temp_path.write_text(serialized, encoding='utf-8')
                temp_path.replace(path)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.05 * (attempt + 1))
        if last_error is not None:
            raise last_error

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()