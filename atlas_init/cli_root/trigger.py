import logging

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from zero_3rdparty.id_creator import simple_id

from atlas_init.settings.env_vars import env_vars_cls_or_none, init_settings
from atlas_init.settings.env_vars_generated import (
    AtlasSettingsWithProject,
    AWSSettings,
    RealmSettings,
)
from atlas_init.settings.env_vars_modules import TFModuleCluster
from atlas_init.settings.path import dump_dotenv
from atlas_init.typer_app import app_command

logger = logging.getLogger(__name__)


@app_command()
def trigger_app():
    create_realm_app()


def create_realm_app():
    settings = init_settings(AtlasSettingsWithProject, TFModuleCluster, AWSSettings)
    atlas_settings = AtlasSettingsWithProject.from_env()
    cluster_settings = TFModuleCluster.from_env()
    aws_settings = AWSSettings.from_env()
    project_id = atlas_settings.MONGODB_ATLAS_PROJECT_ID
    base_url = atlas_settings.realm_url
    cluster_name = cluster_settings.MONGODB_ATLAS_CLUSTER_NAME
    auth_headers = login_to_realm(settings, base_url)
    realm_settings = env_vars_cls_or_none(RealmSettings, dotenv_path=settings.env_vars_trigger)
    if realm_settings and function_exists(
        base_url,
        auth_headers,
        project_id,
        realm_settings.MONGODB_REALM_APP_ID,
        realm_settings.MONGODB_REALM_FUNCTION_ID,
    ):
        logger.info(f"function {realm_settings.MONGODB_REALM_FUNCTION_NAME} already exists ✅")
        settings.include_extra_env_vars_in_vscode(realm_settings.model_dump())
        return
    logger.info("creating new realm app")
    if apps := list_apps(base_url, auth_headers, project_id):
        logger.info(f"got apps: {apps}")
        app_id = apps[0]["_id"]
    else:
        logger.info("no apps found, creating one")
        app = create_app(base_url, auth_headers, project_id, cluster_name, aws_settings.AWS_REGION)
        logger.info(f"created app: {app}")
        app_id = app["_id"]
    logger.info(f"using app_id: {app_id}")
    suffix = simple_id(length=5)
    service = create_service(base_url, auth_headers, project_id, cluster_name, app_id, suffix)
    logger.info(f"new service: {service}")
    service_id = service["_id"]
    logger.info(f"using service_id: {service_id}")
    func_response = create_function(base_url, auth_headers, project_id, app_id, suffix)
    logger.info(f"new function: {func_response}")
    func_id = func_response["_id"]
    func_name = func_response["name"]
    logger.info(f"using func_id: {func_id}")
    realm_settings = RealmSettings(
        MONGODB_REALM_APP_ID=app_id,
        MONGODB_REALM_SERVICE_ID=service_id,
        MONGODB_REALM_FUNCTION_ID=func_id,
        MONGODB_REALM_FUNCTION_NAME=func_name,
        MONGODB_REALM_BASE_URL=base_url,
    )
    extra_env_vars = realm_settings.model_dump()
    dump_dotenv(settings.env_vars_trigger, extra_env_vars)
    logger.info(f"done {settings.env_vars_trigger} created with trigger env-vars ✅")
    settings.include_extra_env_vars_in_vscode(extra_env_vars)


def login_to_realm(settings, base_url):
    login_req = {
        "username": settings.MONGODB_ATLAS_PUBLIC_KEY,
        "apiKey": settings.MONGODB_ATLAS_PRIVATE_KEY,
    }
    token_response = _request_post_call(
        f"{base_url}api/admin/v3.0/auth/providers/mongodb-cloud/login",
        data=login_req,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=10,
    )
    access_token = token_response["access_token"]
    logger.debug(f"token: {access_token}")
    return {"Authorization": f"Bearer {access_token}"}


def list_apps(base_url: str, auth_headers: dict[str, str], project_id: str) -> list[dict]:
    existing_apps_response = requests.get(
        f"{base_url}api/admin/v3.0/groups/{project_id}/apps",
        headers=auth_headers,
        timeout=10,
    )
    existing_apps_response.raise_for_status()
    apps = existing_apps_response.json()
    assert isinstance(apps, list), f"expected list, got: {apps!r}"
    return apps


