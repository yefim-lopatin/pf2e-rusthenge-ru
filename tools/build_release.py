#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_ID = "pf2e-rusthenge-ru"
INCLUDE = [
    "module.json",
    "README.md",
    "NOTICE.md",
    "scripts",
    "styles",
    "translations",
    "data/source-index.json",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()

    version = args.tag.removeprefix("v")
    manifest = json.loads((ROOT / "module.json").read_text(encoding="utf-8"))
    if manifest["version"] != version:
        raise SystemExit(
            f"Версия module.json ({manifest['version']}) не совпадает с тегом {args.tag}"
        )

    dist = ROOT / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir()
    shutil.copy2(ROOT / "module.json", dist / "module.json")

    with tempfile.TemporaryDirectory(prefix="rusthenge-release-") as tmp:
        package = Path(tmp) / MODULE_ID
        package.mkdir()
        for relative in INCLUDE:
            source = ROOT / relative
            target = package / relative
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

        archive = dist / f"{MODULE_ID}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            for path in sorted(package.rglob("*")):
                if path.is_file():
                    output.write(path, path.relative_to(package.parent))


if __name__ == "__main__":
    main()
