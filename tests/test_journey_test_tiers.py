"""The non-browser journey tier must work without the optional browser extra."""

import os
import subprocess
import sys
from pathlib import Path


def test_non_browser_journey_tests_run_without_playwright():
    code = """
import sys
sys.modules['playwright'] = None
sys.modules['playwright.sync_api'] = None
import pytest
raise SystemExit(pytest.main([
    '-q', '-m', 'not browser',
    'tests/test_journey_runner.py', 'tests/test_journey_walker.py',
]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout
    assert "deselected" in result.stdout
    assert "skipped" not in result.stdout
