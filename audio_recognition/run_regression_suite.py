from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


TEST_MODULES = [
    "audio_recognition.tests.test_react_pipeline",
    "audio_recognition.tests.test_regression_suite",
    "audio_recognition.tests.test_planner_modes",
    "audio_recognition.tests.test_intermediate_store",
]


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromNames(TEST_MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
