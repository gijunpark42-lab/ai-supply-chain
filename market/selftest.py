"""Nightly self-test of the market-data parsers (user, 2026-10-17: regression tests that pin known parsing results,
run every night, offline).

The tests live in tests/market/ (stdlib unittest, one file per collector) and read only the small saved inputs in
tests/market/fixtures/: no network (tests/market/__init__.py switches it off for the test process), no API keys,
and nothing is written to market/history or graph (builders run in temporary folders). They take a few seconds.
They pin the cases the 2026-10-17 verification fixed (Alphabet's two-class share offering, Supermicro's common-stock
prospectus, per-line 10b5-1 flags, the Eli Lilly price typo, NRG's joint filers, Korean unit-price cells, the
financials' GAAP vs adjusted EPS rows and their adjusted-EPS history, ...), so a parser change that breaks one of
them is caught the same night instead of silently publishing wrong numbers.

This script runs them all and writes the outcome for the nightly routine:
    market/selftest_result.json   {"date", "ok", "passed", "failed": [{"test", "message"}]}
It prints the test runner's progress to stderr and ONE summary line to stdout (the nightly log keeps the last line),
and exits 0 when every test passed, 1 otherwise (also when no test was found at all).

CLI (from the repo root, with the project's Python):
    python -X utf8 market/selftest.py
    python -X utf8 -m unittest discover -s tests/market -t .     (the same tests, without the result file)
"""
import re
import sys
import time
import unittest
from pathlib import Path

# Running as a script puts market/ itself first on sys.path; use the repo root instead (same fix as run_all.py),
# so "from market.common import ..." and "from tests.market.helpers import ..." work from any folder.
_ROOT = Path(__file__).resolve().parent.parent
if sys.path and Path(sys.path[0] or ".").resolve() == _ROOT / "market":
    sys.path[0] = str(_ROOT)
elif str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from market.common import ROOT, today, write_json  # noqa: E402  (needs the sys.path fix above)

TESTS_DIR = ROOT / "tests" / "market"
RESULT_FILE = ROOT / "market" / "selftest_result.json"
MESSAGE_LINES = 5          # lines of the exception kept in the result file (a long diff is cut)
MESSAGE_CHARS = 600


def short_message(traceback_text):
    """One short line for the result file: the exception at the end of a traceback and the test line it came
    from, e.g. "AssertionError: 10000000000.0 != 18000000123.0 (test_financing_us.py line 36)".
    In a traceback, every 'File "...", line N' entry is followed by indented lines (the code, Python's ~~~^^^
    markers); the exception itself starts at the left margin after the LAST entry."""
    lines = [line.rstrip() for line in traceback_text.strip().splitlines() if line.strip()]
    entries = [i for i, line in enumerate(lines) if line.lstrip().startswith('File "')]
    if not entries:
        return " | ".join(line.strip() for line in lines[-MESSAGE_LINES:])[:MESSAGE_CHARS]
    last = entries[-1]
    exception = [line for line in lines[last + 1:] if not line.startswith(" ")][:MESSAGE_LINES]
    where = re.search(r'File "([^"]+)", line (\d+)', lines[last])
    text = " | ".join(exception) or lines[-1].strip()
    if where:
        text += f" ({Path(where.group(1)).name} line {where.group(2)})"
    return text[:MESSAGE_CHARS]


def run_tests():
    """Discover and run tests/market/. Returns (unittest result object, seconds taken)."""
    started = time.time()
    suite = unittest.defaultTestLoader.discover(start_dir=str(TESTS_DIR), top_level_dir=str(ROOT))
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=1)
    result = runner.run(suite)
    return result, time.time() - started


def summarize(result):
    """The result file's content: {"date", "ok", "passed", "failed": [{"test", "message"}]}."""
    failed = []
    # failures = an assertion did not hold; errors = a test crashed (or a test file could not be imported)
    for test, traceback_text in result.failures + result.errors:
        failed.append({"test": test.id(), "message": short_message(traceback_text)})
    for test in result.unexpectedSuccesses:
        failed.append({"test": test.id(), "message": "expected to fail, but passed"})
    if result.testsRun == 0:
        failed.append({"test": "discover", "message": f"no tests found in {TESTS_DIR}"})
    passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped) \
        - len(result.unexpectedSuccesses)
    return {"date": today(), "ok": not failed, "passed": max(passed, 0), "failed": failed}


def main():
    try:
        result, seconds = run_tests()
        summary = summarize(result)
    except Exception as e:                  # tests/market missing or not importable: still write a failed result
        seconds = 0.0
        summary = {"date": today(), "ok": False, "passed": 0,
                   "failed": [{"test": "discover", "message": f"{type(e).__name__}: {e}"[:MESSAGE_CHARS]}]}
    write_json(RESULT_FILE, summary)
    line = f"selftest: {summary['passed']} passed, {len(summary['failed'])} failed in {seconds:.1f} s"
    if summary["failed"]:
        line += " (first: " + summary["failed"][0]["test"] + ")"
    print(line)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
