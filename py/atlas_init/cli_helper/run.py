import os
import subprocess  # nosec
import sys
from logging import Logger
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory
from typing import IO

import typer
from zero_3rdparty.id_creator import simple_id

LOG_CMD_PREFIX = "running: '"


def run_command_is_ok(
    cmd: str,
    env: dict | None,
    cwd: Path | str,
    logger: Logger,
    output: IO | None = None,
    *,
    dry_run: bool = False,
) -> bool:
    env = env or {**os.environ}
    logger.info(f"{LOG_CMD_PREFIX}{cmd}' from '{cwd}'")
    if dry_run:
        return True
    output = output or sys.stdout  # type: ignore
    exit_code = subprocess.call(
        cmd,
        stdin=sys.stdin,
        stderr=sys.stderr,
        stdout=output,
        cwd=cwd,
        env=env,
        shell=True,  # noqa: S602 # We control the calls to this function and don't suspect any shell injection #nosec
    )
    is_ok = exit_code == 0
    if is_ok:
        logger.info(f"success 🥳 '{cmd}'\n")  # adds extra space to separate runs
    else:
        logger.error(f"error 💥, exit code={exit_code}, '{cmd}'")
    return is_ok


def run_binary_command_is_ok(
    binary_name: str, command: str, cwd: Path, logger: Logger, env: dict | None = None, *, dry_run: bool = False
) -> bool:
    env = env or {**os.environ}
    bin_path = find_binary_on_path(binary_name, logger, allow_missing=dry_run) or binary_name
    return run_command_is_ok(
        f"{bin_path} {command}",
        env=env,
        cwd=cwd,
        logger=logger,
        dry_run=dry_run,
    )


def find_binary_on_path(binary_name: str, logger: Logger, *, allow_missing: bool = False) -> str:
    if bin_path := which(binary_name):
        return bin_path
    if allow_missing:
        logger.warning(f"binary '{binary_name}' not found on $PATH")
        return ""
    logger.critical(f"please install '{binary_name}'")
    raise typer.Exit(1)


def run_command_exit_on_failure(
    cmd: str, cwd: Path | str, logger: Logger, env: dict | None = None, *, dry_run: bool = False
) -> None:
    if not run_command_is_ok(cmd, cwd=cwd, env=env, logger=logger, dry_run=dry_run):
        logger.critical("command failed, see output 👆")
        raise typer.Exit(1)


def run_command_receive_result(
    command: str, cwd: Path, logger: Logger, env: dict | None = None, *, can_fail: bool = False
) -> str:
    with TemporaryDirectory() as temp_dir:
        result_file = Path(temp_dir) / "file"
        with open(result_file, "w") as file:
            is_ok = run_command_is_ok(command, env=env, cwd=cwd, logger=logger, output=file)
        output_text = result_file.read_text().strip()
    if not is_ok:
        if can_fail:
            logger.warning(f"command failed {command}, {output_text}")
            return f"FAIL: {output_text}"
        logger.critical(f"command failed {command}, {output_text}")
        raise typer.Exit(1)
    return output_text


def run_command_is_ok_output(command: str, cwd: Path, logger: Logger, env: dict | None = None) -> tuple[bool, str]:
    with TemporaryDirectory() as temp_dir:
        result_file = Path(temp_dir) / f"{simple_id()}.txt"
        with open(result_file, "w") as file:
            is_ok = run_command_is_ok(command, env=env, cwd=cwd, logger=logger, output=file)
        output_text = result_file.read_text().strip()
    return is_ok, output_text


def add_to_clipboard(clipboard_content: str, logger: Logger):
    if pb_binary := find_binary_on_path("pbcopy", logger, allow_missing=True):
        subprocess.run(pb_binary, text=True, input=clipboard_content, check=True)  # nosec
    else:
        logger.warning("pbcopy not found on $PATH")
