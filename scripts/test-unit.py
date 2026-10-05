#!/usr/bin/env python3
"""Run Python unit tests without browser, HTTP-server, tmux or installation E2E jobs."""
from pathlib import Path
import sys
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'tests/backend'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DIRECTORY))
warnings.simplefilter('error', ResourceWarning)
EXCLUDED = {'test_http.py', 'test_tmux.py', 'test_installer.py'}
suite = unittest.TestSuite()
loader = unittest.TestLoader()
for path in sorted(DIRECTORY.glob('test_*.py')):
    if path.name not in EXCLUDED:
        module_suite = loader.loadTestsFromName(path.stem)
        for case_suite in module_suite:
            if path.stem == 'test_lmstudio' and any('.LMStudioTests.' in test.id() for test in case_suite):
                continue  # Legacy loopback HTTP/relay integration class.
            suite.addTests(case_suite)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
