import logging

import typer

from atlas_init.cli_helper.go import GoEnvVars, GoTestCaptureMode, GoTestMode, GoTestResult, run_go_tests
from atlas_init.cli_tf.mock_tf_log import MockTFLog, mock_tf_log, resolve_admin_api_path
from atlas_init.repos.path import Repo, current_repo, current_repo_path
from atlas_init.settings.env_vars import active_suites, init_settings
from atlas_init.typer_app import app_command

logger = logging.getLogger(__name__)


@app_command()
def go_test(
    mode: str = typer.Option("package", "-m", "--mode", help="package|individual or a prefix"),
    dry_run: bool = typer.Option(False, help="only log out the commands to be run"),
    timeout_minutes: int = typer.Option(300, "-t", "--timeout", help="timeout in minutes"),
    concurrent_runs: int = typer.Option(20, "-c", "--concurrent", help="number of concurrent runs"),
    re_run: bool = typer.Option(False, "-r", "--re-run", help="re-run the tests if the log already exist"),
    export_mock_tf_log: bool = typer.Option(False, "-e", "--export", help="export the mock-tf-log"),
    export_mock_tf_log_verbose: bool = typer.Option(
        False, "--export-verbose", help="log roundtrips when exporting the mock-tf-log"
    ),
    env_method: GoEnvVars = typer.Option(GoEnvVars.manual, "--env"),
    names: list[str] = typer.Option(
        ...,
        "-n",
        "--names",
        default_factory=list,
        help="run only the tests with these names",
    ),
    capture_mode: GoTestCaptureMode = typer.Option(GoTestCaptureMode.capture, "--capture"),
    use_old_schema: bool = typer.Option(False, "--old-schema", help="use the old schema for the tests"),
):
    if export_mock_tf_log and mode != GoTestMode.individual:
        err_msg = "exporting mock-tf-log is only supported for individual tests"
        raise ValueError(err_msg)
    settings = init_settings()
    suites = active_suites(settings)
    sorted_suites = sorted(suite.name for suite in suites)
    logger.info(f"running go tests for {len(suites)} test-suites: {sorted_suites}")
    results: GoTestResult | None = None
    match current_repo():
        case Repo.CFN:
            raise NotImplementedError
        case Repo.TF:
            repo_path = current_repo_path()
            results = run_go_tests(
                repo_path,
                settings,
                suites,
                mode,
                dry_run=dry_run,
                timeout_minutes=timeout_minutes,
                concurrent_runs=concurrent_runs,
                re_run=re_run,
                env_vars=env_method,
                names=set(names),
                capture_mode=capture_mode,
                use_old_schema=use_old_schema,
            )
        case _:
            raise NotImplementedError
    if results is None:
        error_msg = "no results found"
        raise ValueError(error_msg)
    if export_mock_tf_log:
        _export_mock_tf_logs(results, export_mock_tf_log_verbose)
    # use the test_results: dict[str, list[GoTestRun]]
    # TODO: create_detailed_summary()


def _export_mock_tf_logs(results: GoTestResult, verbose: bool):
    package_paths = results.test_name_package_path
    admin_api_path = resolve_admin_api_path("", sdk_branch="main", admin_api_path="")
    for test_name, runs in results.runs.items():
        package_path = package_paths.get(test_name)
        if package_path is None:
            logger.warning(f"no package path found for test_name={test_name}")
            continue
        assert len(runs) == 1, f"expected only 1 run for test_name={test_name}, got {len(runs)}"
        run = runs[0]
        tpf_package_path = package_path.with_name(f"{package_path.name}tpf") / "testdata"
        default_package_path = package_path / "testdata"
        if not tpf_package_path.exists():
            logger.warning(
                f"tpf_package_path={tpf_package_path} doesn't exist, adding mocked data to {default_package_path}"
            )
            tpf_package_path = default_package_path
        tf_log_path = run.log_path
        assert tf_log_path, f"test didn't set tf_log_path: {test_name}"
        if test_name in results.failure_names:
            logger.warning(f"test_name={test_name} failed, not exporting mock-tf-log")
            continue
        req = MockTFLog(
            log_path=tf_log_path,
            output_dir=tpf_package_path,
            admin_api_path=admin_api_path,
            package_name=package_path.name,
            log_diff_roundtrips=verbose,
        )
        mocked_yaml = mock_tf_log(req)
        logger.info(f"mocked TestConfig saved to {mocked_yaml}")
