"""Refresh the frozen PathLab engine; perform no network or package installation.

Run from any directory with ``python tools/vendor_core.py``.  Only the application
exception import is adapted.  Hashes refer to actual source bytes, including
uncommitted work, rather than claiming the checkout's HEAD contains those bytes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


def vendor():
    extension_root = Path(__file__).resolve().parents[1]
    repository_root = extension_root.parents[1]
    source_path = "workers/python/conditional_process.py"
    source = (repository_root / source_path).read_bytes()
    old = b"from engine import LabError"
    new = b"from .errors import LabError"
    if source.count(old) != 1:
        raise RuntimeError("Expected exactly one application exception import")
    vendored = source.replace(old, new)
    target = extension_root / "pathlab_spss" / "core.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(vendored)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--", source_path],
        cwd=repository_root, text=True,
    ).strip()
    provenance = {
        "format_version": 1,
        "source_repository": "https://github.com/issacjohny/Stratistics",
        "source_path": source_path,
        "checkout_head": head,
        "source_has_uncommitted_changes": bool(dirty),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "vendored_path": "pathlab_spss/core.py",
        "vendored_sha256": hashlib.sha256(vendored).hexdigest(),
        "adaptation": {
            "occurrences": 1,
            "replace": old.decode(),
            "with": new.decode(),
            "description": "Isolate the exception contract; statistical code is unchanged.",
        },
        "note": "Source hash identifies the actual working-tree snapshot; checkout HEAD alone does not.",
    }
    (extension_root / "source-provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Vendored engine sha256: {provenance['vendored_sha256']}")


if __name__ == "__main__":
    vendor()
