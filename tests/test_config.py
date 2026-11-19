from pathlib import Path

import pytest
from pydantic import ValidationError

from memauthy.config import CostTier, ExperimentConfig, ModelConfig, config_hash, load_config

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_example_config_loads() -> None:
    cfg = load_config(ROOT / "configs" / "example-offline.yaml")
    assert cfg.tier is CostTier.OFFLINE
    assert cfg.name == "example-offline"


def test_hash_independent_of_key_order(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.yaml", "name: x\ntier: 0\nseed: 1\nparams: {a: 1, b: 2}\n")
    b = _write(tmp_path / "b.yaml", "params: {b: 2, a: 1}\nseed: 1\ntier: 0\nname: x\n")
    assert config_hash(load_config(a)) == config_hash(load_config(b))


def test_hash_changes_with_content() -> None:
    a = ExperimentConfig(name="x", tier=CostTier.OFFLINE, seed=1)
    b = ExperimentConfig(name="x", tier=CostTier.OFFLINE, seed=2)
    assert config_hash(a) != config_hash(b)
    assert len(config_hash(a)) == 64


def test_unknown_keys_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path / "c.yaml", "name: x\ntier: 0\nseed: 1\ntypo_field: 3\n")
    with pytest.raises(ValidationError):
        load_config(path)


def test_non_mapping_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mapping"):
        load_config(_write(tmp_path / "d.yaml", "- a\n- b\n"))


def test_key_env_must_be_a_variable_name() -> None:
    ModelConfig(name="m", provider="ollama", temperature=0.0, key_env="AGENT_API_KEY")
    with pytest.raises(ValidationError):
        ModelConfig(name="m", provider="x", temperature=0.0, key_env="sk-live-not-a-name")


def test_temperature_required() -> None:
    with pytest.raises(ValidationError):
        ModelConfig(name="m", provider="ollama")  # type: ignore[call-arg]
