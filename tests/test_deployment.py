import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_python_from_project(code):
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_entrypoint_imports_from_project_root():
    result = run_python_from_project("import Dexweb; print(Dexweb.app.name)")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "dexweb"


def test_wsgi_app_imports_from_project_root():
    result = run_python_from_project("from wsgi import app; print(app.name)")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "dexweb"
