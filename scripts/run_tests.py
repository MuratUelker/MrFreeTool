#!/usr/bin/env python3
"""Run the MrFreeTool test suite.

    python3 scripts/run_tests.py            # everything
    python3 scripts/run_tests.py -v         # verbose
    python3 scripts/run_tests.py naming     # only tests/test_naming.py

No FreeCAD required: the modules under test are written to run without it.
"""

import argparse
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pattern", nargs="?", default="test_*.py", help="test file pattern")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-f", "--failfast", action="store_true")
    args = parser.parse_args()

    loader = unittest.TestLoader()
    if args.pattern != "test_*.py":
        loader.testNamePatterns = [args.pattern if args.pattern.startswith("test") else "test_" + args.pattern]

    suite = loader.discover(start_dir=os.path.join(ROOT, "tests"), top_level_dir=ROOT, pattern=args.pattern)
    if args.failfast:
        suite = _FailFast(suite)

    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


class _FailFast(unittest.TestSuite):
    """Stop at the first failure, to keep the feedback loop short."""

    def run(self, result, debug=False):
        top = super().run(result, debug)
        if top and not result.wasSuccessful():
            print("\n(stopped at first failure; drop --failfast to run everything)")
        return top


if __name__ == "__main__":
    raise SystemExit(main())
