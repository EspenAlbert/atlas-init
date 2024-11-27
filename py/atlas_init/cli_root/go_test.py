import logging

import typer

from atlas_init.cli_helper.go import GoTestMode, run_go_tests
from atlas_init.repos.path import Repo, current_repo, current_repo_path
from atlas_init.settings.env_vars import active_suites, init_settings
from atlas_init.typer_app import app_command

logger = logging.getLogger(__name__)


@app_command()
def go_test(
    mode: GoTestMode = typer.Option("package", "-m", "--mode", help="package|individual"),
    dry_run: bool = typer.Option(False, help="only log out the commands to be run"),
    timeout_minutes: int = typer.Option(300, "-t", "--timeout", help="timeout in minutes"),
    concurrent_runs: int = typer.Option(20, "-c", "--concurrent", help="number of concurrent runs"),
    re_run: bool = typer.Option(False, "-r", "--re-run", help="re-run the tests if the log already exist"),
):
    settings = init_settings()
    suites = active_suites(settings)
    sorted_suites = sorted(suite.name for suite in suites)
    logger.info(f"running go tests for {len(suites)} test-suites: {sorted_suites}")
    match repo_alias := current_repo():
        case Repo.CFN:
            raise NotImplementedError
        case Repo.TF:
            repo_path = current_repo_path()
            package_prefix = settings.config.go_package_prefix(repo_alias)
            run_go_tests(
                repo_path,
                repo_alias,
                package_prefix,
                settings,
                suites,
                mode,
                dry_run=dry_run,
                timeout_minutes=timeout_minutes,
                concurrent_runs=concurrent_runs,
                re_run=re_run,
            )
        case _:
            raise NotImplementedError
