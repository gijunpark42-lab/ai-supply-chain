// up.mjs — "ask 실행": put the local Opus engine behind the live site in ONE command.
//
//   node up.mjs              start what is not running, point Vercel at the tunnel, redeploy, verify
//   node up.mjs --force      redo the Vercel part even if the tunnel address did not change
//   node up.mjs --no-vercel  only start the runner + tunnel (print the address, touch nothing on Vercel)
//
// Steps, each skipped when it is already done:
//   1. start local-ask/server.mjs, detached (logs/runner.out)   → GET http://127.0.0.1:8787/health
//   2. start a Cloudflare quick tunnel, detached (logs/tunnel.out) → https://xxxx.trycloudflare.com
//      (a quick tunnel needs no account, but its address changes every time it starts — hence step 3)
//   3. set LOCAL_ASK_URL on Vercel (production) to that address and redeploy the current production
//      build — env vars are baked in at deploy time, so without a redeploy the site keeps the old one
//   4. ask the live site one small question and check the answer came from the local engine
//
// logs/state.json remembers the pids and the address so `down.mjs` can stop what this started and
// a second `up.mjs` can tell that nothing changed. Needs: the Vercel CLI logged in (`vercel login`),
// cloudflared installed, and ASK_SHARED_SECRET in local-ask/.env (the same value must already be
// set on Vercel — this script never touches secrets).

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
try {
  process.loadEnvFile(path.join(HERE, ".env"));
} catch {
  /* no .env — the checks below will complain */
}

const SECRET = process.env.ASK_SHARED_SECRET || "";
const PORT = Number(process.env.PORT || 8787);
const LOCAL = `http://127.0.0.1:${PORT}`;
const WEB_DIR = path.join(HERE, "..", "web"); // the Vercel-linked folder
const SCOPE = process.env.VERCEL_SCOPE || "gijun42";
const PROJECT = process.env.VERCEL_PROJECT || "reticulum-ai";
const SITE = (process.env.ASK_SITE || "https://gijun42.com").replace(/\/+$/, "");
const CLOUDFLARED =
  process.env.CLOUDFLARED_BIN ||
  (process.platform === "win32" ? "C:\\Program Files (x86)\\cloudflared\\cloudflared.exe" : "cloudflared");
const LOG_DIR = path.join(HERE, "logs");
const STATE_FILE = path.join(LOG_DIR, "state.json");
const FORCE = process.argv.includes("--force");
const NO_VERCEL = process.argv.includes("--no-vercel");

// 2026-09-13: the runner is reached through a FIXED Tailscale Funnel address
// (https://gijun-pc.tail362ef7.ts.net) that is already set as LOCAL_ASK_URL on
// Vercel. This script would overwrite it with a throwaway trycloudflare address
// and break Ask. Refuse unless the caller explicitly opts back into Cloudflare.
if (!process.argv.includes("--cloudflare")) {
  console.error(
    "✗ Not running: Ask uses the fixed Tailscale Funnel address now (see local-ask/README.md).\n" +
      "  Check/restart with the ask-server skill or the desktop 'Ask Switch'.\n" +
      "  Only if the Funnel is gone for good: node up.mjs --cloudflare"
  );
  process.exit(1);
}

if (SECRET.length < 16) {
  console.error("ASK_SHARED_SECRET is missing in local-ask/.env — see local-ask/README.md.");
  process.exit(1);
}
fs.mkdirSync(LOG_DIR, { recursive: true });

// ── Small helpers ──────────────────────────────────────────────────────────

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function fail(message) {
  console.error("✗ " + message);
  process.exit(1);
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch {
    return {};
  }
}

function writeState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

/** Is a process with this pid still running? (signal 0 = just check) */
function alive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function safeRead(file) {
  try {
    return fs.readFileSync(file, "utf8");
  } catch {
    return "";
  }
}

