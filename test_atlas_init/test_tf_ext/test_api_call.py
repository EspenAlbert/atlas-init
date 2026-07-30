import logging
import requests
from requests.auth import HTTPDigestAuth
from atlas_init.tf_ext.api_call import ApiCall, APICallError
from functools import lru_cache
import os

logger = logging.getLogger(__name__)


@lru_cache
def _public_private_key() -> tuple[str, str, str]:
    public_key = os.environ.get("MONGODB_ATLAS_PUBLIC_KEY")
    private_key = os.environ.get("MONGODB_ATLAS_PRIVATE_KEY")
    base_url = os.environ.get("MONGODB_ATLAS_BASE_URL", "https://cloud-dev.mongodb.com")
    if not public_key or not private_key:
        raise ValueError("MONGODB_ATLAS_PUBLIC_KEY and MONGODB_ATLAS_PRIVATE_KEY must be set in environment variables.")
    return base_url, public_key, private_key


def call_api(api_call: ApiCall, path_variables: dict[str, str], data: dict | list, method: str = "GET") -> dict:
    resolved_path = api_call.path_with_variables(path_variables)
    base_url, public_key, private_key = _public_private_key()
    digest_auth = HTTPDigestAuth(public_key, private_key)
    url = f"{base_url.rstrip('/')}/{resolved_path.lstrip('/')}"
    logger.info(f"Calling {url} with {data}, public_key: {public_key}")
    response = requests.request(
        method,
        url,
        params=api_call.query_args,
        # "Accept": "application/json" might be a better header for private endpoints.
        headers={"Accept": api_call.accept_header, "Content-Type": "application/json"},
        auth=digest_auth,
        timeout=30,
        json=data,
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


def test_api_call():
    call = ApiCall(
        operation_id="advanced_configuration",
        path="/api/atlas/v2/groups/{groupId}/clusters/{clusterName}/processArgs",
        accept_header="application/vnd.atlas.2024-08-05+json",
    )
    response = call_api(
        call,
        {"groupId": "664619d870c247237f4b86a6", "clusterName": "HELP-90015-oplog-repro"},
        {"oplogMinRetentionHours": None},
    )
    logger.info(f"Response: {response}")


def test_api_encryption_privatelink_delete():
    call = ApiCall(
        operation_id="requestPrivateEndpointDeletion",
        path="/api/atlas/v2/groups/{groupId}/encryptionAtRest/{cloudProvider}/privateEndpoints/{endpointId}",
        accept_header="application/vnd.atlas.2024-08-05+json",
    )
    response = call_api(
        call,
        {"groupId": "664619d870c247237f4b86a6", "cloudProvider": "AWS", "endpointId": "69d385a0d6fb09b90f0c9077"},
        {},
        method="DELETE",
    )
    logger.info(f"Response: {response}")
