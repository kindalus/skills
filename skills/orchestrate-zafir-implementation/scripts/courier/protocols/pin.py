"""Pin the sha256 of every protocol module into PUBLISHED.json (run once when a version is published)."""
import hashlib, json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
out = {f"{p.parent.name}/{p.stem}": hashlib.sha256(p.read_bytes()).hexdigest()
       for p in sorted(here.glob("*/*.py"))}
current = json.loads((here / "PUBLISHED.json").read_text()) if (here / "PUBLISHED.json").exists() else {}
changed = {k for k in current if k in out and current[k] != out[k]}
if changed and "--force" not in sys.argv:
    sys.exit(f"published protocols changed: {sorted(changed)}; publish a new version instead")
(here / "PUBLISHED.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
print(json.dumps(out, indent=2))
