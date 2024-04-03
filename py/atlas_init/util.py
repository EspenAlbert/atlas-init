from logging import Logger
from pathlib import Path
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
    logger.info(f"exit_code of command={exit_code}: '{command_str}'")
    is_ok = exit_code == 0
    if is_ok:
        logger.info("success 🥳")
    else:
        logger.error("error 💥")
    return is_ok
