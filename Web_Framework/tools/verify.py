"""Verify every delivered file and reject missing, changed or extra files."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
expected = {item["path"]: item for item in manifest["files"]}
actual = {
    p.relative_to(root).as_posix(): p
    for p in root.rglob("*")
    if p.is_file() and p != root / "MANIFEST.json"
}
assert actual.keys() == expected.keys(), (
    "Inventory mismatch",
    sorted(expected.keys() - actual.keys()),
    sorted(actual.keys() - expected.keys()),
)
for name, path in actual.items():
    assert not path.is_symlink(), f"Unexpected symlink: {name}"
    data = path.read_bytes()
    assert len(data) == expected[name]["bytes"], f"Size mismatch: {name}"
    assert hashlib.sha256(data).hexdigest() == expected[name]["sha256"], name
print(f"Verified {len(expected)} files. Run before creating a venv or editing source.")
