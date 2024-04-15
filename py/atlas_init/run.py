from logging import Logger
import os
from pathlib import Path
from shutil import which
import subprocess
import sys


def run_command_is_ok(
    cmd: list[str], env: dict, cwd: Path | str, logger: Logger
) -> bool:
    command_str = " ".join(cmd)
    logger.info(f"running: {command_str}")
    exit_code = subprocess.call(
        cmd,
        stdin=sys.stdin,
        stderr=sys.stderr,
        stdout=sys.stdout,
        cwd=cwd,
        env=env,
    )
    is_ok = exit_code == 0
    if is_ok:
        logger.info(f"success 🥳 '{command_str}'\n") # adds extra space to separate runs
    else:
        logger.error(f"error 💥, exit code={exit_code}, '{command_str}'")
    return is_ok


def run_binary_command_is_ok(binary_name: str, command: str, cwd: Path, logger: Logger, env: dict | None = None) -> bool:
    env = env or {**os.environ}
    
    bin = which(binary_name)
    if not bin:
        logger.critical(f"please install '{binary_name}'")
        return False
    return run_command_is_ok(
        [bin, *command.split()],
        env=env,
        cwd=cwd,
        logger=logger,
    )
