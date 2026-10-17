"""Shared helpers for the tests in tests/market/: where the fixtures are, how to read them, and a test case
whose market/history and graph folders are temporary (so a builder run in a test never touches real files)."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import market.common as common

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The builders keep the last 365 days counted from "today". The tests pin today to the day the fixtures were
# recorded, so a test does not start failing next year just because its rows fell out of the window.
FIXED_TODAY = "2026-10-17"


def fixture_text(name):
    """A text fixture as one string."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_jsonl(name):
    """A JSONL fixture as a list of dicts (one per line)."""
    return [json.loads(line) for line in fixture_text(name).splitlines() if line.strip()]


def quietly(function, *args, **kwargs):
    """Call `function` without its progress lines (a builder prints a summary and warnings, which would only
    clutter the test output). Returns what the function returns."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return function(*args, **kwargs)


class TempDataTestCase(unittest.TestCase):
    """A test case with fresh, empty history/ and graph/ folders in a temporary directory.

    market.common.HISTORY and market.common.GRAPH point there during each test, and so do the HISTORY / GRAPH /
    today names of every module listed in PATCHED_MODULES (a module that did `from market.common import HISTORY`
    has its own copy of the name, so it must be patched too). Everything is restored after each test."""

    PATCHED_MODULES = ()          # e.g. (market.insiders,) in a subclass

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="market_selftest_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.history = self.tmp / "history"
        self.graph = self.tmp / "graph"
        self.history.mkdir()
        self.graph.mkdir()
        targets = [common] + list(self.PATCHED_MODULES)
        replacements = {"HISTORY": self.history, "GRAPH": self.graph, "today": lambda: FIXED_TODAY}
        for module in targets:
            for name, value in replacements.items():
                if hasattr(module, name):
                    patcher = mock.patch.object(module, name, value)
                    patcher.start()
                    self.addCleanup(patcher.stop)

    def put_history(self, dataset, fixture_name):
        """Copy a JSONL fixture into the temporary history folder as <dataset>.jsonl."""
        shutil.copyfile(FIXTURES / fixture_name, self.history / f"{dataset}.jsonl")

    def read_graph(self, relative_path):
        """A JSON file the builder wrote into the temporary graph folder."""
        return json.loads((self.graph / relative_path).read_text(encoding="utf-8"))
