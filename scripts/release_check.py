"""Run the complete local release gate and a clean-wheel acceptance test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", ".pytest-tmp", "release", "dist", "build"}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".txt", ".cff", ".svg"}
SECRET_PATTERNS = {
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    ok: bool
    command: tuple[str, ...]
    output: str


def release_check(*, skip_package: bool) -> dict[str, Any]:
    steps: list[Step] = []
    version_errors = _version_errors()
    steps.append(Step("version-sync", not version_errors, (), "\n".join(version_errors)))
    secret_errors = _secret_errors()
    steps.append(Step("secret-scan", not secret_errors, (), "\n".join(secret_errors)))
    if version_errors or secret_errors:
        return _result(steps)

    commands = (
        ("ruff-format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("ruff-check", [sys.executable, "-m", "ruff", "check", "."]),
        ("mypy", [sys.executable, "-m", "mypy"]),
        ("pytest", [sys.executable, "-m", "pytest"]),
    )
    for name, command in commands:
        step = _run(name, command)
        steps.append(step)
        if not step.ok:
            return _result(steps)

    staging = Path(tempfile.mkdtemp(prefix=".pricewitness-gate-", dir=ROOT))
    try:
        demo = staging / "source-demo"
        step = _run(
            "source-demo", [sys.executable, "-m", "pricewitness", "demo", "--output", str(demo)]
        )
        steps.append(step)
        if not step.ok:
            return _result(steps)
        verify_command = [
            sys.executable,
            "-m",
            "pricewitness",
            "verify",
            str(demo / "pricewitness.db"),
            *[str(path) for path in sorted((demo / "receipts").glob("*.txt"))],
        ]
        step = _run("source-demo-verify", verify_command)
        steps.append(step)
        if not step.ok:
            return _result(steps)
        analysis = json.loads((demo / "analysis.json").read_text(encoding="utf-8"))
        summary_ok = (
            analysis["summary"]["receipt_count"] == 3
            and analysis["summary"]["mapped_count"] == 15
            and analysis["summary"]["review_count"] == 1
            and analysis["summary"]["alert_count"] >= 2
        )
        steps.append(
            Step("demo-contract", summary_ok, (), json.dumps(analysis["summary"], sort_keys=True))
        )
        if not summary_ok or skip_package:
            return _result(steps)

        step = _run(
            "package",
            [
                sys.executable,
                str(ROOT / "scripts" / "package_release.py"),
                "--output",
                str(ROOT / "release"),
            ],
        )
        steps.append(step)
        if not step.ok:
            return _result(steps)
        step = _run(
            "release-verify",
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_release.py"),
                "--directory",
                str(ROOT / "release"),
            ],
        )
        steps.append(step)
        if not step.ok:
            return _result(steps)

        distributions = sorted(
            [
                *list((ROOT / "release").glob("*.whl")),
                *list((ROOT / "release").glob("*.tar.gz")),
            ]
        )
        if len(distributions) != 2:
            steps.append(
                Step("distribution-discovery", False, (), "expected one wheel and one sdist")
            )
            return _result(steps)
        step = _run(
            "twine-check",
            [sys.executable, "-m", "twine", "check", *[str(path) for path in distributions]],
        )
        steps.append(step)
        if not step.ok:
            return _result(steps)

        reproduction = staging / "reproduction"
        step = _run(
            "package-reproduction",
            [
                sys.executable,
                str(ROOT / "scripts" / "package_release.py"),
                "--output",
                str(reproduction),
            ],
        )
        steps.append(step)
        if not step.ok:
            return _result(steps)
        reproduction_errors = _release_comparison_errors(ROOT / "release", reproduction)
        steps.append(
            Step(
                "reproducible-assets",
                not reproduction_errors,
                (),
                "\n".join(reproduction_errors),
            )
        )
        if reproduction_errors:
            return _result(steps)

        wheels = sorted((ROOT / "release").glob("pricewitness-*.whl"))
        if len(wheels) != 1:
            steps.append(Step("wheel-discovery", False, (), "expected exactly one wheel"))
            return _result(steps)
        environment = staging / "clean-venv"
        step = _run("clean-venv", [sys.executable, "-m", "venv", str(environment)])
        steps.append(step)
        if not step.ok:
            return _result(steps)
        clean_python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        step = _run(
            "wheel-install",
            [str(clean_python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        )
        steps.append(step)
        if not step.ok:
            return _result(steps)
        wheel_demo = staging / "wheel-demo"
        step = _run(
            "wheel-demo",
            [str(clean_python), "-m", "pricewitness", "demo", "--output", str(wheel_demo)],
        )
        steps.append(step)
        if not step.ok:
            return _result(steps)
        step = _run(
            "wheel-demo-verify",
            [
                str(clean_python),
                "-m",
                "pricewitness",
                "verify",
                str(wheel_demo / "pricewitness.db"),
                *[str(path) for path in sorted((wheel_demo / "receipts").glob("*.txt"))],
            ],
        )
        steps.append(step)
        return _result(steps)
    finally:
        _safe_remove_staging(staging)


def _run(name: str, command: list[str]) -> Step:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return Step(name, completed.returncode == 0, tuple(command), completed.stdout)


def _release_comparison_errors(first: Path, second: Path) -> list[str]:
    first_files = {path.name: path for path in first.iterdir() if path.is_file()}
    second_files = {path.name: path for path in second.iterdir() if path.is_file()}
    errors: list[str] = []
    if first_files.keys() != second_files.keys():
        errors.append(
            f"release file sets differ: first={sorted(first_files)} second={sorted(second_files)}"
        )
        return errors
    for name in sorted(first_files):
        first_hash = _sha256(first_files[name])
        second_hash = _sha256(second_files[name])
        if first_hash != second_hash:
            errors.append(f"{name}: {first_hash} != {second_hash}")
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_errors() -> list[str]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    version = project["version"]
    if not isinstance(version, str):
        return ["project version is not a string"]
    errors: list[str] = []
    version_source = (ROOT / "src" / "pricewitness" / "version.py").read_text(encoding="utf-8")
    if f'__version__ = "{version}"' not in version_source:
        errors.append("src version does not match pyproject.toml")
    if f"## [{version}]" not in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"):
        errors.append("CHANGELOG does not contain the project version")
    if not (ROOT / "release-notes" / f"v{version}.md").is_file():
        errors.append("release notes are missing")
    return errors


def _secret_errors() -> list[str]:
    errors: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(
            part in SKIP_DIRS or part.startswith(".demo") for part in path.relative_to(ROOT).parts
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{path.relative_to(ROOT)}: possible {label}")
    return errors


def _result(steps: list[Step]) -> dict[str, Any]:
    return {
        "ok": all(step.ok for step in steps),
        "steps": [
            {
                "name": step.name,
                "ok": step.ok,
                "command": list(step.command),
                "output": step.output[-4000:],
            }
            for step in steps
        ],
    }


def _safe_remove_staging(path: Path) -> None:
    resolved = path.resolve()
    if resolved.parent != ROOT.resolve() or not resolved.name.startswith(".pricewitness-gate-"):
        raise RuntimeError(f"refusing to remove unexpected gate path: {resolved}")
    shutil.rmtree(resolved)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-package", action="store_true")
    parser.add_argument("--json", action="store_true", help="reserved; output is always JSON")
    arguments = parser.parse_args(argv)
    result = release_check(skip_package=arguments.skip_package)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
