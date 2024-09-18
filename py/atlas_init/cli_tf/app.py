import logging
import os
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import typer
from zero_3rdparty import file_utils
from zero_3rdparty.datetime_utils import utc_now
from zero_3rdparty.file_utils import clean_dir

from atlas_init.cli_helper.run import (
    add_to_clipboard,
    run_binary_command_is_ok,
    run_command_exit_on_failure,
    run_command_receive_result,
)
from atlas_init.cli_tf.changelog import convert_to_changelog
from atlas_init.cli_tf.github_logs import (
    GH_TOKEN_ENV_NAME,
    find_test_runs,
    include_filestems,
    include_test_jobs,
    summary_dir,
)
from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_summary import GoTestSummary, summary_lines
from atlas_init.cli_tf.schema import (
    download_admin_api,
    dump_generator_config,
    parse_py_terraform_schema,
    update_provider_code_spec,
)
from atlas_init.cli_tf.schema_inspection import log_optional_only
from atlas_init.cli_tf.schema_v2 import (
    generate_resource_go_resource_schema,
    parse_schema,
)
from atlas_init.cli_tf.schema_v2_api_parsing import add_api_spec_info
from atlas_init.cli_tf.schema_v2_sdk import generate_model_go, parse_sdk_model
from atlas_init.repos.path import Repo, current_repo_path
from atlas_init.settings.env_vars import init_settings
from atlas_init.settings.interactive import confirm

app = typer.Typer(no_args_is_help=True)
logger = logging.getLogger(__name__)


@app.command()
def schema(
    branch: str = typer.Option("main", "-b", "--branch"),
):
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
        download_admin_api(admin_api_path, branch=branch)

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
        command=f"generate all --input ./{provider_code_spec_path.name} --output {go_code_output.name}",
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
def ci_tests(
    test_group_name: str = typer.Option("", "-g"),
    max_days_ago: int = typer.Option(1, "-d", "--days"),
    branch: str = typer.Option("master", "-b", "--branch"),
    workflow_file_stems: str = typer.Option("test-suite,terraform-compatibility-matrix", "-w", "--workflow"),
    only_last_workflow: bool = typer.Option(False, "-l", "--last"),
    summary_name: str = typer.Option("", "-s", "--summary", help="the name of the summary directory to store detailed test results"),
):  # sourcery skip: use-named-expression
    repo_path = current_repo_path(Repo.TF)
    token = run_command_receive_result("gh auth token", cwd=repo_path, logger=logger)
    os.environ[GH_TOKEN_ENV_NAME] = token
    end_test_date = utc_now()
    start_test_date = end_test_date - timedelta(days=max_days_ago)
    job_runs = find_test_runs(
        start_test_date,
        include_job=include_test_jobs(test_group_name),
        branch=branch,
        include_workflow=include_filestems(set(workflow_file_stems.split(","))),
    )
    test_results: dict[str, list[GoTestRun]] = defaultdict(list)
    workflow_ids = set()
    for key in sorted(job_runs.keys(), reverse=True):
        workflow_id, job_id = key
        workflow_ids.add(workflow_id)
        if only_last_workflow and len(workflow_ids) > 1:
            logger.info("only showing last workflow")
            break
        runs = job_runs[key]
        if not runs:
            logger.warning(f"no go tests for job_id={job_id}")
            continue
        for run in runs:
            test_results[run.name].append(run)

    failing_names = [name for name, name_runs in test_results.items() if all(run.is_failure for run in name_runs)]
    if not failing_names:
        logger.info("ALL TESTS PASSED! ✅")
        return
    if summary_name:
        summary_dir_path = summary_dir(summary_name)
        file_utils.clean_dir(summary_dir_path)
        summaries = [GoTestSummary(name=name, results=runs) for name, runs in test_results.items()]
        summaries = [summary for summary in summaries if summary.results and not summary.is_skipped]
        top_level_summary = ["# SUMMARY OF ALL TESTS name (success rate)"]
        for summary in sorted(summaries):
            test_summary_path = summary_dir_path / f"{summary.success_rate_human}_{summary.name}.md"
            test_summary_md = summary_lines(summary, start_test_date, end_test_date)
            file_utils.ensure_parents_write_text(test_summary_path, test_summary_md)
            top_level_summary.append(f"- {summary.name} ({summary.success_rate_human})")
        summary_str = "\n".join(top_level_summary)
    else:
        summary = ["# SUMMARY OF FAILING TESTS"]
        summary_fail_details: list[str] = ["# FAIL DETAILS"]

        for fail_name in failing_names:
            fail_tests = test_results[fail_name]
            summary.append(f"- {fail_name} has {len(fail_tests)} failures:")
            summary.extend(
                f"  - [{fail_run.when} failed in {fail_run.runtime_human}]({fail_run.url})" for fail_run in fail_tests
            )
            summary_fail_details.append(f"\n\n ## {fail_name} details:")
            summary_fail_details.extend(f"```\n{fail_run.finish_summary()}\n```" for fail_run in fail_tests)
        logger.info("\n".join(summary_fail_details))
        summary_str = "\n".join(summary)
    add_to_clipboard(summary_str, logger)
    logger.info(summary_str)


