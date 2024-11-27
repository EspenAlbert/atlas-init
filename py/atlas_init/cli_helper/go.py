import logging
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait
from enum import StrEnum
from pathlib import Path

import typer
from model_lib import Entity

from atlas_init.cli_helper.run import run_command_is_ok
from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.settings.config import TestSuite
from atlas_init.settings.env_vars import AtlasInitSettings
from atlas_init.settings.path import DEFAULT_DOWNLOADS_DIR

logger = logging.getLogger(__name__)


class GoTestMode(StrEnum):
    package = "package"
    individual = "individual"


class GoEnvVars(StrEnum):
    manual = "manual"
    vscode = "vscode"


class GoTestResult(Entity):
    passes: dict[str, GoTestRun]


def run_go_tests(
    repo_path: Path,
    repo_alias: str,
    package_prefix: str,
    settings: AtlasInitSettings,
    groups: list[TestSuite],
    mode: GoTestMode = GoTestMode.package,
    *,
    dry_run: bool = False,
    timeout_minutes: int = 300,
    concurrent_runs: int = 20,
    re_run: bool = False,
    env_vars: GoEnvVars = GoEnvVars.vscode,
):
    test_env = _resolve_env_vars(settings, env_vars)
    if ci_value := test_env.pop("CI", None):
        logger.warning(f"pooped CI={ci_value}")
    commands_to_run: dict[str, list[str]] = {}
    for group in groups:
        package_paths = group.repo_go_packages.get(repo_alias, [])
        packages = ",".join(f"{package_prefix}/{pkg}" for pkg in package_paths)
        if not packages:
            logger.warning(f"no go packages for suite: {group}")
            continue
        if mode == GoTestMode.individual:
            test_names = find_individual_tests(repo_path, package_paths)
            for name in test_names:
                command = f"go test {packages} -v -run ^{name}$ -timeout {timeout_minutes}m"
                commands_to_run[name] = command.split(" ")
        elif mode == GoTestMode.package:
            command = f"go test {packages} -v -run ^TestAcc* -timeout {timeout_minutes}m".split(" ")
            if not group.sequential_tests:
                command.extend(["-parallel", f"{concurrent_runs}"])
            commands_to_run[group.name] = command
        else:
            raise NotImplementedError(f"mode={mode}")
    commands_str = "\n".join(f"'{name}': '{" ".join(command)}'" for name, command in sorted(commands_to_run.items()))
    logger.info(f"will run the following commands:\n{commands_str}")
    if dry_run:
        return
    _run_tests(
        repo_path,
        commands_to_run,
        test_env,
        test_timeout_s=timeout_minutes * 60,
        max_workers=concurrent_runs,
        re_run=re_run,
    )


def _resolve_env_vars(settings: AtlasInitSettings, env_vars: GoEnvVars) -> dict[str, str]:
    if env_vars == GoEnvVars.manual:
        extra_vars = settings.load_profile_manual_env_vars(skip_os_update=True)
    elif env_vars == GoEnvVars.vscode:
        extra_vars = settings.load_env_vars(settings.env_vars_vs_code)
    else:
        raise NotImplementedError(f"don't know how to load env_vars={env_vars}")
    test_env = os.environ | extra_vars
    logger.info(f"go test env-vars-extra: {sorted(extra_vars)}")
    return test_env


def find_individual_tests(repo_path: Path, package_paths: list[str]) -> list[str]:
    tests = []
    for package_path in package_paths:
        package_dir = repo_path / package_path
        for go_file in package_dir.glob("*.go"):
            with go_file.open() as f:
                for line in f:
                    if line.startswith("func TestAcc"):
                        test_name = line.split("(")[0].strip().removeprefix("func ")
                        tests.append(test_name)
    return tests


def _run_tests(
    repo_path: Path,
    commands_to_run: dict[str, list[str]],
    test_env: dict[str, str],
    test_timeout_s: int = 301 * 60,
    max_workers: int = 2,
    *,
    re_run: bool = False,
):
    futures = {}
    downloads_dir = DEFAULT_DOWNLOADS_DIR
    with ThreadPoolExecutor(max_workers=min(max_workers, len(commands_to_run))) as pool:
        for name, command in sorted(commands_to_run.items()):
            log_path = downloads_dir / f"{name}.log"
            if log_path.exists() and log_path.read_text() and not re_run:
                logger.info(f"skipping {name} because log exists")
                continue
            command_env = {**test_env, "TF_LOG_PATH": str(log_path), "TF_LOG": "DEBUG"}
            future = pool.submit(run_command_is_ok, command, command_env, cwd=repo_path, logger=logger)
            futures[future] = name
        done, not_done = wait(futures.keys(), timeout=test_timeout_s)
        for f in not_done:
            logger.warning(f"timeout to run command name = {futures[f]}")
    result_names: dict[bool, list[str]] = defaultdict(list)
    for f in done:
        name: str = futures[f]
        try:
            ok = f.result()
            result_names[ok].append(name)
        except Exception:
            logger.exception(f"failed to run command for {name}")
            result_names[False].append(name)
            continue
    if failure_names := result_names[False]:
        move_failed_logs_to_error_dir(set(failure_names))
        logger.error(f"failed to run tests: {failure_names}")
        typer.Exit(1)


def move_failed_logs_to_error_dir(failures: set[str]):
    error_dir = DEFAULT_DOWNLOADS_DIR / "failures"
    for log in DEFAULT_DOWNLOADS_DIR.glob("*.log"):
        if log.stem in failures:
            text = log.read_text()
            assert "\n" in text
            first_line = text.split("\n", maxsplit=1)[0]
            ts = first_line.split(" ")[0]
            log.rename(error_dir / f"{ts}.{log.name}")
