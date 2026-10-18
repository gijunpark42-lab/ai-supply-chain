"""Offline tests of the graph build (graph_build.py, relations.py, utils/check_relations.py).

Run from the repo root (they are NOT part of market/selftest.py, which runs only tests/market/):
    python -X utf8 -m unittest discover -s tests/graph -t .
Every test builds in a temporary folder, so chains/, relations/ and graph/ in the repo are never touched.
"""
