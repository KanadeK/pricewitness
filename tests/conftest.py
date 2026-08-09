from __future__ import annotations

from pathlib import Path

import pytest

from pricewitness.demo import create_demo


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    destination = tmp_path / "demo"
    create_demo(destination)
    return destination
