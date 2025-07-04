from collections import defaultdict
from concurrent.futures import Future, as_completed
from functools import lru_cache
import logging
import os
from pathlib import Path
import re

from ask_shell import new_task, run_pool
from model_lib import dump, parse_model
from pydantic import BaseModel, Field, model_validator
import requests
import typer
from requests.auth import HTTPDigestAuth
from zero_3rdparty.file_utils import ensure_parents_write_text
from zero_3rdparty.str_utils import ensure_prefix, ensure_suffix

from atlas_init.cli_tf.mock_tf_log import resolve_admin_api_path
from atlas_init.cli_tf.openapi import OpenapiSchema
from atlas_init.settings.env_vars import init_settings
from atlas_init.settings.env_vars_generated import AtlasSettingsWithProject
from atlas_init.settings.env_vars_modules import (
    TFModuleCluster,
    TFModuleFederated_Vars,
    TFModuleProject_Extra,
    TFModuleStream_Instance,
)
from atlas_init.settings.path import load_dotenv
from atlas_init.tf_ext.settings import TfDepSettings

logger = logging.getLogger(__name__)

ALLOWED_MISSING_VARS: set[str] = {
    "alertConfigId",
    "alertId",
    "clientId",
    "cloudProvider",
    # "federationSettingsId",
    "invoiceId",
    # "name",
    "pipelineName",
    "processId",
    "username",
}


# export ATLAS_INIT_TEST_SUITES=clusterm10,s3,federated,project,stream_connection
def resolve_path_variables() -> dict[str, str]:
    settings = init_settings()
    env_vars_full = load_dotenv(settings.env_vars_vs_code)
    atlas_settings = AtlasSettingsWithProject(**env_vars_full)
    cluster_settings = TFModuleCluster(**env_vars_full)
    project_settings = TFModuleProject_Extra(**env_vars_full)
    stream_settings = TFModuleStream_Instance(**env_vars_full)
    federated_settings = TFModuleFederated_Vars(**env_vars_full)
    return {
        "orgId": atlas_settings.MONGODB_ATLAS_ORG_ID,
        "cloudProvider": "AWS",
        "federationSettingsId": federated_settings.MONGODB_ATLAS_FEDERATION_SETTINGS_ID,
        "clusterName": cluster_settings.MONGODB_ATLAS_CLUSTER_NAME,
        "name": cluster_settings.MONGODB_ATLAS_CLUSTER_NAME,
        "groupId": atlas_settings.MONGODB_ATLAS_PROJECT_ID,
        "teamId": project_settings.MONGODB_ATLAS_TEAM_ID,
        "tenantName": stream_settings.MONGODB_ATLAS_STREAM_INSTANCE_NAME,
        "apiUserId": atlas_settings.MONGODB_ATLAS_PROJECT_OWNER_ID,
        "username": atlas_settings.MONGODB_ATLAS_USER_EMAIL,
    }


class ApiCall(BaseModel):
    path: str
    accept_header: str = "application/vnd.atlas.2023-01-01+json"
    query_args: dict[str, str] = Field(default_factory=dict)
    operation_id: str = ""

    def path_with_variables(self, path_variables: dict[str, str]):
        return self.path.format(**path_variables)

    @model_validator(mode="after")
    def check_path_variables(self):
        self.accept_header = ensure_prefix(self.accept_header, "application/vnd.atlas.")
        self.accept_header = ensure_suffix(self.accept_header, "+json")
        return self


class UnresolvedPathsError(Exception):
    def __init__(self, missing_var_paths: dict[str, list[str]]) -> None:
        self.missing_var_paths = missing_var_paths
        missing_vars_formatted = "\n".join(f"{var}: {paths}" for var, paths in missing_var_paths.items())
        super().__init__(f"Failed to resolve path variables:\nMissing vars: {missing_vars_formatted}")


_path_variables_re = re.compile(r"\{([\w-]+)\}")


