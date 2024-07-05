import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from textwrap import indent

import typer
from zero_3rdparty.datetime_utils import utc_now
from zero_3rdparty.file_utils import clean_dir

from atlas_init.cli_helper.run import (
    run_binary_command_is_ok,
    run_command_exit_on_failure,
    run_command_receive_result,
)
from atlas_init.cli_tf.changelog import convert_to_changelog
from atlas_init.cli_tf.github_logs import GH_TOKEN_ENV_NAME, find_test_runs, include_test_jobs
from atlas_init.cli_tf.go_test_run_format import fail_test_summary, job_summary
from atlas_init.cli_tf.schema import (
    download_admin_api,
    dump_generator_config,
    parse_py_terraform_schema,
    update_provider_code_spec,
)
from atlas_init.cli_tf.schema_inspection import log_optional_only
from atlas_init.repos.path import Repo, current_repo_path
from atlas_init.settings.env_vars import init_settings

app = typer.Typer(no_args_is_help=True)
logger = logging.getLogger(__name__)


@app.command()
def schema():
    settings = init_settings()
    schema_out_path = settings.schema_out_path_computed
    schema_out_path.mkdir(exist_ok=True)

    schema_parsed = parse_py_terraform_schema(settings.tf_schema_config_path)
    generator_config = dump_generator_config(schema_parsed)
    generator_config_path = schema_out_path / "generator_config.yaml"
    generator_config_path.write_text(generator_config)
    provider_code_spec_path = schema_out_path / "provider-code-spec.json"
    admin_api_path = schema_out_path / "admin_api.yaml"
    if admin_api_path.exists():
        logger.warning(f"using existing admin api @ {admin_api_path}")
    else:
        download_admin_api(admin_api_path)

    if not run_binary_command_is_ok(
        cwd=schema_out_path,
        binary_name="tfplugingen-openapi",
        command=f"generate --config {generator_config_path.name} --output {provider_code_spec_path.name} {admin_api_path.name}",
        logger=logger,
    ):
        logger.critical("failed to generate spec")
        sys.exit(1)
    new_provider_spec = update_provider_code_spec(schema_parsed, provider_code_spec_path)
    provider_code_spec_path.write_text(new_provider_spec)
    logger.info(f"updated {provider_code_spec_path.name} ✅ ")

    go_code_output = schema_out_path / "internal"
    if go_code_output.exists():
        logger.warning(f"cleaning go code dir: {go_code_output}")
        clean_dir(go_code_output, recreate=True)

    if not run_binary_command_is_ok(
        cwd=schema_out_path,
        binary_name="tfplugingen-framework",
        command=f"generate resources --input ./{provider_code_spec_path.name} --output {go_code_output.name}",
        logger=logger,
    ):
        logger.critical("failed to generate plugin schema")
        sys.exit(1)

    logger.info(f"new files generated to {go_code_output} ✅")
    for go_file in sorted(go_code_output.rglob("*.go")):
        logger.info(f"new file @ '{go_file}'")


@app.command()
def schema_optional_only():
    repo_path = current_repo_path(Repo.TF)
    log_optional_only(repo_path)


@app.command()
def changelog(
    pr: str = typer.Argument("", help="the PR number, will read the file in .changelog/$pr_input.txt"),
    delete_input: bool = typer.Option(False, "-d", "--delete-input"),
):
    repo_path = current_repo_path(Repo.TF)
    changelog_input_path = repo_path / f".changelog/{pr}_input.txt"
    if not changelog_input_path.exists():
        logger.critical(f"no file @ {changelog_input_path}")
        raise typer.Abort
    changes_in = changelog_input_path.read_text()
    logger.info(f"will generate changelog to {changelog_input_path} based on changes:\n{changes_in}")
    changes_out = convert_to_changelog(changes_in)
    changelog_path = repo_path / f".changelog/{pr}.txt"
    changelog_path.write_text(changes_out)
    logger.info(f"updated file ✅ \n{changes_in}\n--> TO:\n{changes_out} ")
    if delete_input:
        logger.warning(f"deleting input file {changelog_input_path}")
        changelog_input_path.unlink()


@app.command()
def example_gen(
    in_path: Path = typer.Argument(..., help="Path to the latest code"),
    out_path: Path = typer.Argument("", help="Output path (empty will use input path)"),
):
    out_path = out_path or in_path  # type: ignore
    assert in_path.is_dir(), f"path not found: {in_path}"
    assert out_path.is_dir(), f"path not found: {out_path}"
    run_command_exit_on_failure("terraform fmt", cwd=in_path, logger=logger)
    if in_path == out_path:
        logger.warning(f"will overwrite/change files in {out_path}")
    else:
        logger.info(f"will use from {in_path} -> {out_path}")
    from zero_3rdparty import file_utils

    for path, rel_path in file_utils.iter_paths_and_relative(in_path, "*.tf", "*.sh", "*.py", "*.md", rglob=False):
        dest_path = out_path / rel_path
        file_utils.copy(path, dest_path, clean_dest=False)


@app.command()
def ci_tests(test_group_name: str = typer.Option("", "-g"), max_days_ago: int = typer.Option(1, "-d", "--days")):
    repo_path = current_repo_path(Repo.TF)
    token = run_command_receive_result("gh auth token", cwd=repo_path, logger=logger)
    os.environ[GH_TOKEN_ENV_NAME] = token
    job_runs = find_test_runs(
        utc_now() - timedelta(days=max_days_ago),
        include_job=include_test_jobs(test_group_name),
    )
    for job_id in sorted(job_runs.keys(), reverse=True):
        runs = job_runs[job_id]
        if not runs:
            logger.warning(f"no go tests for job_id={job_id}")
            continue
        job, summary = job_summary(runs)
        logger.info(f"[b]Summary for job [/]: {job.name} @ {job.url}")
        logger.info(summary)
        if fail_summary := fail_test_summary(runs):
            logger.info(indent(fail_summary, "  "))

    assert job_runs