# https://www.mongodb.com/docs/atlas/app-services/apps/deployment-models-and-regions/#cloud-deployment-regions
_cloud_deployment_regions = {
    "aws-eu-west-1": "IE",
    "aws-us-west-2": "US-OR",
    "aws-ap-southeast-2": "AU",
    "aws-us-east-1": "US-VA",
}


def create_app(
    base_url: str,
    auth_headers: dict[str, str],
    project_id: str,
    cluster_name: str,
    aws_region: str,
) -> dict:
    provider_region = f"aws-{aws_region}"
    location = _cloud_deployment_regions.get(provider_region)
    if not location:
        raise ValueError(
            f"unknown location for provider_region: {provider_region}, only supports: {_cloud_deployment_regions}"
        )
    create_app_req = {
        "name": "atlas-init-app",
        "location": location,
        "deployment_model": "GLOBAL",
        "environment": "production",
        "provider_region": provider_region,
        "data_source": {
            "name": "mongodb-atlas",
            "type": "mongodb-atlas",
            "config": {
                "clusterName": cluster_name,
                "readPreference": "primary",
                "wireProtocolEnabled": True,
            },
        },
    }
    app_response = _request_post_call(
        f"{base_url}api/admin/v3.0/groups/{project_id}/apps",
        data=create_app_req,
        headers=auth_headers,
        timeout=10,
        log_data_on_failure=True,
    )
    assert isinstance(app_response, dict), f"expected dict, got: {app_response!r}"
    return app_response


def create_service(
    base_url: str,
    auth_headers: dict[str, str],
    project_id: str,
    cluster_name: str,
    app_id: str,
    suffix: str,
) -> dict:
    create_service_req = {
        "name": f"atlas-init-{suffix}",
        "type": "mongodb-atlas",
        "config": {
            "clusterName": cluster_name,
            "readPreference": "primary",
            "wireProtocolEnabled": True,
        },
    }
    service = _request_post_call(
        f"{base_url}api/admin/v3.0/groups/{project_id}/apps/{app_id}/services",
        data=create_service_req,
        headers=auth_headers,
        timeout=10,
        log_data_on_failure=True,
    )
    assert isinstance(service, dict), f"expected dict, got: {service}"
    return service


def create_function(
    base_url: str,
    auth_headers: dict[str, str],
    project_id: str,
    app_id: str,
    suffix: str,
) -> dict:
    create_func_req = {
        "can_evaluate": {},
        "name": f"testfunc-{suffix}",
        "private": True,
        "source": 'exports = function(changeEvent) {console.log("New Document Inserted")};',
        "run_as_system": True,
    }
    func = _request_post_call(
        f"{base_url}api/admin/v3.0/groups/{project_id}/apps/{app_id}/functions",
        data=create_func_req,
        headers=auth_headers,
        timeout=10,
        log_data_on_failure=True,
    )
    assert isinstance(func, dict), f"expected dict, got: {func}"
    return func


def function_exists(
    base_url: str,
    auth_headers: dict[str, str],
    project_id: str,
    app_id: str,
    func_id: str,
) -> bool:
    # https://services.cloud.mongodb.com/api/admin/v3.0/groups/{groupId}/apps/{appId}/functions/{functionId}
    get_func_response = requests.get(
        f"{base_url}api/admin/v3.0/groups/{project_id}/apps/{app_id}/functions/{func_id}",
        headers=auth_headers,
        timeout=10,
    )
    if get_func_response.status_code == 404:  # noqa: PLR2004
        return False
    get_func_response.raise_for_status()
    func = get_func_response.json()
    assert isinstance(func, dict), f"expected dict response, got: {func}"
    return True


class _RetryPostRequestError(Exception):
    pass


@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(10),
    retry=retry_if_exception_type(),
    reraise=True,
)
def _request_post_call(
    url: str,
    data: dict,
    headers: dict[str, str],
    timeout: int,
    *,
    log_data_on_failure: bool = False,
) -> dict:
    response = requests.post(url, json=data, headers=headers, timeout=timeout)
    if response.status_code >= 500:  # noqa: PLR2004
        logger.warning(f"failed to post to {url}, status_code: {response.status_code}, response: {response.text}")
        if log_data_on_failure:
            logger.warning(f"data: {data}")
        raise _RetryPostRequestError(f"status_code: {response.status_code}, response: {response.text}")
    response.raise_for_status()
    return response.json()