class ApiCalls(BaseModel):
    calls: list[ApiCall] = Field(default_factory=list)
    path_variables: dict[str, str] = Field(default_factory=resolve_path_variables)

    @model_validator(mode="after")
    def check_path_variables(self):
        missing_vars_paths: dict[str, list[str]] = defaultdict(list)
        for call in self.calls:
            try:
                resolved = call.path_with_variables(self.path_variables)
            except KeyError as e:
                missing_vars_paths[str(e).strip("'")].append(f"{call.operation_id} {call.path}")
                continue
            for match in _path_variables_re.finditer(resolved):
                missing_vars_paths[match.group(1)].append(resolved)
        for allowed_missing in ALLOWED_MISSING_VARS:
            if allowed_missing in missing_vars_paths:
                logger.info(f"Allowed missing variable {allowed_missing}: {missing_vars_paths[allowed_missing]}")
                del missing_vars_paths[allowed_missing]
        if missing_vars_paths:
            raise UnresolvedPathsError(missing_var_paths=missing_vars_paths)
        return self


@lru_cache
def _public_private_key() -> tuple[str, str]:
    public_key = os.environ.get("MONGODB_ATLAS_PUBLIC_KEY")
    private_key = os.environ.get("MONGODB_ATLAS_PRIVATE_KEY")
    if not public_key or not private_key:
        raise ValueError("MONGODB_ATLAS_PUBLIC_KEY and MONGODB_ATLAS_PRIVATE_KEY must be set in environment variables.")
    return public_key, private_key


def call_api(api_call: ApiCall, path_variables: dict[str, str]) -> dict:
    resolved_path = api_call.path_with_variables(path_variables)
    response = requests.get(
        f"https://cloud-dev.mongodb.com/{resolved_path.lstrip('/')}",
        params=api_call.query_args,
        headers={"Accept": api_call.accept_header, "Content-Type": "application/json"},
        auth=HTTPDigestAuth(*_public_private_key()),
    )
    response.raise_for_status()
    return response.json()


def api_config(config_path_str: str = typer.Option("", "-p", "--path", help="Path to the API config file")):
    if config_path_str == "":
        with new_task("Find API Calls that use pagination"):
            config_path = dump_config_path()
    else:
        config_path = Path(config_path_str)
    assert config_path.exists(), f"Config file {config_path} does not exist."
    model = parse_model(config_path, t=ApiCalls)
    total_calls = len(model.calls)
    assert _public_private_key(), "Public and private keys must be set in environment variables."
    path_variables = model.path_variables
    with run_pool(
        task_name="make API calls", max_concurrent_submits=10, threads_used_per_submit=1, total=total_calls
    ) as pool:
        futures: dict[Future, ApiCall] = {
            pool.submit(call_api, api_call, path_variables): api_call for api_call in model.calls
        }
    for future in as_completed(futures):
        api_call = futures[future]
        try:
            result = future.result()
        except Exception as e:
            logger.error(f"Failed to make API call {api_call}: {e}")
            continue
        logger.info(f"API call {api_call} completed successfully with result: {result}")


def api(path: str = typer.Option("-p", "--path", help="Path to the API endpoint")):
    assert path, "Path must be provided."
    accept_header = "application/vnd.atlas.2023-01-01+json"
    try:
        r = requests.get(
            f"https://cloud-dev.mongodb.com/{path.lstrip('/')}",
            headers={"Accept": accept_header, "Content-Type": "application/json"},
            auth=HTTPDigestAuth(*_public_private_key()),
        )
        print(r.json())
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(e)
        print(e.response)


def dump_config_path() -> Path:
    settings = TfDepSettings.from_env()
    latest_api_spec = resolve_admin_api_path()
    model = parse_model(latest_api_spec, t=OpenapiSchema)
    paginated_paths: list[ApiCall] = []
    path_versions = list(model.path_method_api_versions())

    for (path, method, code), versions in path_versions:
        if method != "get" or code != "200":
            continue
        assert len(versions) == 1, f"{path} {method} {code} has multiple versions: {versions}"
        get_method = model.get_method(path)
        if not get_method:
            continue
        parameters = get_method.get("parameters", [])
        for param in parameters:
            if param_ref := param.get("$ref"):
                if param_ref.endswith("itemsPerPage"):
                    version = versions[0].strftime("%Y-%m-%d")
                    paginated_paths.append(
                        ApiCall(
                            path=path,
                            query_args={"itemsPerPage": "0", "pageNum": "0"},
                            accept_header=f"application/vnd.atlas.{version}+json",
                            operation_id=get_method["operationId"],
                        )
                    )
    config_path = settings.api_calls_path
    calls = ApiCalls(
        calls=paginated_paths,
    )
    calls_yaml = dump(calls, "yaml")
    logger.info(f"Dumped {len(paginated_paths)} API calls to {config_path}")
    ensure_parents_write_text(config_path, calls_yaml)
    return config_path
