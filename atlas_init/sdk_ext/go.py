from contextlib import suppress
import logging
from pathlib import Path
from ask_shell import confirm, run_and_wait
from model_lib import dump, parse_model
import typer
from zero_3rdparty.file_utils import clean_dir, copy, ensure_parents_write_text
from atlas_init.cli_args import ParsedPaths, option_sdk_repo_path, option_mms_repo_path
from atlas_init.cli_tf.openapi import OpenapiSchema

_go_mod_line = "replace go.mongodb.org/atlas-sdk/v20250312005 v20250312005.0.0 => ../atlas-sdk-go"
logger = logging.getLogger(__name__)


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
    openapi_path = transform_openapi(openapi_path, sdk_path / "openapi/openapi-mms.yaml")
    generate_go_sdk(sdk_path, openapi_path)
    confirm(f"Have you remembered to add to your go.mod file: {_go_mod_line}")


def transform_openapi(old: Path, dest_path: Path) -> Path:
    api_spec = parse_model(old, t=OpenapiSchema)
    new_api_spec = api_spec.model_dump()
    for path in api_spec.paths.keys():
        for method_name, method in api_spec.methods_with_name(path):
            responses = method.get("responses", {})
            for code, multi_responses in responses.items():
                with suppress(AlreadySingleVersion):
                    new_api_spec["paths"][path][method_name]["responses"][code]["content"] = use_a_single_version(
                        multi_responses, api_spec, path
                    )
            if request_body := method.get("requestBody", {}):
                with suppress(AlreadySingleVersion):
                    new_api_spec["paths"][path][method_name]["requestBody"]["content"] = use_a_single_version(
                        request_body, api_spec, path
                    )
    dest_yaml = dump(new_api_spec, "yaml")
    ensure_parents_write_text(dest_path, dest_yaml)
    return dest_path


class AlreadySingleVersion(Exception):
    pass


def use_a_single_version(multi_content: dict, api_spec: OpenapiSchema, path: str) -> dict[str, dict]:
    if api_versions := api_spec._unpack_schema_versions(multi_content):
        if len(api_versions) > 1:
            latest_version = max(api_versions)
            last_header = f"application/vnd.atlas.{latest_version}+json"
            old_content = multi_content["content"]
            assert last_header in old_content, f"failed to find {last_header} for {path} in {old_content.keys()}"
            return {last_header: old_content[last_header]}
    raise AlreadySingleVersion


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
    openapi_dest_path = openapi_folder / openapi_path.name
    if openapi_path != openapi_dest_path:
        copy(openapi_path, openapi_dest_path)
    generate_env = {
        "OPENAPI_FOLDER": str(openapi_folder),
        "OPENAPI_FILE_NAME": openapi_path.name,
        "SDK_FOLDER": str(SDK_FOLDER),
    }
    run_and_wait(f"{generate_script}", cwd=repo_path / "tools", env=generate_env, print_prefix="go sdk create")
    mockery_script = repo_path / "tools/scripts/generate_mocks.sh"
    run_and_wait(f"{mockery_script}", cwd=repo_path / "tools", print_prefix="go sdk mockery")
