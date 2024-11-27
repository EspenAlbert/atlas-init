import logging
import os
from concurrent.futures import ThreadPoolExecutor, wait
from enum import StrEnum
from pathlib import Path

from model_lib import Entity
from pydantic import Field

from atlas_init.cli_helper.run import run_command_is_ok_output
from atlas_init.cli_tf.go_test_run import (
    GoTestContext,
    GoTestContextStep,
    GoTestRun,
    parse,
)
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
    runs: dict[str, list[GoTestRun]] = Field(default_factory=dict)
    failure_names: list[str] = Field(default_factory=list)

    test_name_package_path: dict[str, Path] = Field(default_factory=dict)

    def add_test_package_path(self, test_name: str, package_path: Path):
        if old_path := self.test_name_package_path.get(test_name):
            logger.warning(f"overwriting test_name={test_name} with package_path={old_path} --> {package_path}")
        self.test_name_package_path[test_name] = package_path

    def add_test_results(self, test_name: str, test_results: list[GoTestRun]):
        prev_test_results = self.runs.setdefault(test_name, [])
        if prev_test_results is not None:
            logger.warning(f"2nd time test results for {test_name}")
        prev_test_results.extend(test_results)


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
) -> GoTestResult:
    test_env = _resolve_env_vars(settings, env_vars)
    if ci_value := test_env.pop("CI", None):
        logger.warning(f"pooped CI={ci_value}")
    results = GoTestResult()
    commands_to_run: dict[str, str] = {}
    for group in groups:
        package_paths = group.repo_go_packages.get(repo_alias, [])
        packages = ",".join(f"{package_prefix}/{pkg}" for pkg in package_paths)
        if not packages:
            logger.warning(f"no go packages for suite: {group}")
            continue
        if mode == GoTestMode.individual:
            test_names = find_individual_tests(repo_path, package_paths)
            for name, pkg_path in test_names.items():
                results.add_test_package_path(name, pkg_path)
                commands_to_run[name] = f"go test {packages} -v -run ^{name}$ -timeout {timeout_minutes}m"

        elif mode == GoTestMode.package:
            command = f"go test {packages} -v -run ^TestAcc* -timeout {timeout_minutes}m"
            if not group.sequential_tests:
                command = f"{command} -parallel {concurrent_runs}"
            commands_to_run[group.name] = command
        else:
            raise NotImplementedError(f"mode={mode}")
    commands_str = "\n".join(f"'{name}': '{command}'" for name, command in sorted(commands_to_run.items()))
    logger.info(f"will run the following commands:\n{commands_str}")
    if dry_run:
        return results
    return _run_tests(
        results,
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
    test_env = os.environ | extra_vars | {"TF_ACC": "1", "TF_LOG": "DEBUG"}
    logger.info(f"go test env-vars-extra: {sorted(extra_vars)}")
    return test_env


def find_individual_tests(repo_path: Path, package_paths: list[str]) -> dict[str, Path]:
    tests = {}
    for package_path in package_paths:
        package_abs_path = repo_path / package_path
        for go_file in package_abs_path.glob("*.go"):
            with go_file.open() as f:
                for line in f:
                    if line.startswith("func TestAcc"):
                        test_name = line.split("(")[0].strip().removeprefix("func ")
                        tests[test_name] = package_abs_path
    return tests


def _run_tests(
    results: GoTestResult,
    repo_path: Path,
    commands_to_run: dict[str, str],
    test_env: dict[str, str],
    test_timeout_s: int = 301 * 60,
    max_workers: int = 2,
    *,
    re_run: bool = False,
) -> GoTestResult:
    futures = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(commands_to_run))) as pool:
        for name, command in sorted(commands_to_run.items()):
            log_path = _log_path(name)
            if log_path.exists() and log_path.read_text() and not re_run:
                logger.info(f"skipping {name} because log exists")
                continue
            command_env = {**test_env, "TF_LOG_PATH": str(log_path)}
            future = pool.submit(
                run_command_is_ok_output,
                command=command,
                env=command_env,
                cwd=repo_path,
                logger=logger,
            )
            futures[future] = name
        done, not_done = wait(futures.keys(), timeout=test_timeout_s)
        for f in not_done:
            logger.warning(f"timeout to run command name = {futures[f]}")
    for f in done:
        name: str = futures[f]
        try:
            ok, command_out = f.result()
        except Exception:
            logger.exception(f"failed to run command for {name}")
            results.failure_names.append(name)
            continue
        context = GoTestContext(
            name=name,
            html_url=f"file://{_log_path(name)}",
            steps=[GoTestContextStep(name="local-run")],
        )
        try:
            parsed_tests = list(parse(command_out.splitlines(), context, test_step_nr=0))
        except Exception:
            logger.exception(f"failed to parse tests for {name}")
            results.failure_names.append(name)
            continue
        if not ok:
            results.failure_names.append(name)
            logger.error(f"failed to run tests for {name}: {command_out}")
            # TODO: If the test run completed but no "errors" we should parse and store the test
            continue
        if not parsed_tests:
            logger.warning(f"no test results for {name}: {command_out}")
            continue
        results.add_test_results(name, parsed_tests)
    if failure_names := results.failure_names:
        move_failed_logs_to_error_dir(set(failure_names))
        logger.error(f"failed to run tests: {sorted(failure_names)}")
    return results


def move_failed_logs_to_error_dir(failures: set[str]):
    error_dir = DEFAULT_DOWNLOADS_DIR / "failures"
    for log in DEFAULT_DOWNLOADS_DIR.glob("*.log"):
        if log.stem in failures:
            text = log.read_text()
            assert "\n" in text
            first_line = text.split("\n", maxsplit=1)[0]
            ts = first_line.split(" ")[0]
            log.rename(error_dir / f"{ts}.{log.name}")


def _log_path(name: str) -> Path:
    return DEFAULT_DOWNLOADS_DIR / f"{name}.log"
