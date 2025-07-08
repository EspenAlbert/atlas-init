from __future__ import annotations
import logging
from concurrent.futures import Future
from contextlib import suppress
from datetime import datetime
from typing import ClassVar
from ask_shell import ShellRun, confirm, kill, run, run_and_wait
from ask_shell.models import ShellRunEventT, ShellRunStdOutput
from zero_3rdparty import str_utils
from zero_3rdparty.file_utils import copy, ensure_parents_write_text
from atlas_init.settings.env_vars import AtlasInitSettings
from pathlib import Path
from model_lib import Event

logger = logging.getLogger(__name__)


class MonthlyReportPaths(Event):
    summary_path: Path
    error_only_path: Path
    details_dir: Path
    summary_name: str

    ERROR_ONLY_SUFFIX: ClassVar[str] = "_error-only.md"

    @classmethod
    def from_settings(cls, settings: AtlasInitSettings, summary_name: str) -> MonthlyReportPaths:
        return cls(
            summary_path=settings.github_ci_summary_dir / str_utils.ensure_suffix(summary_name, ".md"),
            error_only_path=settings.github_ci_summary_dir
            / str_utils.ensure_suffix(summary_name, MonthlyReportPaths.ERROR_ONLY_SUFFIX),
            details_dir=settings.github_ci_summary_details_path(summary_name, "dummy").parent,
            summary_name=summary_name,
        )


CI_TESTS_DIR_NAME = "ci-tests"
MKDOCS_SERVE_TIMEOUT = 120
MKDOCS_SERVE_URL = "http://127.0.0.1:8000"


def export_ci_tests_markdown_to_html(settings: AtlasInitSettings, report_paths: MonthlyReportPaths) -> None:
    html_out = settings.atlas_init_static_html_path
    if not html_out or not html_out.exists():
        return
    ci_tests_dir = html_out / CI_TESTS_DIR_NAME
    docs_out_dir = ci_tests_dir / "docs"
    summary_path = report_paths.summary_path
    ensure_parents_write_text(
        docs_out_dir / summary_path.name,
        summary_path.read_text(),
    )
    error_only_path = report_paths.error_only_path
    ensure_parents_write_text(
        docs_out_dir / error_only_path.name,
        error_only_path.read_text(),
    )
    details_dir = report_paths.details_dir
    copy(details_dir, docs_out_dir / details_dir.name, clean_dest=True)
    index_md_content = create_index_md(docs_out_dir)
    ensure_parents_write_text(docs_out_dir / "index.md", index_md_content)
    server_url, run_event = start_mkdocs_serve(ci_tests_dir)
    try:
        if confirm(f"do you want to open the html docs? {server_url}", default=False):
            run_and_wait(f'open -a "Google Chrome" {server_url}')
        if confirm("Finished testing html docs?", default=False):
            pass
    except BaseException as e:
        raise e
    finally:
        kill(run_event, reason="Done with html docs check")
    if confirm("Are docs ok to build and push?", default=False):
        build_and_push(ci_tests_dir, report_paths.summary_name)


def create_index_md(docs_out_dir: Path) -> str:
    """
    tree -L 1 docs
    docs
    ├── 2025-06-26_details
    ├── 2025-06-26_.md
    ├── 2025-06-26.md
    ├── 2025-06-26_error-only.md
    ├── index.md
    ├── javascript
    └── stylesheets
    """
    md_files = {f.name: f for f in docs_out_dir.glob("*.md") if f.name != "index.md"}
    parsed_dates = []
    for md_file in md_files.values():
        with suppress(ValueError):
            parsed_dates.append(datetime.strptime(md_file.stem, "%Y-%m-%d"))
    parsed_dates.sort(reverse=True)

    def date_row(date: datetime) -> str:
        summary_filename = f"{date.strftime('%Y-%m-%d')}.md"
        error_only_filename = f"{date.strftime('%Y-%m-%d')}{MonthlyReportPaths.ERROR_ONLY_SUFFIX}"
        if error_only_filename in md_files:
            return f"- [{date.strftime('%Y-%m-%d')}](./{summary_filename}) [{date.strftime('%Y-%m-%d')} Error Only](./{error_only_filename})"
        return f"- [{date.strftime('%Y-%m-%d')}]({summary_filename})"

    md_content = [
        "# Welcome to CI Tests",
        "",
        *[date_row(dt) for dt in parsed_dates],
        "",
    ]
    return "\n".join(md_content)


def start_mkdocs_serve(ci_tests_dir: Path) -> tuple[str, ShellRun]:
    future = Future()

    def on_message(event: ShellRunEventT) -> bool:
        match event:
            case ShellRunStdOutput(_, content) if f"Serving on {MKDOCS_SERVE_URL}" in content:
                logger.info(f"Docs server ready @ {MKDOCS_SERVE_URL}")
                future.set_result(None)
                return True
        return False

    run_event = run(" uv run mkdocs serve", cwd=ci_tests_dir, message_callbacks=[on_message])
    future.result(timeout=MKDOCS_SERVE_TIMEOUT)
    return MKDOCS_SERVE_URL, run_event


def build_and_push(ci_tests_dir: Path, summary_name: str) -> None:
    run_and_wait("uv run mkdocs build", cwd=ci_tests_dir, print_prefix="build")
    run_and_wait("git add .", cwd=ci_tests_dir, print_prefix="add")
    run_and_wait(f"git commit -m 'update ci tests {summary_name}'", cwd=ci_tests_dir, print_prefix="commit")
    run_and_wait("git push", cwd=ci_tests_dir, print_prefix="push")
