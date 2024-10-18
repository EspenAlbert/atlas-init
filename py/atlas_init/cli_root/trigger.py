import logging

import requests
from zero_3rdparty.id_creator import simple_id

from atlas_init.settings.env_vars import init_settings
from atlas_init.settings.path import dump_vscode_dotenv
from atlas_init.typer_app import app_command

logger = logging.getLogger(__name__)


@app_command()
def trigger_app():
    settings = init_settings()
    login_req = {
        "username": settings.MONGODB_ATLAS_PUBLIC_KEY,
        "apiKey": settings.MONGODB_ATLAS_PRIVATE_KEY,
    }
    response = requests.post(
        "https://realm-dev.mongodb.com/api/admin/v3.0/auth/providers/mongodb-cloud/login",
        json=login_req,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    token_response = response.json()
    access_token = token_response["access_token"]
    logger.info(f"token: {access_token}")
    auth_headers = {"Authorization": f"Bearer {access_token}"}
    env_vars = settings.load_env_vars_generated()
    project_id = env_vars["MONGODB_ATLAS_PROJECT_ID"]
    cluster_name = env_vars["MONGODB_ATLAS_CLUSTER_NAME"]
    apps = list_apps(auth_headers, project_id)
    if apps:
        logger.info(f"got apps: {apps}")
        app_id = apps[0]["_id"]
    else:
        logger.info("no apps found, creating one")
        app = create_app(auth_headers, project_id, cluster_name)
        logger.info(f"created app: {app}")
        app_id = app["_id"]
    logger.info(f"using app_id: {app_id}")
    suffix = simple_id(length=5)
    service = create_service(auth_headers, project_id, cluster_name, app_id, suffix)
    logger.info(f"new service: {service}")
    service_id = service["_id"]
    logger.info(f"using service_id: {service_id}")
    func_response = create_function(auth_headers, project_id, app_id, suffix)
    logger.info(f"new function: {func_response}")
    func_id = func_response["_id"]
    logger.info(f"using func_id: {func_id}")
    extra_env_vars = {
        "MONGODB_REALM_APP_ID": app_id,
        "MONGODB_REALM_SERVICE_ID": service_id,
        "MONGODB_REALM_FUNCTION_ID": func_id,
        "MONGODB_REALM_BASE_URL": "https://realm-dev.mongodb.com/",
    }
    dump_vscode_dotenv(settings.env_vars_generated, settings.env_vars_vs_code, **extra_env_vars)
    logger.info(f"done {settings.env_vars_vs_code} updated with trigger env-vars ✅")


def list_apps(auth_headers: dict[str, str], project_id: str) -> list[dict]:
    existing_apps_response = requests.get(
        f"https://realm-dev.mongodb.com/api/admin/v3.0/groups/{project_id}/apps",
        headers=auth_headers,
        timeout=10,
    )
    existing_apps_response.raise_for_status()
    apps = existing_apps_response.json()
    assert isinstance(apps, list), f"expected list, got: {apps!r}"
    return apps


def create_app(auth_headers: dict[str, str], project_id: str, cluster_name: str) -> dict:
    create_app_req = {
        "name": "atlas-init-app",
        "location": "US-VA",
        "deployment_model": "GLOBAL",
        "environment": "production",
        "provider_region": "aws-us-east-1",
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
    create_app_response = requests.post(
        f"https://realm-dev.mongodb.com/api/admin/v3.0/groups/{project_id}/apps",
        json=create_app_req,
        headers=auth_headers,
        timeout=10,
    )
    create_app_response.raise_for_status()
    app = create_app_response.json()
    assert isinstance(app, dict), f"expected dict, got: {app!r}"
    return app


def create_service(auth_headers: dict[str, str], project_id: str, cluster_name: str, app_id: str, suffix: str) -> dict:
    create_service_req = {
        "name": f"atlas-init-{suffix}",
        "type": "mongodb-atlas",
        "config": {
            "clusterName": cluster_name,
            "readPreference": "primary",
            "wireProtocolEnabled": True,
        },
    }
    create_service_response = requests.post(
        f"https://realm-dev.mongodb.com/api/admin/v3.0/groups/{project_id}/apps/{app_id}/services",
        json=create_service_req,
        headers=auth_headers,
        timeout=10,
    )
    create_service_response.raise_for_status()
    service = create_service_response.json()
    assert isinstance(service, dict), f"expected dict, got: {service}"
    return service


def create_function(auth_headers: dict[str, str], project_id: str, app_id: str, suffix: str) -> dict:
    create_func_req = {
        "can_evaluate": {},
        "name": f"testfunc-{suffix}",
        "private": True,
        "source": 'exports = function(changeEvent) {console.log("New Document Inserted")};',
        "run_as_system": True,
    }
    create_func_response = requests.post(
        f"https://realm-dev.mongodb.com/api/admin/v3.0/groups/{project_id}/apps/{app_id}/functions",
        json=create_func_req,
        headers=auth_headers,
        timeout=10,
    )
    create_func_response.raise_for_status()
    func = create_func_response.json()
    assert isinstance(func, dict), f"expected dict, got: {func}"
    return func
