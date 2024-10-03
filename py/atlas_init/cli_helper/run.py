import os
import subprocess
import sys
from logging import Logger
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory
from typing import IO, TypeVar

import typer

StrT = TypeVar("StrT", bound=str)


def run_command_is_ok(
    cmd: list[StrT],
    env: dict | None,
    cwd: Path | str,
    logger: Logger,
    output: IO | None = None,
) -> bool:
    env = env or {**os.environ}
    command_str = " ".join(cmd)
    logger.info(f"running: '{command_str}' from '{cwd}'")
    output = output or sys.stdout  # type: ignore
    exit_code = subprocess.call(
        cmd,
        stdin=sys.stdin,
        stderr=sys.stderr,
        stdout=output,
        cwd=cwd,
        env=env,
    )
    is_ok = exit_code == 0
    if is_ok:
        logger.info(f"success 🥳 '{command_str}'\n")  # adds extra space to separate runs
    else:
        logger.error(f"error 💥, exit code={exit_code}, '{command_str}'")
    return is_ok


def run_binary_command_is_ok(
    binary_name: str, command: str, cwd: Path, logger: Logger, env: dict | None = None
) -> bool:
    env = env or {**os.environ}

    bin_path = find_binary_on_path(binary_name, logger)
    return run_command_is_ok(
        [bin_path, *command.split()],
        env=env,
        cwd=cwd,
        logger=logger,
    )


def find_binary_on_path(binary_name: str, logger: Logger, *, allow_missing: bool = False) -> str:
    bin_path = which(binary_name)
    if bin_path:
        return bin_path
    if allow_missing:
        return ""
    logger.critical(f"please install '{binary_name}'")
    raise typer.Exit(1)


def run_command_exit_on_failure(
    cmd: list[StrT] | str,
    cwd: Path | str,
    logger: Logger,
    env: dict | None = None,
) -> None:
    if isinstance(cmd, str):
        cmd = cmd.split()  # type: ignore
    assert isinstance(cmd, list)
    if not run_command_is_ok(cmd, cwd=cwd, env=env, logger=logger):
        logger.critical("command failed, see output 👆")
        raise typer.Exit(1)


def run_command_receive_result(
    command: str, cwd: Path, logger: Logger, env: dict | None = None, *, can_fail: bool = False
) -> str:
    with TemporaryDirectory() as temp_dir:
        result_file = Path(temp_dir) / "file"
        with open(result_file, "w") as file:
            is_ok = run_command_is_ok(command.split(), env=env, cwd=cwd, logger=logger, output=file)
        output_text = result_file.read_text().strip()
    if not is_ok:
        if can_fail:
            logger.warning(f"command failed {command}, {output_text}")
            return f"FAIL: {output_text}"
        logger.critical(f"command failed {command}, {output_text}")
        raise typer.Exit(1)
    return output_text


def add_to_clipboard(clipboard_content: str, logger: Logger):
    if pb_binary := find_binary_on_path("pbcopy", logger, allow_missing=True):
        subprocess.run(pb_binary, text=True, input=clipboard_content, check=True)
    else:
        logger.warning("pbcopy not found on $PATH")
