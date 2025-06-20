import logging
from collections.abc import Callable
from pathlib import Path
from pydoc import locate
from typing import Literal

import typer
from ask_shell.typer_command import configure_logging
from model_lib import dump, parse_payload
from zero_3rdparty.file_utils import iter_paths

from atlas_init.cli_helper import sdk_auto_changes
from atlas_init.cli_helper.run import (
    run_binary_command_is_ok,
    run_command_exit_on_failure,
    run_command_receive_result,
)
from atlas_init.cli_helper.sdk import (
    SDK_VERSION_HELP,
    SdkVersion,
    SdkVersionUpgrade,
    find_breaking_changes,
    find_latest_sdk_version,
    format_breaking_changes,
    is_removed,
    parse_breaking_changes,
)
from atlas_init.cli_helper.tf_runner import (
    TerraformRunError,
    dump_tf_vars,
    export_outputs,
    get_tf_vars,
    run_terraform,
)
from atlas_init.repos.go_sdk import go_sdk_breaking_changes
from atlas_init.repos.path import (
    Repo,
    current_repo,
    current_repo_path,
    find_go_mod_dir,
    find_paths,
    resource_name,
)
from atlas_init.settings.config import RepoAliasNotFoundError, TestSuite
from atlas_init.settings.env_vars import (
    active_suites,
    init_settings,
)
from atlas_init.settings.env_vars_generated import AWSSettings, AtlasSettings
from atlas_init.settings.path import (
    CwdIsNoRepoPathError,
    dump_vscode_dotenv,
    repo_path_rel_path,
)
from atlas_init.typer_app import app, app_command, extra_root_commands

logger = logging.getLogger(__name__)


@app_command()
def init(context: typer.Context):
    settings = init_settings()
    extra_args = context.args
    logger.info(f"in the init command: {extra_args}")
    run_terraform(settings, "init", extra_args)


@app_command()
def plan(context: typer.Context, *, skip_outputs: bool = False):
    _plan_or_apply(context.args, "plan", skip_outputs=skip_outputs)


@app_command()
def apply(context: typer.Context, *, skip_outputs: bool = False):
    suites = _plan_or_apply(context.args, "apply", skip_outputs=skip_outputs)
    for suite in suites:
        for hook in suite.post_apply_hooks:
            logger.info(f"running post apply hook: {hook.name}")
            hook_func = locate(hook.locate)
            hook_func()  # type: ignore


def _plan_or_apply(extra_args: list[str], command: Literal["plan", "apply"], *, skip_outputs: bool) -> list[TestSuite]:  # type: ignore
    settings = init_settings(AtlasSettings, AWSSettings)
    logger.info(f"using the '{command}' command, extra args: {extra_args}")
    try:
        suites = active_suites(settings)
    except (CwdIsNoRepoPathError, RepoAliasNotFoundError) as e:
        logger.warning(repr(e))
        suites = []

    tf_vars = get_tf_vars(settings, suites)
    dump_tf_vars(settings, tf_vars)

    try:
        run_terraform(settings, command, extra_args)
    except TerraformRunError as e:
        logger.error(repr(e))  # noqa: TRY400
        raise typer.Exit(1) from e

    if not skip_outputs:
        export_outputs(settings)

    if settings.env_vars_generated.exists():
        dump_vscode_dotenv(settings.env_vars_generated, settings.env_vars_vs_code)
        logger.info(f"your .env file is ready @ {settings.env_vars_vs_code}")
    return suites


@app_command()
def destroy(context: typer.Context):
    extra_args = context.args
    settings = init_settings()
    if not settings.tf_state_path.exists():
        logger.warning(f"no terraform state found  {settings.tf_state_path}, exiting")
        return
    tf_vars = get_tf_vars(settings, [])
    dump_tf_vars(settings, tf_vars)
    try:
        run_terraform(settings, "destroy", extra_args)
    except TerraformRunError as e:
        logger.error(repr(e))  # noqa: TRY400
        return


