from collections import defaultdict
from concurrent.futures import Future, as_completed
from functools import lru_cache
import json
import logging
import os
from pathlib import Path

from ask_shell import new_task, print_to_live, run_pool
from model_lib import dump, parse_model
from pydantic import BaseModel, Field, model_validator
import requests
from rich.markdown import Markdown
import typer
from requests.auth import HTTPDigestAuth
from zero_3rdparty.file_utils import ensure_parents_write_text
from zero_3rdparty.str_utils import ensure_prefix, ensure_suffix, instance_repr

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
    "invoiceId",
    # "name",
    "pipelineName",
    "processId",
    "username",
}
ALLOWED_ERROR_CODES: set[str] = {
    "CANNOT_USE_CLUSTER_IN_SERVERLESS_INSTANCE_API",
    "VALIDATION_ERROR",
    "UNEXPECTED_ERROR",
    "CANNOT_USE_NON_FLEX_CLUSTER_IN_FLEX_API",
    "CHECKPOINTS_ONLY_ON_CONTINOUS_BACKUP",
    "INCORRECT_BACKUP_API_ENDPOINT",
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
    operation_id: str
    path: str
    accept_header: str = "application/vnd.atlas.2023-01-01+json"
    query_args: dict[str, str] = Field(default_factory=dict)

    def __str__(self):
        return instance_repr(self, ["operation_id", "path"])

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


class ApiCalls(BaseModel):
    calls: list[ApiCall] = Field(default_factory=list)
    ignored_calls: list[ApiCall] = Field(default_factory=list)
    path_variables: dict[str, str] = Field(default_factory=resolve_path_variables)
    skip_validation: bool = False

    @model_validator(mode="after")
    def check_path_variables(self):
        if self.skip_validation:
            return self
        missing_vars_paths: dict[str, list[str]] = defaultdict(list)
        ok_calls = []
        for call in self.calls:
            try:
                call.path_with_variables(self.path_variables)
                ok_calls.append(call)
            except KeyError as e:
                missing_vars_paths[str(e).strip("'")].append(f"{call.operation_id} {call.path}")
                self.ignored_calls.append(call)
                continue
        for allowed_missing in sorted(ALLOWED_MISSING_VARS):
            if allowed_missing in missing_vars_paths:
                logger.info(f"Allowed missing variable {allowed_missing}: {missing_vars_paths[allowed_missing]}")
                del missing_vars_paths[allowed_missing]
        if missing_vars_paths:
            raise UnresolvedPathsError(missing_var_paths=missing_vars_paths)
        self.calls = ok_calls
        return self

    def dump_to_dict(self) -> dict:
        return {
            "calls": [call.model_dump(exclude_defaults=True, exclude_unset=True) for call in self.calls],
        }


@lru_cache
def _public_private_key() -> tuple[str, str]:
    public_key = os.environ.get("MONGODB_ATLAS_PUBLIC_KEY")
    private_key = os.environ.get("MONGODB_ATLAS_PRIVATE_KEY")
    if not public_key or not private_key:
        raise ValueError("MONGODB_ATLAS_PUBLIC_KEY and MONGODB_ATLAS_PRIVATE_KEY must be set in environment variables.")
    return public_key, private_key


class APICallError(Exception):
    def __init__(self, api_call: ApiCall, json_response: dict, error: requests.exceptions.HTTPError):
        self.api_call = api_call
        self.json_response = json_response
        super().__init__(f"Failed to make API call {api_call}:\njson={json_response}\n{error}")

    @property
    def error_code(self) -> str:
        return self.json_response.get("errorCode", "")


def call_api(api_call: ApiCall, path_variables: dict[str, str]) -> dict:
    resolved_path = api_call.path_with_variables(path_variables)
    response = requests.get(
        f"https://cloud-dev.mongodb.com/{resolved_path.lstrip('/')}",
        params=api_call.query_args,
        headers={"Accept": api_call.accept_header, "Content-Type": "application/json"},
        auth=HTTPDigestAuth(*_public_private_key()),
        timeout=30,
    )
    try:
        response_json = response.json()
    except requests.exceptions.JSONDecodeError as e:
        logger.error(f"Failed to parse_json {api_call}: {e}")
        response_json = {}
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise APICallError(api_call, response_json, e) from e
    return response_json


class NoSelfLinkError(Exception):
    def __init__(self, json_response: dict) -> None:
        self.json_response = json_response
        super().__init__("No self link found in response")


def parse_href_response(json_response: dict) -> str:
    for ref in json_response.get("links", []):
        if ref.get("rel") == "self":
            return ref.get("href")
    raise NoSelfLinkError(json_response)


def api_config(
    config_path_str: str = typer.Option("", "-p", "--path", help="Path to the API config file"),
    query_args_str: str = typer.Option(
        '{"pageNum": "0", "itemsPerPage": "0"}', "-q", "--query-args", help="Query arguments for the API call"
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose output"),
):
    query_args: dict[str, str] = json.loads(query_args_str)
    if config_path_str == "":
        with new_task("Find API Calls that use pagination"):
            config_path = dump_config_path(query_args)
    else:
        config_path = Path(config_path_str)
    assert config_path.exists(), f"Config file {config_path} does not exist."
    model = parse_model(config_path, t=ApiCalls)
    total_calls = len(model.calls)
    assert _public_private_key(), "Public and private keys must be set in environment variables."
    path_variables = model.path_variables
    op_id_path_self_qstring: dict[tuple[str, str], str] = {}
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
        except APICallError as e:
            if e.error_code in ALLOWED_ERROR_CODES:
                logger.info(f"Allowed error code {e.error_code} in response for {api_call}")
                model.ignored_calls.append(api_call)
                continue
            raise
        except Exception as e:
            logger.error(e)
            continue
        try:
            href = parse_href_response(result)
            op_id_path_self_qstring[(api_call.operation_id, api_call.path)] = href.split("?")[-1]
        except NoSelfLinkError as e:
            logger.error(f"{api_call} did not have a self link in the response:\n{e.json_response}")
            continue
        logger.info(f"API call {api_call} completed successfully with self ref:\n{href}")
        if verbose:
            logger.info(f"Response for {api_call.query_args} was:\n{dump(result, 'pretty_json')}")
    query_args_str = "&".join(f"{key}={value}" for key, value in query_args.items())
    md_report: list[str] = [
        f"# Pagination Report for query_args='{query_args_str}'",
        "",
        "## Checked endpoints",
        "",
        "Operation ID | Path | SelfQueryString",
        "--- | --- | ---",
        *[
            f"{operation_id} | {path} | {self_query_string}"
            for (operation_id, path), self_query_string in op_id_path_self_qstring.items()
        ],
        "",
        "## Ignored endpoints (not checked)",
        "",
        "Operation ID | Path",
        "--- | ---",
        *[f"{call.operation_id} | {call.path}" for call in model.ignored_calls],
    ]
    md_content = "\n".join(md_report)
    md = Markdown(md_content)
    print_to_live(md)
    output_path = TfDepSettings.from_env().pagination_output_path(query_args_str)
    ensure_parents_write_text(output_path, md_content)
    logger.info(f"Pagination report saved to {output_path}")
    return md


def api(
    path: str = typer.Option("-p", "--path", help="Path to the API endpoint"),
    query_string: str = typer.Option("", "-q", "--query-string", help="Query string for the API call"),
):
    assert path, "Path must be provided."
    accept_header = "application/vnd.atlas.2023-01-01+json"
    url = f"https://cloud-dev.mongodb.com/{path.lstrip('/')}?{query_string}"
    logger.info(f"Calling {url}")
    try:
        r = requests.get(
            url,
            headers={"Accept": accept_header, "Content-Type": "application/json"},
            auth=HTTPDigestAuth(*_public_private_key()),
            timeout=30,
        )
        print(r.text)
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(e)
        print(e.response)


def dump_config_path(query_args: dict[str, str]) -> Path:
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
                            query_args=query_args,
                            accept_header=f"application/vnd.atlas.{version}+json",
                            operation_id=get_method["operationId"],
                        )
                    )
    config_path = settings.api_calls_path
    calls = ApiCalls(
        calls=paginated_paths,
        skip_validation=True,
    )
    calls_yaml = dump(calls.dump_to_dict(), "yaml")
    logger.info(f"Dumped {len(paginated_paths)} API calls to {config_path}")
    ensure_parents_write_text(config_path, calls_yaml)
    return config_path
