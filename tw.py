"""
tw.py -- Taiwan companies with Chinese-language calls: 法說會 video -> audio -> our own
         verbatim Chinese transcript -> transcripts/tw/*.txt

Who this is for: the TWSE/TPEx names that investing.py CANNOT cover because their investor
conferences are held in Chinese and no one publishes an English transcript -- Quanta, Wiwynn,
Foxconn, Wistron, Unimicron, Delta Electronics, GUC, Elite Material, Gold Circuit, Zhen Ding ...
(Taiwan names that ARE on Investing.com -- Alchip, MediaTek, Lite-On, Nanya Technology --
stay on investing.py and are excluded here.)

How it works (each stage verified on the Foxconn Q2 FY2026 call, 2026-08-12):
  1. MOPS 法人說明會一覽表 (t100sb02_1) lists every conference: company, date, subject.
     We keep rows that look like RESULTS calls (營運成果 / 財務報告 / self-hosted 法說會),
     not broker marketing tours.
  2. Taiwanese finance channels upload the full call to YouTube ("完整公開" -- e.g. 非凡).
     `yt-dlp` searches "<中文名> 法說會", keeps uploads near the conference date that run
     30+ minutes, and downloads the AUDIO only (~25MB for a 70-minute call).
  3. `faster-whisper` (local, free) transcribes the Chinese audio -- measured ~2.3x realtime
     on this machine's CPU, so a 1-hour call takes ~30 minutes. Run `transcribe` overnight
     for a busy week. The output is OUR OWN verbatim transcript, like DART filings it is a
     primary "what the company said" source; enrichment translates to English (Workflow 2b
     rules apply: English only in chains/).

    python tw.py sync                # MOPS -> find video -> download audio into tw/audio/
    python tw.py sync --month 202608 # backfill one month
    python tw.py transcribe          # whisper every downloaded audio -> transcripts/tw/*.txt (SLOW)
    python tw.py fetch <youtube url> --company "Quanta" --date 2026-08-13   # manual
    python tw.py pending / done      # the enrichment queue

No video found (smaller companies, webex-only calls): sync prints `no_media` with the MOPS
subject so the user can hunt the replay by hand and pass it to `fetch`. Coverage is expected
to be strong for the AI-server large caps and spotty below that -- that is the honest deal.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).parent
METADATA = ROOT / "company_metadata.json"
OUT_DIR = ROOT / "transcripts" / "tw"
# Audio lives OUTSIDE the repo on purpose: the repo sits in OneDrive, and gigabytes of
# call video were being cloud-synced (and competing for memory/disk with whisper).
AUDIO_DIR = Path.home() / "tw_audio"                 # downloaded, not yet transcribed
AUDIO_DONE = Path.home() / "tw_audio" / "done"       # transcribed (kept until the user deletes)
STATE = ROOT / "tw" / "sync_state.json"      # conferences seen + their media status
PENDING = ROOT / "tw" / "pending.json"       # transcripts written, not yet enriched

MOPS_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"

# Companies THIS pipeline owns: TWSE/TPEx names whose calls are Chinese-only.
# stock code -> (canonical node name, Chinese name used for the YouTube search).
# Names covered by investing.py (Alchip, MediaTek, Lite-On, Nanya Technology) are absent.
COMPANIES = {
    "2382": ("Quanta", "廣達"),
    "6669": ("Wiwynn", "緯穎"),
    "2317": ("Foxconn", "鴻海"),
    "3231": ("Wistron", "緯創"),
    "3037": ("Unimicron", "欣興"),
    "2308": ("Delta Electronics", "台達電"),
    "3443": ("GUC (Global Unichip)", "創意"),
    "2383": ("Elite Material", "台光電"),
    "2368": ("Gold Circuit", "金像電"),
    "4958": ("Zhen Ding", "臻鼎"),
    "8046": ("Nan Ya PCB", "南電"),
    "3189": ("Kinsus", "景碩"),
    "5274": ("ASPEED", "信驊"),
    "8210": ("Chenbro", "勤誠"),
    "4938": ("Pegatron", "和碩"),
    "2376": ("Gigabyte", "技嘉"),
    "2327": ("Yageo", "國巨"),
    "6488": ("GlobalWafers", "環球晶"),
    "2345": ("Accton Technology", "智邦"),
    "2356": ("Inventec", "英業達"),
    "8299": ("Phison", "群聯"),
    "3035": ("Faraday Technology", "智原"),
    "2455": ("VPEC", "全新"),                # NB: metadata had 6729 (機光科技) by mistake; corrected 2026-08-31
    "6274": ("Taiwan Union Technology (TUC)", "台燿"),
    "6239": ("Powertech Technology", "力成"),
}

# A MOPS row is a RESULTS call (not a broker marketing event) when the subject says so.
RESULTS_RE = re.compile(r"營運成果|財務報告|財務業務|業績展望|季.{0,6}(法人說明會|法說)|自辦|召開.*法人說明會|線上法人說明會")


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


# ---------------------------------------------------------------- MOPS conference list

def mops_conferences(year_roc, month):
    """All 法說會 rows for one ROC year+month, both listed (sii) and OTC, for OUR companies.

    Returns [{code, name, zh, date, subject}]. MOPS serves plain HTML; the download of the
    attached PDFs is WAF-blocked, but this list page is open.
    """
    rows = []
    for typek in ("sii", "otc"):
        r = requests.post(MOPS_URL, data={
            "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
            "TYPEK": typek, "year": str(year_roc), "month": f"{month:02d}",
        }, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
            cells = [re.sub("<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(cells) < 6 or cells[0] not in COMPANIES:
                continue
            m = re.match(r"(\d{3})/(\d\d)/(\d\d)", cells[2])       # ROC date, e.g. 115/08/12
            if not m:
                continue
            when = date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
            name, zh = COMPANIES[cells[0]]
            # TWSE hosts many replays as plain files: irconference.twse.com.tw/<code>_<id>_<date>_<ch|en>.mp3/mp4
            # MOPS writes the href with double OR single quotes (single since 2026), so accept either
            replays = re.findall(r"""href=["'](https?://irconference\.twse\.com\.tw/[^"']+)["']""", tr)
            rows.append({"code": cells[0], "name": name, "zh": zh, "date": when,
                         "replay": replays[0] if replays else None,
                         "subject": re.sub(r"\s+", " ", cells[5])[:200]})
        time.sleep(1)
    return rows


# ---------------------------------------------------------------- YouTube search + audio

def ytdlp(*args):
    """Run yt-dlp as `python -m yt_dlp` (no PATH dependency); return stdout text."""
    p = subprocess.run([sys.executable, "-X", "utf8", "-m", "yt_dlp", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr


def find_video(zh_name, conf_date):
    """Search YouTube for the full call. Accepts an upload within [-2, +21] days of the
    conference that runs >= 25 minutes and mentions the company + 法說. Returns (url, title,
    duration_s) or None."""
    code, out, err = ytdlp("--print", "%(id)s\t%(duration)s\t%(upload_date)s\t%(title)s",
                           "--no-download", "--flat-playlist" if False else "--no-playlist",
                           f"ytsearch8:{zh_name} 法說會")
    best = None
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        vid, dur, up, title = parts
        try:
            dur = int(float(dur))
            up = datetime.strptime(up, "%Y%m%d").date()
        except ValueError:
            continue
        if dur < 25 * 60 or zh_name not in title or "法說" not in title:
            continue
        offset = (up - conf_date).days
        if -2 <= offset <= 21:
            if best is None or abs(offset) < best[3]:
                best = (f"https://www.youtube.com/watch?v={vid}", title, dur, abs(offset))
    return best[:3] if best else None


def download_file(url, out_path):
    """Plain streamed download for TWSE irconference files (no extractor needed)."""
    with requests.get(url, stream=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"}) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def download_audio(url, out_path):
    """Lowest-bitrate audio is plenty for speech; ~25MB per hour."""
    code, out, err = ytdlp("-f", "bestaudio[abr<70]/bestaudio", "-o", str(out_path),
                           "--no-part", "--no-playlist", url)
    if code != 0 or not out_path.exists():
        raise RuntimeError(f"yt-dlp failed: {err.strip()[-200:]}")


# ---------------------------------------------------------------- quarter + label

_LABEL = re.compile(r"^(?P<name>.+?) Q(?P<q>[1-4]) FY(?P<fy>20\d\d) \((?P<d>\d\d-\d\d-\d{4})\)$")


def quarter_for(name, conf_date):
    """Taiwan filers are calendar-year. Results-call season maps cleanly onto months:
    Jan-Mar = Q4 of the previous year; Apr-Jun = Q1; Jul-Sep = Q2; Oct-Dec = Q3.
    If the graph already has a newer convention for this company, the graph label + 1 wins
    (same rule as investing.py)."""
    month = conf_date.month
    if month <= 3:
        fy, q = conf_date.year - 1, 4
    else:
        fy, q = conf_date.year, (month - 4) // 3 + 1
    try:
        g = json.loads((ROOT / "graph" / "merged_graph.json").read_text(encoding="utf-8"))
        best = None
        for node in g["nodes"]:
            if node["id"] != name:
                continue
            for qd in node.get("quarterly_data", []):
                m = _LABEL.match(qd.get("quarter", ""))
                if m and m.group("name") == name:
                    d = datetime.strptime(m.group("d"), "%m-%d-%Y").date()
                    if best is None or d > best[2]:
                        best = (int(m.group("fy")), int(m.group("q")), d)
        if best and best[2] < conf_date:
            nfy, nq = (best[0] + 1, 1) if best[1] == 4 else (best[0], best[1] + 1)
            if (nfy, nq) != (fy, q) and (conf_date - best[2]).days < 130:
                fy, q = nfy, nq          # stay consistent with the graph's own history
    except FileNotFoundError:
        pass
    return fy, q


# ---------------------------------------------------------------- state / queue helpers

def _load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _queue(rows):
    pending = _load(PENDING, [])
    known = {(x["file"], x["label"]) for x in pending}
    for name, path, label in rows:
        row = {"kind": "transcript", "company": name,
               "file": str(path.relative_to(ROOT)).replace("\\", "/"), "label": label}
        if (row["file"], row["label"]) not in known:
            pending.append(row)
    _save(PENDING, pending)


# ---------------------------------------------------------------- stages

def sync(month=None):
    """Discover this month's (and last month's) results calls and download their audio.
    Fast stage -- no transcription here."""
    state = _load(STATE, {"seen": {}})        # "code|YYYY-MM-DD" -> status
    today = date.today()
    months = [(month // 100, month % 100)] if month else sorted(
        {(d.year, d.month) for d in (today, today - timedelta(days=28))})

    rows = []
    for y, m in months:
        rows += mops_conferences(y - 1911, m)
    # one row per (company, date); MOPS repeats the same conference across broker listings
    confs = {}
    for r in rows:
        if RESULTS_RE.search(r["subject"]):
            confs.setdefault(f"{r['code']}|{r['date']}", r)
    print(f"{len(confs)} results-type conference(s) for our companies in {months}")

    for key, r in sorted(confs.items()):
        if key in state["seen"] and state["seen"][key] != "no_media":
            continue
        if r["date"] > today:
            print(f"upcoming {r['name']:28s} {r['date']}  (will fetch after it happens)")
            continue
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        if r.get("replay"):
            # best case: TWSE's own replay file (prefer the Chinese track when both exist)
            url, title = r["replay"], "TWSE irconference replay"
            ext = url.rsplit(".", 1)[-1].lower()
            out = AUDIO_DIR / f"{slug(r['name'])}_{r['date']}.{ext if ext in ('mp3', 'mp4', 'm4a') else 'mp4'}"
            if not out.exists():
                print(f"replay   {r['name']:28s} {r['date']}  {url}")
                try:
                    download_file(url, out)
                except Exception as exc:
                    print(f"FAIL     {r['name']}: {exc}")
                    continue
        else:
            hit = find_video(r["zh"], r["date"])
            if not hit:
                state["seen"][key] = "no_media"
                print(f"no_media {r['name']:28s} {r['date']}  {r['subject'][:60]}")
                continue
            url, title, dur = hit
            out = AUDIO_DIR / f"{slug(r['name'])}_{r['date']}.m4a"
            if not out.exists():
                print(f"audio    {r['name']:28s} {r['date']}  {dur // 60}min  {title[:50]}")
                try:
                    download_audio(url, out)
                except Exception as exc:
                    print(f"FAIL     {r['name']}: {exc}")
                    continue
        meta = {"company": r["name"], "date": str(r["date"]), "url": url, "title": title}
        out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        state["seen"][key] = "audio"
    _save(STATE, state)
    waiting = sorted(p for ext in ("m4a", "mp3", "mp4", "webm")
                     for p in AUDIO_DIR.glob(f"*.{ext}")) if AUDIO_DIR.exists() else []
    print(f"\n{len(waiting)} audio file(s) waiting -- run `python tw.py transcribe` (slow, ~30min per call)")


def transcribe_file(audio_path):
    """Whisper one call. Chinese, verbatim, timestamped every segment. Returns (name, txt_path, label)."""
    # GOTCHA: this repo's av.py (Alpha Vantage) shadows the PyAV package that faster-whisper
    # imports as `av` when running from the repo root. Drop the repo root from sys.path and
    # purge any half-imported module before importing whisper.
    sys.path = [p for p in sys.path if str(Path(p or ".").resolve()) != str(ROOT.resolve())]
    for mod in ("av", "av.audio"):
        sys.modules.pop(mod, None)
    from faster_whisper import WhisperModel
    meta = json.loads(audio_path.with_suffix(".json").read_text(encoding="utf-8"))
    name = meta["company"]
    conf_date = datetime.strptime(meta["date"], "%Y-%m-%d").date()
    fy, q = quarter_for(name, conf_date)
    label = f"{name} Q{q} FY{fy} ({conf_date.strftime('%m-%d-%Y')})"

    model = WhisperModel("small", device="cpu", compute_type="int8")
    # Most calls are Mandarin, but some replays are the English track (Yageo files
    # ending _en.mp3) -- the meta sidecar's "lang" field overrides the default.
    lang = meta.get("lang", "zh")
    # No VAD: on a 2026-07-28 Faraday replay vad_filter=True dropped ~40% of the speech (1-3 min gaps), which breaks
    # the full-transcript rule. condition_on_previous_text=False keeps no-VAD decoding from looping on silence.
    segments, info = model.transcribe(str(audio_path), language=lang, beam_size=1, vad_filter=False,
                                      condition_on_previous_text=False)
    lines, chars = [], 0
    for s in segments:
        stamp = f"[{int(s.start // 60):02d}:{int(s.start % 60):02d}]"
        lines.append(f"{stamp} {s.text.strip()}")
        chars += len(s.text)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    txt = OUT_DIR / f"{slug(name)}_q{q}_{fy}.txt"
    head = [
        f"SOURCE: 法說會 audio transcribed locally with faster-whisper (small) -- {meta['url']}",
        f"VIDEO TITLE: {meta['title']}",
        f"CALL DATE: {conf_date.strftime('%m-%d-%Y')}",
        f"QUARTER: Q{q} FY{fy}",
        f"# source label: {label}",
        f"# note: verbatim Chinese speech-to-text, no speaker labels; treat numbers with care and",
        f"#       cross-check against the MOPS deck when a figure looks off",
        f"# segments: {len(lines)}   characters: {chars:,}",
        "", "---", "",
    ]
    txt.write_text("\n".join(head) + "\n".join(lines) + "\n", encoding="utf-8")
    AUDIO_DONE.mkdir(parents=True, exist_ok=True)
    audio_path.rename(AUDIO_DONE / audio_path.name)
    audio_path.with_suffix(".json").rename(AUDIO_DONE / audio_path.with_suffix(".json").name)
    return name, txt, label


def transcribe_all():
    done = []
    audios = sorted(p for ext in ("m4a", "mp3", "mp4", "webm")
                    for p in AUDIO_DIR.glob(f"*.{ext}")) if AUDIO_DIR.exists() else []
    for audio in audios:
        print(f"whisper  {audio.name} ...", flush=True)
        t0 = time.time()
        try:
            name, txt, label = transcribe_file(audio)
        except Exception as exc:
            print(f"FAIL     {audio.name}: {exc}")
            continue
        done.append((name, txt, label))
        print(f"saved    {label:45s} -> {txt.relative_to(ROOT)}  ({(time.time() - t0) / 60:.0f} min)")
    _queue(done)
    return done


# ---------------------------------------------------------------- CLI

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync"); s.add_argument("--month", type=int, help="YYYYMM backfill")
    sub.add_parser("transcribe")
    f = sub.add_parser("fetch"); f.add_argument("url"); f.add_argument("--company", required=True)
    f.add_argument("--date", required=True, help="conference date YYYY-MM-DD")
    sub.add_parser("pending"); sub.add_parser("done")
    args = ap.parse_args()

    if args.cmd == "sync":
        sync(args.month)
    elif args.cmd == "transcribe":
        rows = transcribe_all()
        print(f"\n{len(rows)} transcript(s) written; `python tw.py pending` shows the queue")
    elif args.cmd == "fetch":
        names = {n for n, _ in COMPANIES.values()}
        if args.company not in names:
            sys.exit(f"{args.company!r} is not a tw.py company; choices: {sorted(names)}")
        conf_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        out = AUDIO_DIR / f"{slug(args.company)}_{conf_date}.m4a"
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        download_audio(args.url, out)
        out.with_suffix(".json").write_text(json.dumps(
            {"company": args.company, "date": str(conf_date), "url": args.url,
             "title": "manual fetch"}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"audio saved -> {out}; run `python tw.py transcribe`")   # AUDIO_DIR is outside the repo: no relative_to(ROOT)
    elif args.cmd == "pending":
        rows = _load(PENDING, [])
        for r in rows:
            print(f"{r['company']:32s} {r['label']:45s} {r['file']}")
        print(f"{len(rows)} pending")
    elif args.cmd == "done":
        _save(PENDING, [])
        print("queue cleared")
