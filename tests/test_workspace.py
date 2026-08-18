"""Workspace conventions: absolute paths and dated, slugged filenames.

The workspace rule is that paths are built from its root and the working
directory is never assumed. These tests pin that, because the failure mode is
silent: reports land somewhere plausible-looking and nobody notices for days.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from buffett.config import load_config
from buffett.run import main, resolve_output_dir

TODAY = date(2026, 8, 17)


def test_relative_output_dir_resolves_against_the_workspace_root(tmp_path):
    cfg = load_config()
    cfg.report.workspace_root = str(tmp_path / "Farell AI Workspace")
    cfg.report.output_dir = "investing/outputs"

    resolved = resolve_output_dir(cfg)

    assert resolved.is_absolute()
    assert resolved == (tmp_path / "Farell AI Workspace/investing/outputs").resolve()


def test_absolute_output_dir_wins_over_the_workspace_root(tmp_path):
    """An explicit absolute path is an override, not something to join onto."""
    cfg = load_config()
    cfg.report.workspace_root = str(tmp_path / "ws")
    cfg.report.output_dir = str(tmp_path / "elsewhere")

    assert resolve_output_dir(cfg) == (tmp_path / "elsewhere").resolve()


def test_output_dir_is_absolute_even_with_no_workspace_root():
    cfg = load_config()
    cfg.report.workspace_root = None
    cfg.report.output_dir = "reports"

    assert resolve_output_dir(cfg).is_absolute()


def test_workspace_root_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("FARELL_WS", str(tmp_path / "ws"))
    cfg = load_config()
    assert cfg.report.workspace_root == str(tmp_path / "ws")


def test_home_relative_workspace_root_expands(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = load_config()
    cfg.report.workspace_root = "~/Farell AI Workspace"
    cfg.report.output_dir = "investing/outputs"

    assert "~" not in str(resolve_output_dir(cfg))
    assert resolve_output_dir(cfg).is_absolute()


def test_reports_are_written_dated_and_slugged(tmp_path, monkeypatch):
    """YYYY-MM-DD-{slug}.{ext}, so several agents can share one outputs folder."""
    monkeypatch.setenv("FARELL_WS", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    exit_code = main(
        [
            "--offline",
            "--no-notify",
            "--no-agent",
            "--output-dir",
            "investing/outputs",
        ]
    )
    assert exit_code == 0

    outputs = tmp_path / "investing/outputs"
    written = sorted(p.name for p in outputs.iterdir())

    # One dated stem per format, plus the stable bookmark file.
    dated = [n for n in written if n[:10].count("-") == 2 and "latest" not in n]
    assert dated, written
    for name in dated:
        stem = Path(name).stem
        run_day, slug = stem[:10], stem[11:]
        date.fromisoformat(run_day)  # raises if the prefix is not a real date
        assert slug == "buffett", name

    assert "latest-buffett.html" in written


def test_written_json_is_valid_and_names_its_source(tmp_path, monkeypatch):
    monkeypatch.setenv("FARELL_WS", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert main(["--offline", "--no-notify", "--no-agent", "--output-dir", "out"]) == 0

    payload = json.loads(
        next((tmp_path / "out").glob("*-buffett.json")).read_text(encoding="utf-8")
    )
    assert payload["run_date"]
    assert "candidates" in payload and "memo" in payload
