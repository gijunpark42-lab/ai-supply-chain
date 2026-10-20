"""After a nightly publish: is the enriched map served over MCP up to date? (user, 2026-10-20: "앞으로 enrich할 때도
mcp도 같이 업데이트")

Both MCP servers read the built data, so a publish updates them by itself:
  - nodus42_mcp.py (local, Claude Desktop on this PC) reads graph/ in this checkout;
  - https://nodus42.com/api/mcp (remote, the Claude apps on phone / web) reads the copy the site deploys, a few
    minutes after the publish merges into main.
This script asks both for map_status and waits (up to --minutes) until the remote one reports the same number of
facts as the local graph. It prints one line for routine/nightly.ps1's log and always exits 0 (a check, not a gate).

    python -X utf8 utils/mcp_check.py                 # default: wait up to 15 minutes
    python -X utf8 utils/mcp_check.py --minutes 0     # ask once
"""
import argparse
import asyncio
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
REMOTE = "https://nodus42.com/api/mcp"


async def remote_status(url):
    """map_status from the remote server, through the MCP protocol itself (as the Claude apps call it)."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with streamable_http_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            result = await session.call_tool("map_status", {})
            return json.loads(result.content[0].text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=15, help="how long to wait for the site's deploy")
    ap.add_argument("--url", default=REMOTE)
    args = ap.parse_args()

    os.environ.setdefault("NODUS42_DATA", ROOT)
    import nodus42_mcp                                  # the local server's own lookup
    local = nodus42_mcp.map_status()
    want = local["company_facts"]

    deadline = time.time() + args.minutes * 60
    remote, error = None, None
    while True:
        try:
            remote = asyncio.run(remote_status(args.url))
            error = None
        except Exception as exc:                        # site redeploying, network: try again until the deadline
            error = f"{type(exc).__name__}: {exc}"[:200]
        if remote and remote.get("company_facts") == want:
            break
        if time.time() >= deadline:
            break
        time.sleep(60)

    if remote and remote.get("company_facts") == want:
        print(f"mcp_check: OK - local and remote MCP both serve {local['companies']} companies, {want} facts, "
              f"newest source {local['newest_source_date']}")
    elif remote:
        print(f"mcp_check: remote MCP still behind - local {want} facts, remote {remote.get('company_facts')} "
              f"(the site may still be deploying)")
    else:
        print(f"mcp_check: remote MCP not reachable ({error}); local serves {want} facts")


if __name__ == "__main__":
    main()
