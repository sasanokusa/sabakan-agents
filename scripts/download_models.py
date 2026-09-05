#!/usr/bin/env python3
"""Download and verify the GGUF files listed in models/manifest.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "models" / "manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(item: dict[str, str], *, force: bool) -> None:
    relative_path = Path(item["path"])
    destination = ROOT / relative_path
    if destination.is_file() and not force:
        actual = sha256(destination)
        if actual == item["sha256"]:
            print(f"{item['label']}: already verified")
            return
        raise RuntimeError(f"existing file has the wrong SHA-256: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{item['repository']}/resolve/main/{item['file']}?download=true"
    partial = destination.with_name(destination.name + ".part")
    print(f"{item['label']}: downloading {url}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "sabakan-agent-model-fetch/0.1"})
    digest = hashlib.sha256()
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        pass
    else:
        context.load_verify_locations(certifi.where())
    with urllib.request.urlopen(request, timeout=60, context=context) as response, partial.open("wb") as stream:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            stream.write(chunk)
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != item["sha256"]:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {item['label']}: expected {item['sha256']}, got {actual}")
    os.replace(partial, destination)
    print(f"{item['label']}: verified {destination}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="redownload files even when an existing hash matches")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for item in manifest["models"]:
        download(item, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
