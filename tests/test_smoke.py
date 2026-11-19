import importlib

from typer.testing import CliRunner

import memauthy
from memauthy.cli import app

SUBPACKAGES = ["memory_io", "rules", "provenance", "policy", "defenses", "eval"]


def test_version_is_set() -> None:
    assert isinstance(memauthy.__version__, str)
    assert memauthy.__version__


def test_subpackages_importable() -> None:
    for name in SUBPACKAGES:
        importlib.import_module(f"memauthy.{name}")


def test_cli_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"memauthy {memauthy.__version__}"
