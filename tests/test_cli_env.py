"""Tests for Alpaca CLI subprocess environment handling."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import synthetix_alpha.config as config

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.modules.setdefault("synthetix_alpha", type(sys)("synthetix_alpha"))
sys.modules["synthetix_alpha.config"] = config

_spec = importlib.util.spec_from_file_location(
    "synthetix_alpha.live.cli",
    _REPO_ROOT / "synthetix_alpha" / "live" / "cli.py",
)
cli = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(cli)


def test_env_preserves_inherited_path_for_subprocess(monkeypatch, tmp_path) -> None:
    bin_dir = tmp_path / "go" / "bin"
    bin_dir.mkdir(parents=True)
    fake_alpaca = bin_dir / "alpaca"
    fake_alpaca.write_text('#!/bin/sh\necho "{\\"equity\\":\\"1000\\"}"\n')
    fake_alpaca.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    monkeypatch.setenv("HOME", str(tmp_path))

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)

        class R:
            stdout = '{"equity":"1000"}'
            stderr = ""

        return R()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli.config, "ALPACA_BIN", "alpaca")
    cli.account()

    env = captured["env"]
    assert env is not None
    assert str(bin_dir) in env["PATH"]
    assert env["PATH"] == f"{bin_dir}:/usr/bin:/bin"
    assert env["ALPACA_API_KEY"] == "k"
    assert env["ALPACA_SECRET_KEY"] == "s"
    assert env["HOME"] == str(tmp_path)
    assert "ALPACA_LIVE_TRADE" not in env


def test_env_is_not_credentials_only(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/custom/go/bin:/usr/bin")
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    env = cli._env()
    assert env["PATH"] == "/custom/go/bin:/usr/bin"
    assert len(env) > 2


def test_credentials_only_env_would_drop_path(monkeypatch, tmp_path) -> None:
    """Regression guard: bare credential dicts cannot find alpaca on PATH."""
    bin_dir = tmp_path / "go" / "bin"
    bin_dir.mkdir(parents=True)
    fake_alpaca = bin_dir / "alpaca"
    fake_alpaca.write_text('#!/bin/sh\necho ok\n')
    fake_alpaca.chmod(0o755)

    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    with pytest.raises(FileNotFoundError):
        cli.subprocess.run(
            ["alpaca"],
            capture_output=True,
            text=True,
            env={"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s"},
        )

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)

        class R:
            stdout = '{"equity":"1000"}'
            stderr = ""

        return R()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli.config, "ALPACA_BIN", "alpaca")
    cli.account()
    assert str(bin_dir) in captured["env"]["PATH"]
