"""Offline regression tests of the daily market-data collectors (market/*.py), run every night by
market/selftest.py (user, 2026-10-17: "known parsing results pinned, run every night, offline").

Every test here must run OFFLINE and in seconds: inputs come from small files in tests/market/fixtures/, and
builders write into temporary folders (tests/market/helpers.py), never into the real market/history or graph.

To make "offline" a guarantee instead of a promise, importing this package switches network access off for the
whole test process: any attempt to look up a host name or open a connection raises at once (instead of hanging
on a slow source or silently fetching live data that would make a test pass for the wrong reason).
"""
import socket


def _no_network(*args, **kwargs):
    raise RuntimeError("tests/market must run offline: a test tried to use the network")


socket.getaddrinfo = _no_network          # host name lookups (requests / urllib3 start here)
socket.create_connection = _no_network    # direct connections
socket.socket.connect = _no_network       # any other socket
socket.socket.connect_ex = _no_network    # the same, in the form that returns an error code instead of raising