@app_command()
def sdk_upgrade(
    old: SdkVersion = typer.Argument(help=SDK_VERSION_HELP),
    new: SdkVersion = typer.Argument(
        default_factory=find_latest_sdk_version,
        help=SDK_VERSION_HELP + "\nNo Value=Latest",
    ),
    resource: str = typer.Option("", help="for only upgrading a single resource"),
    dry_run: bool = typer.Option(False, help="only log out the changes"),
    auto_change_name: str = typer.Option("", help="any extra replacements done in the file"),
):
    SdkVersionUpgrade(old=old, new=new)
    repo_path, _ = repo_path_rel_path()
    logger.info(f"bumping from {old} -> {new} @ {repo_path}")

    sdk_breaking_changes_path = go_sdk_breaking_changes(repo_path)
    all_breaking_changes = parse_breaking_changes(sdk_breaking_changes_path, old, new)
    replacements = {
        f"go.mongodb.org/atlas-sdk/{old}/mockadmin": f"go.mongodb.org/atlas-sdk/{new}/mockadmin",
        f"go.mongodb.org/atlas-sdk/{old}/admin": f"go.mongodb.org/atlas-sdk/{new}/admin",
    }
    auto_modifier: Callable[[str, str], str] | None = None
    if auto_change_name:
        func_path = f"{sdk_auto_changes.__name__}.{auto_change_name}"
        auto_modifier = locate(func_path)  # type: ignore

    change_count = 0
    resources: set[str] = set()
    resources_breaking_changes: set[str] = set()
    for path in iter_paths(repo_path, "*.go", ".mockery.yaml"):
        text_old = path.read_text()
        if all(replace_in not in text_old for replace_in in replacements):
            continue
        r_name = resource_name(repo_path, path)
        if resource and resource != r_name:
            continue
        resources.add(r_name)
        logger.info(f"updating sdk version in {path}")
        if breaking_changes := find_breaking_changes(text_old, all_breaking_changes):
            changes_formatted = format_breaking_changes(text_old, breaking_changes)
            logger.warning(f"found breaking changes: {changes_formatted}")
            if is_removed(breaking_changes):
                resources_breaking_changes.add(r_name)
        text_new = text_old
        for replace_in, replace_out in replacements.items():
            text_new = text_new.replace(replace_in, replace_out)
        if not dry_run:
            if auto_modifier:
                text_new = auto_modifier(text_new, old)
            path.write_text(text_new)
        change_count += 1
    if change_count == 0:
        logger.warning("no changes found")
        return
    logger.info(f"changed in total: {change_count} files")
    resources_str = "\n".join(
        f"- {r} 💥" if r in resources_breaking_changes else f"- {r}" for r in sorted(resources) if r
    )
    logger.info(f"resources changed: \n{resources_str}")
    if dry_run:
        logger.warning("dry-run, no changes to go.mod")
        return
    go_mod_parent = find_go_mod_dir(repo_path)
    if not run_binary_command_is_ok("go", "mod tidy", cwd=go_mod_parent, logger=logger):
        logger.critical(f"failed to run go mod tidy in {go_mod_parent}")
        raise typer.Exit(1)


@app_command()
def pre_commit(
    skip_build: bool = typer.Option(default=False),
    skip_lint: bool = typer.Option(default=False),
    max_issues: int = typer.Option(1000, "-m", "--max"),
):
    golang_ci_lint_args = f"--max-same-issues {max_issues} --max-issues-per-linter {max_issues}"
    match current_repo():
        case Repo.CFN:
            repo_path, resource_path, r_name = find_paths()
            build_cmd = f"cd {resource_path} && make build"
            # TODO: understand why piping to grep doesn't work
            # f"golangci-lint run --path-prefix=./cfn-resources | grep {r_name}"
            format_cmd_str = (
                f"cd cfn-resources && golangci-lint run --path-prefix=./cfn-resources {golang_ci_lint_args}"
            )
        case Repo.TF:
            repo_path = current_repo_path()
            build_cmd = "make build"
            format_cmd_str = f"golangci-lint run {golang_ci_lint_args}"
        case _:
            raise NotImplementedError
    if skip_build:
        logger.warning("skipping build")
    else:
        run_command_exit_on_failure(build_cmd, cwd=repo_path, logger=logger)
    if skip_lint:
        logger.warning("skipping formatting")
    else:
        run_command_exit_on_failure(format_cmd_str, cwd=repo_path, logger=logger)


@app_command()
def repo_dump():
    code_root = Path.home() / "code"
    path_urls = {}
    for repo_git_path in iter_paths(code_root, ".git", exclude_folder_names=[".terraform"]):
        repo_path = repo_git_path.parent
        logger.info(f"repo: {repo_path}")
        url = run_command_receive_result("git remote get-url origin", cwd=repo_path, logger=logger, can_fail=True)
        if url.startswith("FAIL:"):
            continue
        path_urls[str(repo_path)] = url
    out_path = code_root / "repos.json"
    repos_json = dump(path_urls, "pretty_json")
    out_path.write_text(repos_json)


@app_command()
def repo_clone():
    repos_file = Path.home() / "code" / "repos.json"
    repo_path_json: dict[str, str] = parse_payload(repos_file)  # type: ignore
    for repo_path_str, url in repo_path_json.items():
        logger.info(f"cloning {url} @ {repo_path_str}")
        repo_path = Path(repo_path_str)
        parent_dir = repo_path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        if repo_path.exists():
            logger.warning(f"skipping {repo_path}, already exists")
            continue
        run_command_exit_on_failure(f"git clone {url} {repo_path.name}", cwd=parent_dir, logger=logger)


def typer_main():
    extra_root_commands()
    configure_logging(app)
    app()


if __name__ == "__main__":
    typer_main()
