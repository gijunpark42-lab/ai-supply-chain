import json, os

# Map: wrong name -> correct name
# Correct name = the version that should win across all files
RENAMES = {
    "Amazon AWS":        "Amazon",
    "Amkor":             "Amkor Technology",
    "Google Cloud":      "Google",
    "Microsoft Azure":   "Microsoft",
    "Thinking Machines": "Thinking Machines Lab",
    "StacyX AI":         "SpaceX",
    "Pure Storage":      "Everpure",
    "Cipher Mining":     "Cipher Digital",
    "Naver Cloud":       "Naver",
}

def rename_all(obj, renames):
    """Walk the full JSON tree — rename company fields AND fix names inside signal/source text."""
    if isinstance(obj, dict):
        if "company" in obj and obj["company"] in renames:
            obj["company"] = renames[obj["company"]]
        for key in ("signal", "source"):  # fix company names embedded in text
            if key in obj:
                for old, new in renames.items():
                    obj[key] = obj[key].replace(old, new)
        for v in obj.values():
            rename_all(v, renames)
    elif isinstance(obj, list):
        for item in obj:
            rename_all(item, renames)

for fname in sorted(os.listdir("chains")):
    if not fname.endswith(".json"):
        continue

    path = f"chains/{fname}"
    with open(path, encoding="utf-8") as f:
        chain = json.load(f)

    # Count how many changes happen (track via a simple counter)
    before = json.dumps(chain)
    rename_all(chain, RENAMES)
    after = json.dumps(chain)

    changed = [old for old in RENAMES if old in before]
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(chain, f, indent=2, ensure_ascii=False)
        print(f"{fname}: renamed {changed}")
    else:
        print(f"{fname}: no changes needed")

print("\nDone. Re-running check_names.py to verify...")
print("=" * 50)

# Quick verify — just show remaining duplicates
all_names = {}
for fname in sorted(os.listdir("chains")):
    if not fname.endswith(".json"):
        continue
    with open(f"chains/{fname}", encoding="utf-8") as f:
        chain = json.load(f)
    for tier in chain["flow"]:
        for p in tier["players"]:
            all_names.setdefault(p["company"], set()).add(fname)
            for e in p.get("connects_to", []):
                all_names.setdefault(e["company"], set()).add(fname)

print("Companies that appear in 2+ files (should be identical names now):")
for name, files in sorted(all_names.items()):
    if len(files) >= 2:
        print(f"  {name}")
