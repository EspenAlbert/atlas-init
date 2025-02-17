from pathlib import Path

import typer

SPLIT_STR = "mongodbatlas: "


def remove_prefix(line: str) -> str:
    """
    >>> remove_prefix(
    ...     "2025-02-14T15:47:14.157Z [DEBUG] provider.terraform-provider-mongodbatlas: {"
    ... )
    '{'
    >>> remove_prefix(
    ...     '2025-02-14T15:47:14.158Z [DEBUG] provider.terraform-provider-mongodbatlas:  "biConnector": {'
    ... )
    ' "biConnector": {'
    """
    if SPLIT_STR not in line:
        return line
    return line.split(SPLIT_STR, 1)[1]


def log_clean(log_path: str = typer.Argument(..., help="Path to the log file")):
    log_path_parsed = Path(log_path)
    assert log_path_parsed.exists(), f"file not found: {log_path}"
    new_lines = [remove_prefix(line) for line in log_path_parsed.read_text().splitlines()]
    log_path_parsed.write_text("\n".join(new_lines))