/** GET {base}/health with the secret; the JSON when ok, else null. */
async function health(base, timeoutMs) {
  try {
    const r = await fetch(`${base}/health`, {
      headers: { "x-ask-secret": SECRET },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!r.ok) return null;
    const j = await r.json();
    return j && j.ok === true ? j : null;
  } catch {
    return null;
  }
}

/** Start a program that outlives this script; its output goes to a log file. */
function startDetached(cmd, args, logFile) {
  const out = fs.openSync(logFile, "w");
  const child = spawn(cmd, args, {
    cwd: HERE,
    detached: true,
    stdio: ["ignore", out, out],
    windowsHide: true,
  });
  child.unref();
  return child.pid;
}

/**
 * Run one Vercel CLI command in web/ (the linked project) and capture its text.
 * `vercel` is a .cmd shim on Windows, so it has to go through the shell; the
 * command is built as ONE string (Node warns when args and `shell` are mixed).
 * Every argument here is a plain word or a URL we generated — nothing to escape.
 */
function vercel(args) {
  const command = ["vercel", ...args, "--scope", SCOPE].join(" ");
  const r = spawnSync(command, {
    cwd: WEB_DIR,
    shell: true,
    encoding: "utf8",
    windowsHide: true,
  });
  const text = ((r.stdout || "") + (r.stderr || "")).replace(/\x1b\[[0-9;]*m/g, "");
  return { ok: r.status === 0, text };
}

// ── Steps ──────────────────────────────────────────────────────────────────

async function ensureRunner(state) {
  let h = await health(LOCAL, 2000);
  if (h) {
    console.log(`1. runner: already up on ${LOCAL} (${h.model}, effort ${h.effort})`);
    return;
  }
  const pid = startDetached(process.execPath, [path.join(HERE, "server.mjs")], path.join(LOG_DIR, "runner.out"));
  for (let i = 0; i < 30 && !h; i++) {
    await sleep(500);
    h = await health(LOCAL, 2000);
  }
  if (!h) fail("the runner did not come up — see local-ask/logs/runner.out");
  state.runnerPid = pid;
  console.log(`1. runner: started (pid ${pid}) on ${LOCAL} (${h.model}, effort ${h.effort})`);
}

async function ensureTunnel(state) {
  if (alive(state.tunnelPid) && state.url && (await health(state.url, 8000))) {
    console.log(`2. tunnel: already up at ${state.url}`);
    return;
  }
  if (CLOUDFLARED.includes("\\") && !fs.existsSync(CLOUDFLARED))
    fail(`cloudflared not found at ${CLOUDFLARED} — install it with: winget install Cloudflare.cloudflared`);
  const logFile = path.join(LOG_DIR, "tunnel.out");
  const pid = startDetached(CLOUDFLARED, ["tunnel", "--url", LOCAL], logFile);
  // cloudflared prints the public address a few seconds after starting.
  let url = null;
  for (let i = 0; i < 60 && !url; i++) {
    await sleep(1000);
    const m = /https:\/\/[a-z0-9-]+\.trycloudflare\.com/.exec(safeRead(logFile));
    if (m) url = m[0];
  }
  const stopTunnel = () => {
    try {
      process.kill(pid);
    } catch {
      /* already gone */
    }
  };
  if (!url) {
    stopTunnel();
    fail("no trycloudflare.com address appeared in local-ask/logs/tunnel.out within 60 s");
  }
  // The address exists before it routes; wait until /health answers through it.
  let ok = null;
  for (let i = 0; i < 30 && !ok; i++) {
    await sleep(2000);
    ok = await health(url, 8000);
  }
  if (!ok) {
    stopTunnel();
    fail(`${url} does not reach the runner yet — this network probably blocks port 7844 (see local-ask/logs/tunnel.out)`);
  }
  state.tunnelPid = pid;
  state.url = url;
  console.log(`2. tunnel: ${url} (pid ${pid})`);
}

function updateVercel(state) {
  if (NO_VERCEL) {
    console.log("3. vercel: skipped (--no-vercel)");
    return;
  }
  if (!FORCE && state.vercelUrl === state.url) {
    console.log(`3. vercel: LOCAL_ASK_URL is already ${state.url} — no redeploy needed`);
    return;
  }
  const ls = vercel(["env", "ls"]);
  if (!/ASK_SHARED_SECRET/.test(ls.text))
    console.warn(
      "   ! ASK_SHARED_SECRET is not set on Vercel. Add it (Settings → Environment Variables, Production)\n" +
        "     with the value from local-ask/.env — the site cannot use the runner without it."
    );
  vercel(["env", "rm", "LOCAL_ASK_URL", "production", "--yes"]); // "not found" is fine
  const add = vercel(["env", "add", "LOCAL_ASK_URL", "production", "--value", state.url, "--yes"]);
  if (!add.ok) fail("vercel env add failed:\n" + add.text);
  console.log(`3. vercel: LOCAL_ASK_URL = ${state.url} — redeploying the current production build (about a minute)…`);

  // The newest production deployment is the first *.vercel.app address `vercel ls` prints.
  const list = vercel(["ls", PROJECT, "--environment", "production"]);
  const m = /https:\/\/[a-z0-9-]+\.vercel\.app/.exec(list.text);
  if (!m) fail("could not find the latest production deployment:\n" + list.text);
  const re = vercel(["redeploy", m[0]]); // waits until the new deployment is ready
  if (!re.ok) fail("vercel redeploy failed:\n" + re.text);
  const fresh = /https:\/\/[a-z0-9-]+\.vercel\.app/.exec(re.text);
  console.log(`   redeployed${fresh ? ` → ${fresh[0]}` : ""}`);
  state.vercelUrl = state.url;
  state.deployedAt = new Date().toISOString();
}

/** One real question to the live site; true when the local engine answered it. */
async function verifyLive() {
  const body = {
    question: "Which company started HBM4 mass production?",
    intent: "lookup",
    lang: "en",
    snippets: [
      {
        kind: "signal",
        company: "SK Hynix",
        chain: "hbm_memory",
        label: "SK Hynix Q2 FY2026 (08-14-2026)",
        date: "2026-08-14",
        text: "HBM4 12-Hi entered mass production in the quarter. Figure: HBM +30% QoQ",
        topics: ["hbm"],
      },
    ],
  };
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const t0 = Date.now();
      const r = await fetch(`${SITE}/api/ask`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(110_000),
      });
      const text = await r.text();
      const lines = text.trim().split("\n");
      let done = null;
      for (const line of lines) {
        try {
          const ev = JSON.parse(line);
          if (ev.type === "done") done = ev;
        } catch {
          /* not JSON (an error page) */
        }
      }
      if (r.ok && done) {
        const where = done.engine === "local" ? "your machine" : done.engine;
        console.log(`4. live check: ${SITE} answered with ${done.model} · effort ${done.effort} · ${where} · ${((Date.now() - t0) / 1000).toFixed(1)} s`);
        if (done.engine === "local") return true;
        console.log("   the site did not use the local engine yet (a deploy can take a moment to switch over)…");
      } else {
        console.log(`   live check attempt ${attempt}: HTTP ${r.status} ${text.slice(0, 160)}`);
      }
    } catch (e) {
      console.log(`   live check attempt ${attempt}: ${e.message}`);
    }
    await sleep(10_000);
  }
  return false;
}

async function main() {
  const state = readState();
  await ensureRunner(state);
  await ensureTunnel(state);
  writeState(state);
  updateVercel(state);
  writeState(state);
  const ok = NO_VERCEL ? true : await verifyLive();
  console.log(
    ok
      ? `\n✓ Ask on ${SITE} now answers with Opus (max effort) from this PC. Stop it with: node local-ask/down.mjs`
      : `\n! Runner and tunnel are up, but ${SITE} still answered elsewhere. Check that ASK_SHARED_SECRET on Vercel equals local-ask/.env, then run again with --force.`
  );
  process.exit(ok ? 0 : 2);
}

main().catch((e) => fail(e.stack || e.message));
