import json
import logging

from atlas_init.cli_tf.debug_logs import SDKRoundtrip, parsed
from atlas_init.cli_tf.debug_logs_test_data import RTModifier

logger = logging.getLogger(__name__)


def add_label_tags(rt: SDKRoundtrip):
    logger.info(f"Adding labels and tags to {rt.id}")
    request = rt.request
    req_dict, req_list, req_bool = parsed(request.text)
    response = rt.response
    resp_dict, resp_list, req_bool = parsed(response.text)
    if resp_list or req_list or req_bool is not None:
        return
    resp_dict = resp_dict or {}
    req_dict = req_dict or {}
    for extra_field in ["labels", "tags"]:
        if extra_field not in resp_dict:
            resp_dict[extra_field] = []
        if extra_field not in req_dict:
            req_dict[extra_field] = []
    request.text = json.dumps(req_dict, indent=1, sort_keys=True)
    response.text = json.dumps(resp_dict, indent=1, sort_keys=True)


cluster_modifier = RTModifier(
    version="2024-08-05",
    method="POST",
    path="/api/atlas/v2/groups/{groupId}/clusters",
    modification=add_label_tags,
)


def package_modifiers(pkg_name: str) -> list[RTModifier]:
    # sourcery skip: assign-if-exp, reintroduce-else
    if pkg_name == "advancedcluster":
        return [cluster_modifier]
    return []


def package_skip_suffixes(pkg_name: str) -> list[str]:
    # sourcery skip: assign-if-exp, reintroduce-else
    if pkg_name == "resourcepolicy":
        return [":validate"]
    return []


def package_must_substrings(pkg_name: str) -> list[str]:
    # sourcery skip: assign-if-exp, reintroduce-else
    if pkg_name == "advancedcluster":
        return ["/clusters"]
    return []
