"""Build deterministic PriceWitness release assets."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import uuid
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATE_EPOCH = "1767225600"  # 2026-01-01T00:00:00Z
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def package_release(output: Path) -> dict[str, Any]:
    version = _project_version()
    staging = Path(tempfile.mkdtemp(prefix=".pricewitness-package-", dir=ROOT))
    try:
        built = staging / "built"
        built.mkdir()
        environment = os.environ.copy()
        environment["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(built),
                str(ROOT),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        wheels = sorted(built.glob("*.whl"))
        sdists = sorted(built.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError("build must produce exactly one wheel and one source distribution")
        _canonicalize_sdist(sdists[0])

        demo_zip = staging / f"pricewitness-demo-v{version}.zip"
        _create_demo_zip(demo_zip, version)
        sbom = staging / f"pricewitness-sbom-v{version}.cdx.json"
        _create_sbom(sbom, version, [wheels[0], sdists[0], demo_zip])

        assets = [wheels[0], sdists[0], demo_zip, sbom]
        expected_names = {asset.name for asset in assets} | {"SHA256SUMS"}
        output.mkdir(parents=True, exist_ok=True)
        unexpected = sorted(
            path.name
            for path in output.iterdir()
            if path.is_file() and path.name not in expected_names
        )
        if unexpected:
            raise RuntimeError(f"release directory contains stale assets: {', '.join(unexpected)}")
        for asset in assets:
            shutil.copyfile(asset, output / asset.name)

        checksums = {asset.name: _sha256(output / asset.name) for asset in assets}
        (output / "SHA256SUMS").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())),
            encoding="utf-8",
            newline="\n",
        )
        return {
            "ok": True,
            "version": version,
            "source_date_epoch": SOURCE_DATE_EPOCH,
            "assets": [
                {
                    "name": name,
                    "sha256": digest,
                    "bytes": (output / name).stat().st_size,
                }
                for name, digest in sorted(checksums.items())
            ],
            "checksums": "SHA256SUMS",
        }
    finally:
        _safe_remove_staging(staging)


def _project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        payload = tomllib.load(handle)
    version = payload.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError("pyproject.toml has no project version")
    return version


def _create_demo_zip(destination: Path, version: str) -> None:
    prefix = f"pricewitness-demo-v{version}"
    files = [
        ROOT / "examples" / "aliases.json",
        *sorted((ROOT / "examples" / "receipts").glob("*.txt")),
    ]
    runme = (
        b"# PriceWitness release demo\n\n"
        b"Install the release wheel, then run:\n\n"
        b"    pricewitness demo --output demo-output\n\n"
        b"Or ingest these fixtures directly with examples/aliases.json. All data is synthetic.\n"
    )
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        _write_zip_bytes(archive, f"{prefix}/RUNME.md", runme)
        for source in files:
            relative = source.relative_to(ROOT).as_posix()
            _write_zip_bytes(archive, f"{prefix}/{relative}", source.read_bytes())


def _canonicalize_sdist(path: Path) -> None:
    """Rewrite setuptools' sdist with stable tar and gzip timestamps."""
    epoch = int(SOURCE_DATE_EPOCH)
    temporary = path.with_name(f".{path.name}.canonical")
    try:
        with (
            tarfile.open(path, "r:gz") as source,
            temporary.open("wb") as raw,
            gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw,
                mtime=epoch,
            ) as compressed,
            tarfile.open(
                fileobj=compressed,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as destination,
        ):
            for member in source.getmembers():
                normalized = copy.copy(member)
                normalized.mtime = epoch
                normalized.pax_headers = {
                    key: value for key, value in member.pax_headers.items() if key != "mtime"
                }
                payload = source.extractfile(member) if member.isfile() else None
                destination.addfile(normalized, payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_zip_bytes(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _create_sbom(destination: Path, version: str, assets: list[Path]) -> None:
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'https://github.com/KanadeK/pricewitness@{version}')}",
        "version": 1,
        "metadata": {
            "timestamp": "2026-01-01T00:00:00Z",
            "component": {
                "type": "application",
                "bom-ref": f"pkg:pypi/pricewitness@{version}",
                "name": "pricewitness",
                "version": version,
                "licenses": [{"license": {"id": "MIT"}}],
                "purl": f"pkg:pypi/pricewitness@{version}",
                "externalReferences": [
                    {
                        "type": "vcs",
                        "url": "https://github.com/KanadeK/pricewitness",
                    }
                ],
            },
        },
        "components": [],
        "properties": [
            {"name": "pricewitness:runtime-dependencies", "value": "0"},
            *[
                {
                    "name": f"pricewitness:artifact:{asset.name}:sha256",
                    "value": _sha256(asset),
                }
                for asset in sorted(assets, key=lambda item: item.name)
            ],
        ],
    }
    destination.write_text(
        json.dumps(bom, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_remove_staging(path: Path) -> None:
    resolved = path.resolve()
    if resolved.parent != ROOT.resolve() or not resolved.name.startswith(".pricewitness-package-"):
        raise RuntimeError(f"refusing to remove unexpected staging path: {resolved}")
    shutil.rmtree(resolved)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    arguments = parser.parse_args(argv)
    try:
        result = package_release(arguments.output)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
