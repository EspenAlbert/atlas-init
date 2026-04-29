from __future__ import annotations

from pathlib import Path

from atlas_init.html_out.md_export import MonthlyReportPaths, create_index_md, remove_exported_report_from_docs
from zero_3rdparty.file_utils import ensure_parents_write_text


def test_remove_exported_report_from_docs(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    snap = "2025-01-15"
    other = "2024-12-01"
    ensure_parents_write_text(docs / f"{snap}.md", "s")
    ensure_parents_write_text(docs / f"{snap}{MonthlyReportPaths.ERROR_ONLY_SUFFIX}", "e")
    ensure_parents_write_text(docs / f"{snap}{MonthlyReportPaths.DAILY_SUFFIX}", "d")
    details = docs / f"{snap}_details"
    details.mkdir()
    ensure_parents_write_text(details / "x.md", "x")
    ensure_parents_write_text(docs / f"{other}.md", "o")
    ensure_parents_write_text(docs / "index.md", "stale")

    report_paths = MonthlyReportPaths(
        summary_path=Path("any") / f"{snap}.md",
        error_only_path=Path("any") / f"{snap}{MonthlyReportPaths.ERROR_ONLY_SUFFIX}",
        details_dir=(Path("any") / f"{snap}_details" / "z.md").parent,
        summary_name=snap,
        daily_path=Path("any") / f"{snap}{MonthlyReportPaths.DAILY_SUFFIX}",
    )
    remove_exported_report_from_docs(docs, report_paths)

    assert not (docs / f"{snap}.md").exists()
    assert not (docs / f"{snap}{MonthlyReportPaths.ERROR_ONLY_SUFFIX}").exists()
    assert not (docs / f"{snap}{MonthlyReportPaths.DAILY_SUFFIX}").exists()
    assert not (docs / f"{snap}_details").exists()
    assert (docs / f"{other}.md").read_text() == "o"
    assert (docs / "index.md").read_text() == create_index_md(docs)
