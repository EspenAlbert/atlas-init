from collections import defaultdict
from pathlib import Path

import requests
from model_lib import Entity, parse_model

from atlas_init.cli_tf.debug_logs_test_data import ApiSpecPath, find_normalized_path
from atlas_init.cli_tf.schema import logger
from atlas_init.cli_tf.openapi import OpenapiSchema


def go_sdk_breaking_changes(repo_path: Path, go_sdk_rel_path: str = "../atlas-sdk-go") -> Path:
    rel_path = "tools/releaser/breaking_changes"
    breaking_changes_dir = repo_path / go_sdk_rel_path / rel_path
    breaking_changes_dir = breaking_changes_dir.absolute()
    assert breaking_changes_dir.exists(), f"not found breaking_changes={breaking_changes_dir}"
    return breaking_changes_dir


def api_spec_path_transformed(sdk_repo_path: Path) -> Path:
    return sdk_repo_path / "openapi/atlas-api-transformed.yaml"


class ApiSpecPaths(Entity):
    method_paths: dict[str, list[ApiSpecPath]]

    def normalize_path(self, method: str, path: str) -> str:
        if path.startswith("/api/atlas/v1.0"):
            return ""
        return find_normalized_path(path, self.method_paths[method]).path


def parse_api_spec_paths(api_spec_path: Path) -> dict[str, list[ApiSpecPath]]:
    model = parse_model(api_spec_path, t=OpenapiSchema)
    paths: dict[str, list[ApiSpecPath]] = defaultdict(list)
    for path, path_dict in model.paths.items():
        for method in path_dict:
            paths[method.upper()].append(ApiSpecPath(path=path))
    return paths


# reusing url from terraform-provider-mongodbatlas/scripts/schema-scaffold.sh
ADMIN_API_URL = "https://raw.githubusercontent.com/mongodb/atlas-sdk-go/main/openapi/atlas-api-transformed.yaml"


def admin_api_url(branch: str) -> str:
    return ADMIN_API_URL.replace("/main/", f"/{branch}/")


def download_admin_api(dest: Path, branch: str = "main") -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = admin_api_url(branch)
    logger.info(f"downloading admin api to {dest} from {url}")
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    dest.write_bytes(response.content)
