import json
import tomllib
import urllib.request
from pathlib import Path

pairs = set()
for item in tomllib.loads(Path("uv.lock").read_text())["package"]:
    if "registry" in item.get("source", {}):
        pairs.add(("PyPI", item["name"], item["version"]))
for path in Path(".").glob("**/Cargo.lock"):
    if ".superpowers" in path.parts or "target" in path.parts:
        continue
    for item in tomllib.loads(path.read_text())["package"]:
        if item.get("source", "").startswith("registry+"):
            pairs.add(("crates.io", item["name"], item["version"]))
pairs = sorted(pairs)
request = urllib.request.Request(
    "https://api.osv.dev/v1/querybatch",
    data=json.dumps(
        {
            "queries": [
                {"package": {"ecosystem": e, "name": n}, "version": v}
                for e, n, v in pairs
            ]
        }
    ).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=60) as stream:
    result = json.load(stream)
findings = [
    {"ecosystem": e, "name": n, "version": v, "vulns": r["vulns"]}
    for (e, n, v), r in zip(pairs, result["results"], strict=True)
    if r.get("vulns")
]
out = {"packages_queried": len(pairs), "findings": findings}
Path("/tmp/mnemosyne-osv-audit.json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
