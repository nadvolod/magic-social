"""Tests for README metrics dashboard syncing."""

from pathlib import Path

from src.agent import (
    README_METRICS_END,
    README_METRICS_START,
    build_readme_metrics_block,
    update_readme_metrics_section,
)


def test_build_readme_metrics_block_contains_markers():
    block = build_readme_metrics_block("# Title\n\n## Section\n")
    assert README_METRICS_START in block
    assert README_METRICS_END in block
    # Heading should be demoted one level inside README.
    assert "## Title" in block


def test_build_readme_metrics_block_does_not_demote_inside_code_fence():
    block = build_readme_metrics_block("# Title\n\n```bash\n# keep me\n```\n")
    assert "## Title" in block
    assert "# keep me" in block
    assert "## keep me" not in block


def test_update_readme_metrics_section_replaces_between_markers(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# Project",
                "",
                README_METRICS_START,
                "old",
                README_METRICS_END,
                "",
                "tail",
            ]
        ),
        encoding="utf-8",
    )
    ok = update_readme_metrics_section(str(readme), "# Metrics\n\n## Scorecard")
    assert ok is True
    updated = readme.read_text(encoding="utf-8")
    assert "## Metrics" in updated
    assert "### Scorecard" in updated
    assert "old" not in updated


def test_update_readme_metrics_section_returns_false_without_markers(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text("# No markers here\n", encoding="utf-8")
    ok = update_readme_metrics_section(str(readme), "# Metrics")
    assert ok is False
