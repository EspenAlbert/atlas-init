from collections import defaultdict
from pathlib import Path

from model_lib import parse_model

from atlas_init.cli_tf.debug_logs_test_data import ApiSpecPath
from atlas_init.cli_tf.schema_v2_api_parsing import OpenapiSchema


def go_sdk_breaking_changes(repo_path: Path, go_sdk_rel_path: str = "../atlas-sdk-go") -> Path:
    rel_path = "tools/releaser/breaking_changes"
    breaking_changes_dir = repo_path / go_sdk_rel_path / rel_path
    breaking_changes_dir = breaking_changes_dir.absolute()
    assert breaking_changes_dir.exists(), f"not found breaking_changes={breaking_changes_dir}"
    return breaking_changes_dir


def parse_api_spec_paths(sdk_repo_path: Path) -> dict[str, list[ApiSpecPath]]:
    api_spec_path = sdk_repo_path / "openapi/atlas-api-transformed.yaml"
    model = parse_model(api_spec_path, t=OpenapiSchema)
    paths: dict[str, list[ApiSpecPath]] = defaultdict(list)
    for path, path_dict in model.paths.items():
        for method in path_dict:
            paths[method.upper()].append(ApiSpecPath(path=path))
    return paths
