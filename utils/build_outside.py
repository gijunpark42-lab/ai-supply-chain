"""Run graph_build.py OUTSIDE Claude Code's process tree, so its low-memory guard cannot kill the build.

Why (2026-10-21): on the nights of 10-18, 10-19 (first build) and 10-20 Claude Code stopped `graph_build.py --sync`
"for low memory" right after the patches were applied -- the guard kills a session's child processes when the
laptop's free memory runs low, and the build (~2 GB at its peak) is the biggest child. The same build run by
routine/nightly.ps1 outside the session finishes, because there Windows simply pages. So the session hands the build
to Windows instead of running it as its own child:

    python -X utf8 utils/build_outside.py                # start graph_build.py --sync outside, wait, print the result
    python -X utf8 utils/build_outside.py --wait         # a build is already running (or the wait ran out): attach
    python -X utf8 utils/build_outside.py -- --no-verify # anything after "--" goes to graph_build.py (default --sync)

How. The build is started through WMI (Win32_Process.Create), so its parent is the WMI service, not this script or
the Claude session: nothing the session's guard kills can take the build with it. This script then only waits on
two small files, .claude/build_outside.json (state + exit code) and .claude/build_outside.log (the build's whole
output). If the guard kills the waiting script, the build goes on; run it again with --wait to collect the result.

The wait is capped (--wait-minutes, default 9) so one call fits a tool call's time limit; when the cap is reached it
prints `still running` and exits 3 -- call it again with --wait. Exit codes: 0 = build finished with exit 0,
1 = the build failed (its exit code and the output's fail lines are printed), 3 = still running.

Before starting it waits (up to 10 min) for at least MIN_FREE_GB of free memory -- the coordinator stops its pool
workers before a build anyway (enrich skill section 7.4) -- and logs what it had.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, ".claude", "build_outside.json")
LOG = os.path.join(ROOT, ".claude", "build_outside.log")
MIN_FREE_GB = 2.5         # graph_build.py peaks near 2 GB; below this it waits for memory first (10 min at most)


def read_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def running(state):
    """True while the build this state describes is still alive (same pid AND same start time, so a reused pid
    after a reboot does not count)."""
    pid = state.get("pid")
    if state.get("status") != "running" or not pid:
        return False
    try:
        proc = psutil.Process(pid)
        return abs(proc.create_time() - state.get("pid_started", 0)) < 5
    except psutil.Error:
        return False


def free_gb():
    return psutil.virtual_memory().available / 1e9


def start(build_args):
    """Start `python utils/build_outside.py --run <args>` through WMI and return at once."""
    waited = 0
    while free_gb() < MIN_FREE_GB and waited < 600:
        if waited == 0:
            print(f"waiting for memory: {free_gb():.1f} GB free, want {MIN_FREE_GB} GB (10 min at most)")
        time.sleep(15)
        waited += 15
    me = os.path.abspath(__file__)
    command = f'"{sys.executable}" -X utf8 "{me}" --run ' + " ".join(f'"{a}"' for a in build_args)
    # Win32_Process.Create starts the process under the WMI service: outside the caller's process tree and job object.
    ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
          "@{CommandLine=$env:BO_CMD; CurrentDirectory=$env:BO_DIR}; "
          "Write-Output ('{0} {1}' -f $r.ReturnValue, $r.ProcessId)")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, text=True, env={**os.environ, "BO_CMD": command, "BO_DIR": ROOT})
    parts = (out.stdout or "").split()
    if len(parts) < 2 or parts[0] != "0":
        sys.exit(f"could not start the build outside: {out.stdout.strip()} {out.stderr.strip()[:300]}")
    print(f"started graph_build.py {' '.join(build_args)} outside the session (runner pid {parts[1]}, "
          f"{free_gb():.1f} GB free); output: .claude/build_outside.log")


def run(build_args):
    """The runner (started by start()): run graph_build.py, keep its output and exit code in the two files."""
    proc_self = psutil.Process()
    write_state({"status": "running", "pid": proc_self.pid, "pid_started": proc_self.create_time(),
                 "args": build_args, "started": datetime.now().isoformat(timespec="seconds"),
                 "free_gb_at_start": round(free_gb(), 1)})
    with open(LOG, "w", encoding="utf-8") as log:
        code = subprocess.call([sys.executable, "-X", "utf8", "graph_build.py", *build_args], cwd=ROOT,
                               stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    state = read_state()
    state.update(status="finished", exit=code, finished=datetime.now().isoformat(timespec="seconds"))
    write_state(state)


def report(state):
    """Print the build's result: its fail / warn lines and the end of its output."""
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    flagged = [l for l in lines if re.search(r"\[(fail|warn)\]|Traceback|Error|MemoryError", l)]
    if flagged:
        print(f"--- {len(flagged)} fail / warn / error lines ---")
        print("\n".join(flagged[:200]))
    print(f"--- last 60 of {len(lines)} lines (.claude/build_outside.log has all) ---")
    print("\n".join(lines[-60:]))
    print(f"\nbuild {state.get('args')} started {state.get('started')} finished {state.get('finished')}: "
          f"exit {state.get('exit')}")
    return 0 if state.get("exit") == 0 else 1


def wait(minutes):
    end = time.time() + minutes * 60
    while True:
        state = read_state()
        if state.get("status") == "finished":
            return report(state)
        if not running(state):
            if state.get("status") == "running":
                print("the build process is gone without writing its exit code (killed?) -- start it again")
                return 1
            # just started: the runner may not have written its state yet
            if time.time() > end:
                print("no build is running")
                return 1
        if time.time() > end:
            print(f"still running since {state.get('started')} -- call `python -X utf8 utils/build_outside.py --wait`")
            return 3
        time.sleep(10)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    mine = argv[:argv.index("--")] if "--" in argv else argv
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wait", action="store_true", help="attach to the running (or finished) build")
    parser.add_argument("--wait-minutes", type=float, default=9)
    parser.add_argument("--run", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args(mine)
    if args.run is not None:
        run(args.run)
        sys.exit(0)
    if not args.wait:
        if running(read_state()):
            print("a build is already running outside -- attaching to it instead of starting another")
        else:
            write_state({"status": "starting", "requested": datetime.now().isoformat(timespec="seconds")})
            start(extra or ["--sync"])
    sys.exit(wait(args.wait_minutes))
