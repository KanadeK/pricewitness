"""Verify release hashes and archive contents without installing an asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def verify_release(directory: Path) -> dict[str, Any]:
    errors: list[str] = []
    checks: list[str] = []
    manifest = directory / "SHA256SUMS"
    if not manifest.is_file():
        return {"ok": False, "checks": checks, "errors": ["SHA256SUMS is missing"]}

    expected: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if match is None:
            errors.append(f"malformed checksum line: {line!r}")
            continue
        expected[match.group(2)] = match.group(1)
    if len(expected) != 4:
        errors.append(f"expected 4 release assets, found {len(expected)}")

    for name, digest in expected.items():
        asset = directory / name
        if not asset.is_file():
            errors.append(f"asset is missing: {name}")
        elif _sha256(asset) != digest:
            errors.append(f"checksum mismatch: {name}")
    if not any("checksum" in error or "missing" in error for error in errors):
        checks.append("sha256-manifest")

    wheels = sorted(directory.glob("pricewitness-*.whl"))
    sdists = sorted(directory.glob("pricewitness-*.tar.gz"))
    demos = sorted(directory.glob("pricewitness-demo-*.zip"))
    sboms = sorted(directory.glob("pricewitness-sbom-*.cdx.json"))
    if not all(len(group) == 1 for group in (wheels, sdists, demos, sboms)):
        errors.append("release must contain one wheel, sdist, demo ZIP, and SBOM")
        return {"ok": False, "checks": checks, "errors": errors}

    _verify_wheel(wheels[0], errors, checks)
    _verify_sdist(sdists[0], errors, checks)
    _verify_demo(demos[0], errors, checks)
    _verify_sbom(sboms[0], errors, checks)
    return {"ok": not errors, "checks": checks, "errors": errors}


def _verify_wheel(path: Path, errors: list[str], checks: list[str]) -> None:
    with zipfile.ZipFile(path) as archive:
        metadata_files = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            errors.append("wheel has no unique METADATA file")
            return
        metadata = archive.read(metadata_files[0]).decode("utf-8")
        required = ("Name: pricewitness", "Version: 0.1.0", "Requires-Python: >=3.11")
        if all(field in metadata for field in required):
            checks.append("wheel-metadata")
        else:
            errors.append("wheel metadata is incomplete")
        if not any(name.endswith("demo_data/aliases.json") for name in archive.namelist()):
            errors.append("wheel does not include demo alias data")


def _verify_sdist(path: Path, errors: list[str], checks: list[str]) -> None:
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        required_suffixes = ("/README.md", "/LICENSE", "/src/pricewitness/demo_data/aliases.json")
        if all(any(name.endswith(suffix) for name in names) for suffix in required_suffixes):
            checks.append("sdist-contents")
        else:
            errors.append("source distribution is missing required files")


def _verify_demo(path: Path, errors: list[str], checks: list[str]) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        receipt_count = sum(name.endswith(".txt") and "/receipts/" in name for name in names)
        if receipt_count == 3 and any(name.endswith("/aliases.json") for name in names):
            checks.append("demo-contents")
        else:
            errors.append("demo ZIP is missing aliases or synthetic receipts")


def _verify_sbom(path: Path, errors: list[str], checks: list[str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("bomFormat") == "CycloneDX"
        and payload.get("specVersion") == "1.6"
        and payload.get("metadata", {}).get("component", {}).get("name") == "pricewitness"
    ):
        checks.append("cyclonedx-sbom")
    else:
        errors.append("SBOM metadata is invalid")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "release")
    arguments = parser.parse_args(argv)
    try:
        result = verify_release(arguments.directory)
    except (OSError, json.JSONDecodeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        result = {"ok": False, "checks": [], "errors": [str(exc)]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
