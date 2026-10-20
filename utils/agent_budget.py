"""How many enrich agents may work at once RIGHT NOW, from the free memory.

User, 2026-10-19: "메모리 로스안나게 에이전트최대갯수 매일루프에서조정시키자" — the nightly loop sets its own
agent ceiling so the laptop never runs out of memory (that is what killed graph_build.py three nights in a row).

The nightly coordinator runs this
  - before it starts its worker pool (the pool never grows past the number printed), and
  - again before graph_build.py, which needs its own reserve.

    python -X utf8 utils/agent_budget.py           ->  agents: 6  (free 8.3 GB of 15.4 GB; 0.75 GB each, 3.0 GB kept free)
    python -X utf8 utils/agent_budget.py --json    ->  {"agents": 6, "free_gb": 8.3, ...}

The numbers are deliberately cautious: an agent's own share is small, but the scripts it runs (a filing
reader, yt-dlp, a big grep) can take several hundred MB for a while.
"""
import json
import sys

import psutil

PER_AGENT_GB = 0.75   # one working agent: its tool processes plus headroom
RESERVE_GB = 3.0      # always kept free: graph_build.py (~2 GB peak since the 2026-10-19 evidence.py fix),
                      # the Claude session itself and Windows
MIN_AGENTS = 1        # one agent is always allowed, or nothing would ever get done
MAX_AGENTS = 20       # the old fixed ceiling (user, 2026-09-26)


def budget():
    """{'agents': n, 'free_gb': x, 'total_gb': y, ...} for the memory free at this moment."""
    memory = psutil.virtual_memory()
    free_gb = memory.available / 1e9          # what Windows can hand out without paging
    fits = int((free_gb - RESERVE_GB) // PER_AGENT_GB)
    agents = max(MIN_AGENTS, min(MAX_AGENTS, fits))
    return {"agents": agents, "free_gb": round(free_gb, 1), "total_gb": round(memory.total / 1e9, 1),
            "per_agent_gb": PER_AGENT_GB, "reserve_gb": RESERVE_GB}


if __name__ == "__main__":
    b = budget()
    if "--json" in sys.argv:
        print(json.dumps(b))
    else:
        print("agents: %d  (free %.1f GB of %.1f GB; %.2f GB each, %.1f GB kept free)"
              % (b["agents"], b["free_gb"], b["total_gb"], b["per_agent_gb"], b["reserve_gb"]))
