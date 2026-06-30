from __future__ import annotations
from app.benchmark.contract import build_benchmark_contract, compact_contract_for_prompt
from app.benchmark.projecteval_runner import build_deterministic_parameter_answers, filter_projecteval_export_files, is_projecteval_managed_runserver, merge_parameter_answers, ProjectEvalMission, try_load_reusable_workspace_result, validate_parameter_answers

def test_build_benchmark_contract_classifies_selectors_and_risks() -> None:
    contract = build_benchmark_contract(project_id='99', project_type='Website', technical_stack='Django', level=2, mode='direct', testcode=[{'page': 'Home', 'function': [{'function': 'Log In', 'parameter': [{'name': 'test_url', 'description': 'the url'}, {'name': 'username_field', 'description': 'username field'}, {'name': 'login_button_id', 'description': 'login button id'}]}]}])
    assert contract['function_count'] == 1
    assert 'auth' in contract['risks']
    assert contract['selectors']['url'][0]['name'] == 'test_url'
    assert contract['selectors']['name'][0]['name'] == 'username_field'
    assert contract['selectors']['id'][0]['name'] == 'login_button_id'
    compact = compact_contract_for_prompt(contract)
    assert compact['summary']
    assert 'selectors' in compact

def test_build_benchmark_contract_extracts_testcode_dom_signals() -> None:
    contract = build_benchmark_contract(project_id='15', project_type='Website', technical_stack='Django', level=2, mode='direct', testcode=[{'page': 'Home', 'function': [{'function': "Button to 'HelloWorld' page", 'test': "button = driver.find_element(By.CLASS_NAME, 'button')\nbutton = driver.find_element(By.TAG_NAME, 'button')\nbutton = driver.find_element(By.ID, 'button')\nassert 'Hello World'.lower() in driver.page_source.lower()", 'parameter': [{'name': 'test_url', 'description': 'the url'}]}]}])
    assert contract['testcode_signals']['ids'] == ['button']
    assert contract['testcode_signals']['classes'] == ['button']
    assert contract['testcode_signals']['tags'] == ['button']
    assert 'Hello World' in contract['testcode_signals']['expected_texts']
    assert compact_contract_for_prompt(contract)['testcode_signals']['ids'] == ['button']

def test_merge_parameter_answers_uses_deterministic_fallback_for_bad_urls() -> None:
    preferred = [{'page': 'Home', 'function': [{'function': 'View', 'parameter': [{'name': 'test_url', 'answer': 'http://example.com'}, {'name': 'title_id', 'answer': ''}]}]}]
    fallback = [{'page': 'Home', 'function': [{'function': 'View', 'parameter': [{'name': 'test_url', 'answer': 'http://127.0.0.1:8000/'}, {'name': 'title_id', 'answer': 'welcome-message'}]}]}]
    merged = merge_parameter_answers(preferred, fallback)
    params = merged[0]['function'][0]['parameter']
    assert params[0]['answer'] == 'http://127.0.0.1:8000/'
    assert params[1]['answer'] == 'welcome-message'

def test_navigation_test_url_uses_source_page_not_destination() -> None:
    mission = type('Mission', (), {'testcode': [{'page': 'Home', 'function': [{'function': "Button to 'HelloWorld' page", 'test': "button = driver.find_element(By.ID, 'button')\nbutton.click()", 'parameter': [{'name': 'test_url', 'description': 'the url for test'}]}]}]})()
    fallback = build_deterministic_parameter_answers(mission, answer_project=[])
    fallback_params = fallback[0]['function'][0]['parameter']
    assert fallback_params[0]['answer'] == 'http://127.0.0.1:8000/'
    preferred = [{'page': 'Home', 'function': [{'function': "Button to 'HelloWorld' page", 'parameter': [{'name': 'test_url', 'answer': 'http://127.0.0.1:8000/helloworld/'}]}]}]
    merged = merge_parameter_answers(preferred, fallback)
    assert merged[0]['function'][0]['parameter'][0]['answer'] == 'http://127.0.0.1:8000/'

def test_display_page_test_url_can_use_display_page() -> None:
    mission = type('Mission', (), {'testcode': [{'page': 'HelloWorld', 'function': [{'function': "Display 'HelloWorld' message", 'test': "assert 'Hello World'.lower() in driver.page_source.lower()", 'parameter': [{'name': 'test_url', 'description': 'the url for test'}]}]}]})()
    fallback = build_deterministic_parameter_answers(mission, answer_project=[])
    assert fallback[0]['function'][0]['parameter'][0]['answer'] == 'http://127.0.0.1:8000/helloworld/'

def test_projecteval_port_cleanup_only_targets_django_runserver() -> None:
    assert is_projecteval_managed_runserver('python manage.py runserver localhost:8000')
    assert is_projecteval_managed_runserver('/venv/bin/python /tmp/project/manage.py runserver')
    assert not is_projecteval_managed_runserver('python -m http.server 8000')
    assert not is_projecteval_managed_runserver('vllm serve model --port 8000')

def test_website_export_adds_static_url_when_staticfiles_is_enabled() -> None:
    mission = ProjectEvalMission(project_id='15', project_type='website', technical_stack='Django', nl_prompt='', nl_checklist=[], skeleton=[], testcode=[])
    exported = filter_projecteval_export_files(mission, [{'file': 'settings.py', 'path': 'myproject/settings.py', 'code': "INSTALLED_APPS = ['django.contrib.staticfiles']\n"}, {'file': 'test.py', 'path': 'tests/test_generated.py', 'code': 'def test_x(): pass'}])
    assert len(exported) == 1
    assert "STATIC_URL = '/static/'" in exported[0]['code']

def test_validate_parameter_answers_reports_missing_ids() -> None:
    answer_project = [{'path': 'templates/home.html', 'code': '<div id="welcome-message"><input name="username"></div>'}]
    parameters = [{'page': 'Home', 'function': [{'function': 'View', 'parameter': [{'name': 'title_id', 'answer': 'missing-title'}, {'name': 'username_field', 'answer': 'username'}]}]}]
    validation = validate_parameter_answers(parameters, answer_project)
    assert validation['invalid'] == 1
    assert validation['issues'][0]['issue'] == 'id_not_found_in_exported_html'

def test_reusable_workspace_respects_core_mode(tmp_path) -> None:
    workspace = tmp_path / 'workspace'
    artifacts = workspace / 'artifacts'
    project_root = workspace / 'generated_project'
    artifacts.mkdir(parents=True)
    project_root.mkdir(parents=True)
    (artifacts / 'final_report.json').write_text('{"benchmark_summary": {"core_mode": "single_agent"}, "generated_root": "%s"}' % str(project_root).replace('\\', '\\\\'), encoding='utf-8')

    class DummyClient:
        config = type('Config', (), {'provider': 'mock'})()
    mission = type('Mission', (), {'project_id': '1', 'project_type': 'website', 'technical_stack': 'Django', 'testcode': []})()
    assert try_load_reusable_workspace_result(mission=mission, workspace=workspace, parameter_client=DummyClient(), parameter_repair_client=None, expected_core_mode='multi_agent') is None