@app.command()
def schema2(
    resource: str = typer.Argument(
        "", help="the resource name to generate the schema for. Must exist in the schema. E.g., 'stream_processor'"
    ),
    branch: str = typer.Option("main", "-b", "--branch", help="the branch for downloading openapi spec"),
    admin_api_path: Path = typer.Option(
        "", "-a", "--admin-api-path", help="the path to store/download the openapi spec"
    ),
    config_path: Path = typer.Option("", "-c", "--config", help="the path to the SchemaV2 config"),
    replace: bool = typer.Option(False, "-r", "--replace", help="replace the existing schema file"),
    sdk_repo_path_str: str = typer.Option("", "-sdk", "--sdk-repo-path", help="the path to the sdk repo"),
):
    repo_path = current_repo_path(Repo.TF)
    config_path = config_path or repo_path / "schema_v2.yaml"
    admin_api_path = admin_api_path or repo_path / "admin_api.yaml"
    if admin_api_path.exists():
        logger.info(f"using existing admin api @ {admin_api_path}")
    else:
        download_admin_api(admin_api_path, branch=branch)
    schema = parse_schema(config_path)
    logger.info("adding api spec info to schema")
    add_api_spec_info(schema, admin_api_path, minimal_refs=True)
    go_old = repo_path / f"internal/service/{resource.replace('_', '')}/resource_schema.go"
    if not go_old.exists():
        if confirm(f"no file found @ {go_old}, ok to create it?", is_interactive=True, default=True):
            go_old.parent.mkdir(exist_ok=True, parents=True)
        else:
            logger.critical(f"no file found @ {go_old}")
            raise typer.Abort
    if replace:
        logger.warning(f"replacing existing schema @ {go_old}")
        go_new = go_old
    else:
        go_new = go_old.with_name("resource_schema_gen.go")
    gen_src = generate_resource_go_resource_schema(schema, resource)
    go_new.write_text(gen_src)
    logger.info(f"generated new schema @ {go_new} ✅")

    resource_schema = schema.resources[resource]
    if conversion_config := resource_schema.conversion:
        if not confirm(
            f"resource {resource} has conversion, ok to generate conversion functions?",
            is_interactive=True,
            default=True,
        ):
            logger.info("skipping conversion functions")
            return
        logger.info("generating conversion functions")
        if not sdk_repo_path_str:
            logger.critical("must provide sdk repo path when generating conversion functions")
            raise typer.Abort
        sdk_repo_path = Path(sdk_repo_path_str)
        if not sdk_repo_path.exists():
            logger.critical(f"no sdk repo found @ {sdk_repo_path}")
            raise typer.Abort
        for sdk_start_ref in conversion_config.sdk_start_refs:
            sdk_model = parse_sdk_model(sdk_repo_path, sdk_start_ref.name)
            go_conversion_src = generate_model_go(schema, resource_schema, sdk_model)
            go_conversion_path = go_old.with_name("model.go")
            go_conversion_path.write_text(go_conversion_src)
