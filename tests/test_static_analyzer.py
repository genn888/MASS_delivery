from __future__ import annotations
from pathlib import Path
from app.analysis.static_analyzer import analyze_generated_project

def test_django_manage_py_can_be_nested(tmp_path: Path) -> None:
    project = tmp_path / 'generated_project'
    nested = project / 'site'
    package = nested / 'site'
    package.mkdir(parents=True)
    (nested / 'manage.py').write_text("print('ok')\n", encoding='utf-8')
    (package / 'settings.py').write_text("SECRET_KEY = 'x'\n", encoding='utf-8')
    result = analyze_generated_project(project)
    assert result['success'] is True
    assert all((issue['code'] != 'django_missing_manage_py' for issue in result['issues']))

def test_django_modelform_rejects_noneditable_model_fields(tmp_path: Path) -> None:
    project = tmp_path / 'generated_project'
    app = project / 'core'
    app.mkdir(parents=True)
    (project / 'manage.py').write_text("print('ok')\n", encoding='utf-8')
    (app / 'models.py').write_text('from django.db import models\n\nclass Purchase(models.Model):\n    datetime = models.DateTimeField(auto_now_add=True)\n    amount = models.DecimalField(max_digits=8, decimal_places=2)\n', encoding='utf-8')
    (app / 'forms.py').write_text("from django import forms\nfrom .models import Purchase\n\nclass PurchaseForm(forms.ModelForm):\n    class Meta:\n        model = Purchase\n        fields = ['datetime', 'amount']\n", encoding='utf-8')
    result = analyze_generated_project(project)
    assert result['success'] is False
    assert any((issue['code'] == 'django_modelform_noneditable_field' for issue in result['issues']))

def test_static_analyzer_warns_when_testcode_dom_probe_is_absent(tmp_path: Path) -> None:
    project = tmp_path / 'generated_project'
    templates = project / 'app' / 'templates'
    templates.mkdir(parents=True)
    (project / 'manage.py').write_text("print('ok')\n", encoding='utf-8')
    (templates / 'home.html').write_text('<a id="btn-helloworld" href="/helloworld/">HelloWorld</a>', encoding='utf-8')
    result = analyze_generated_project(project, benchmark_contract={'testcode_signals': {'ids': ['button'], 'classes': ['button'], 'tags': ['button']}})
    assert result['success'] is True
    assert any((issue['code'] == 'testcode_signal_missing_dom_probe' for issue in result['issues']))