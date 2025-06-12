import logging
import os
from pathlib import Path
from typing import Callable

import pytest
from model_lib import dump, parse_model
from pytest_regressions.common import check_text_files

from atlas_init.cli_helper.run import run_command_is_ok
from atlas_init.cli_tf.codegen.models import ApiResourcesConfig
from atlas_init.cli_tf.codegen.openapi_minimal import minimal_api_spec_simplified

logger = logging.getLogger(__name__)


@pytest.fixture()
def tf_api_resources_config(tf_repo_path) -> ApiResourcesConfig:
    path = tf_repo_path / "tools/codegen/config.yml"
    return parse_model(path, t=ApiResourcesConfig, format="yaml")


def test_parsing_config(tf_api_resources_config: ApiResourcesConfig):
    assert (
        tf_api_resources_config.get_resource("database_user_api").read.path  # type: ignore
        == "/api/atlas/v2/groups/{groupId}/databaseUsers/{databaseName}/{username}"
    )


resources = [
    "cluster_api",
    "custom_db_role_api",
    "database_user_api",
    "project_api",
    "push_based_log_export_api",
    "resource_policy_api",
    "search_deployment_api",
    "stream_connection_api",
    "stream_instance_api",
]


@pytest.fixture()
def resource_skip() -> Callable[[str], None]:
    included = (
        set(os.environ.get("RESOURCE_FILTER", "").split(",")) if os.environ.get("RESOURCE_FILTER") else set(resources)
    )

    def skip_if_not_included(resource_name: str) -> None:
        if resource_name not in included:
            pytest.skip(f"Skipping {resource_name} as it is not in {included}")

    return skip_if_not_included


@pytest.mark.parametrize("resource_name", resources)
def test_create_minimal_api_resources_config(
    resource_skip, tf_api_resources_config: ApiResourcesConfig, live_api_spec, resource_name, file_regression
):
    """
    0. change pytest_regressions.common.L48 if len(diff_lines) <= 500 --> 50_000
    1. Run first with API_SPEC_PATH set to https://github.com/mongodb/openapi/blob/main/openapi/v2.yaml
    2. Run second time with API_SPEC_PATH set to https://github.com/mongodb/atlas-sdk-go/blob/main/openapi/atlas-api-transformed.yaml to see the differences
    """
    resource_skip(resource_name)
    # print(f"Resources: {tf_api_resources_config.list_resources()}")
    minimal_spec = minimal_api_spec_simplified(tf_api_resources_config.get_resource(resource_name), live_api_spec)
    spec_yaml = dump(minimal_spec, format="yaml")
    file_regression.check(
        spec_yaml,
        extension=".yaml",
        basename=f"api_spec_{resource_name}",
    )
    # dump_diff(resource_name, spec_yaml)


def dump_diff(resource_name, spec_yaml):
    output_dir, diffs_dir = output_diff_dir()
    diffs_dir.mkdir(parents=True, exist_ok=True)
    obtained_filename = diffs_dir / f"api_spec_{resource_name}.yaml"
    obtained_filename.write_text(spec_yaml, encoding="utf-8")
    expected_api_spec_filepath = output_dir / f"api_spec_{resource_name}.yaml"
    check_text_files(
        obtained_filename,
        expected_api_spec_filepath,
    )


def output_diff_dir() -> tuple[Path, Path]:
    current_file = Path(__file__)
    output_dir = current_file.parent / current_file.stem
    diffs_dir = output_dir / "diffs"
    return output_dir, diffs_dir


def test_diff_dir():
    _, diff_dir = output_diff_dir()
    html_paths = sorted(f"chrome {path}" for path in diff_dir.glob("*.html"))
    logger.info(f"HTML files in diff directory:\n{'\n'.join(html_paths)}")


@pytest.mark.parametrize("resource_name", resources)
def test_generate_tf_resources(resource_skip, tf_repo_path, resource_name):
    resource_skip(resource_name)
    output_dir, _ = output_diff_dir()
    expected_api_spec_filepath = output_dir / f"api_spec_{resource_name}.yaml"
    env = {
        **os.environ,
        "SKIP_OPENAPI_DOWNLOAD": "true",
        "OPENAPI_SPEC_FILE_PATH": expected_api_spec_filepath,
    }
    assert run_command_is_ok(
        f"go run tools/codegen/main.go {resource_name}",
        env=env,
        cwd=tf_repo_path,
        logger=logger,
        dry_run=False,
    ), f"Failed to generate Terraform resources for {resource_name}"
