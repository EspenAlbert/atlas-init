from pathlib import Path
from ask_shell import run_and_wait
import typer
from zero_3rdparty.file_utils import clean_dir, copy
from atlas_init.cli_args import ParsedPaths, option_sdk_repo_path, option_mms_repo_path


def go(
    mms_path_str: str = option_mms_repo_path,
    sdk_repo_path_str: str = option_sdk_repo_path,
    mms_branch: str = typer.Option("master", "--mms-branch", help="Branch to use for mms"),
    skip_mms_openapi: bool = typer.Option(
        False, "-smms", "--skip-mms-openapi", help="Skip mms openapi generation, use existing file instead"
    ),
):
    paths = ParsedPaths.from_strings(sdk_repo_path_str=sdk_repo_path_str, mms_path=mms_path_str)
    mms_path = paths.mms_repo_path
    assert mms_path, "mms_path is required"
    sdk_path = paths.sdk_repo_path
    assert sdk_path, "sdk_path is required"
    openapi_path = safe_openapi_path(mms_path) if skip_mms_openapi else generate_openapi_spec(mms_path, mms_branch)
    # todo: Add step for transforming the openapi spec, removing all but the latest versions, probably should check the openapi repo for how this works...
    generate_go_sdk(sdk_path, openapi_path)


def generate_openapi_spec(mms_path: Path, mms_branch: str) -> Path:
    run_and_wait(f"git stash && git checkout {mms_branch}", cwd=mms_path)
    bazelisk_bin_run = run_and_wait("mise which bazelisk", cwd=mms_path)
    bazelisk_bin = bazelisk_bin_run.stdout_one_line
    assert Path(bazelisk_bin).exists(), f"not found {bazelisk_bin}"
    openapi_run = run_and_wait(f"{bazelisk_bin} run //server:mms-openapi", cwd=mms_path, print_prefix="mms-openapi")
    assert openapi_run.clean_complete, f"failed to run {openapi_run}"
    return safe_openapi_path(mms_path)


def safe_openapi_path(mms_path: Path) -> Path:
    openapi_path = mms_path / "server/openapi/services/openapi-mms.json"
    assert openapi_path.exists(), f"not found {openapi_path}"
    return openapi_path


def generate_go_sdk(repo_path: Path, openapi_path: Path) -> None:
    SDK_FOLDER = repo_path / "admin"
    clean_dir(SDK_FOLDER, recreate=True)
    generate_script = repo_path / "tools/scripts/generate.sh"
    assert generate_script.exists(), f"not found {generate_script}"
    openapi_folder = repo_path / "openapi"
    copy(openapi_path, openapi_folder / openapi_path.name)
    generate_env = {
        "OPENAPI_FOLDER": str(openapi_folder),
        "OPENAPI_FILE_NAME": openapi_path.name,
        "SDK_FOLDER": str(SDK_FOLDER),
    }
    run_and_wait(f"{generate_script}", cwd=repo_path / "tools", env=generate_env, print_prefix="go sdk create")
