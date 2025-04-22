import logging
import os
from pathlib import Path
from typing import Any

from model_lib import Entity, dump, parse_model
from mypy_boto3_cloudformation.type_defs import ParameterTypeDef
from pydantic import ConfigDict, Field
from rich import prompt
from zero_3rdparty.file_utils import clean_dir
from zero_3rdparty.dict_nested import iter_nested_key_values, update

from atlas_init.cli_cfn.files import create_sample_file, default_log_group_name
from atlas_init.cloud.aws import PascalAlias
from atlas_init.repos.cfn import CfnType, cfn_examples_dir, cfn_type_normalized

logger = logging.getLogger(__name__)
UNKNOWN_PLACEHOLDER = "UNKNOWN"


class TemplatePathNotFoundError(Exception):
    def __init__(self, type_name: str, examples_dir: Path) -> None:
        self.type_name = type_name
        self.examples_dir = examples_dir


def infer_template_path(repo_path: Path, type_name: str, stack_name: str, example_name: str = "") -> Path:
    examples_dir = cfn_examples_dir(repo_path)
    template_paths: list[Path] = []
    type_setting = f'"Type": "{type_name}"'
    for p in examples_dir.rglob("*.json"):
        if example_name and example_name != p.stem:
            continue
        if type_setting in p.read_text():
            logger.info(f"found template @ '{p.stem}': {p.parent}")
            template_paths.append(p)
    if not template_paths:
        raise TemplatePathNotFoundError(type_name, examples_dir)
    if len(template_paths) > 1:
        return choose_template_path(type_name, template_paths, stack_name)
    return template_paths[0]


def choose_template_path(type_name: str, template_paths: list[Path], stack_name: str) -> Path:
    expected_folder = cfn_type_normalized(type_name)
    if (expected_folders := [p for p in template_paths if p.parent.name == expected_folder]) and len(
        expected_folders
    ) == 1:
        logger.info(f"using template: {expected_folders[0]}")
        return expected_folders[0]
    choices = {p.stem: p for p in template_paths}
    if stack_path := choices.get(stack_name):
        logger.info(f"using template @ {stack_path} based on stack name: {stack_name}")
        return stack_path
    selected_path = prompt.Prompt("Choose example template: ", choices=list(choices))()
    return choices[selected_path]


parameters_exported_env_vars = {
    "OrgId": "MONGODB_ATLAS_ORG_ID",
    "Profile": "ATLAS_INIT_CFN_PROFILE",
    "KeyId": "MONGODB_ATLAS_ORG_API_KEY_ID",
    "TeamId": "MONGODB_ATLAS_TEAM_ID",
    "ProjectId": "MONGODB_ATLAS_PROJECT_ID",
    "AWSVpcId": "AWS_VPC_ID",
    "MongoDBAtlasProjectId": "MONGODB_ATLAS_PROJECT_ID",
    "AWSSubnetId": "AWS_SUBNET_ID",
    "AWSRegion": "AWS_REGION",
    "AppId": "MONGODB_REALM_APP_ID",
    "FunctionId": "MONGODB_REALM_FUNCTION_ID",
    "FunctionName": "MONGODB_REALM_FUNCTION_NAME",
    "ServiceId": "MONGODB_REALM_SERVICE_ID",
}

STACK_NAME_PARAM = "$STACK_NAME_PARAM$"
type_names_defaults: dict[str, dict[str, str]] = {
    "project": {
        "KeyRoles": "GROUP_OWNER",
        "TeamRoles": "GROUP_OWNER",
        STACK_NAME_PARAM: "Name",
    },
    "cluster": {
        STACK_NAME_PARAM: "ClusterName",
        "ProjectName": "Cluster-CFN-Example",
    },
    "resourcepolicy": {
        STACK_NAME_PARAM: "Name",
        "Policies": 'forbid (principal, action == cloud::Action::"project.edit",resource) when {context.project.ipAccessList.contains(ip("0.0.0.0/0"))};',
    },
    "trigger": {
        STACK_NAME_PARAM: "TriggerName",
    },
}


class CfnParameter(Entity):
    model_config = PascalAlias
    type: str
    description: str = ""
    constraint_description: str = ""
    default: str = ""
    allowed_values: list[str] = Field(default_factory=list)


class CfnResource(Entity):
    model_config = PascalAlias
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class CfnTemplate(Entity):
    model_config = PascalAlias | ConfigDict(extra="allow")
    parameters: dict[str, CfnParameter]
    resources: dict[str, CfnResource]

    @classmethod
    def read_template_types(cls, template_path: Path, prefix: str = CfnType.MONGODB_ATLAS_CFN_TYPE_PREFIX) -> set[str]:
        cfn_template = parse_model(template_path, t=CfnTemplate)
        return {r.type for r in cfn_template.resources.values() if r.type.startswith(prefix)}

    def find_resource(self, type_name: str) -> CfnResource:
        for r in self.resources.values():
            if r.type == type_name:
                return r
        raise ValueError(f"resource not found: {type_name}")

    def normalized_type_name(self, type_name: str) -> str:
        assert self.find_resource(type_name)
        return cfn_type_normalized(type_name)

    def get_resource_properties(self, type_name: str, parameters: list[ParameterTypeDef]) -> dict:
        resource = self.find_resource(type_name)
        properties = resource.properties
        for param in parameters:
            key = param.get("ParameterKey")
            assert key
            if key not in properties:
                key_found = next(
                    (
                        maybe_key
                        for maybe_key, value in properties.items()
                        if isinstance(value, dict) and value.get("Ref") == key
                    ),
                    None,
                )
                err_msg = f"unable to find parameter {key} in resource {type_name}, can happen if there are template parameters not used for {type_name}"
                if key_found is None:
                    logger.warning(err_msg)
                    continue
                key = key_found
            param_value = param.get("ParameterValue", "")
            assert param_value
            properties[key] = param_value
        return properties


class CfnTemplateUnknownParametersError(Exception):
    def __init__(self, unknown_params: list[str]) -> None:
        self.unknown_params = unknown_params


def infer_template_parameters(
    path: Path, type_name: str, stack_name: str, explicit_params: dict[str, Any]
) -> list[ParameterTypeDef]:
    cfn_template = parse_model(path, t=CfnTemplate)
    parameters_dict: dict[str, Any] = {key: UNKNOWN_PLACEHOLDER for key in cfn_template.parameters.keys()}
    type_defaults = type_names_defaults.get(cfn_template.normalized_type_name(type_name), {})
    if stack_name_param := type_defaults.pop(STACK_NAME_PARAM, None):
        type_defaults[stack_name_param] = stack_name
    for param_name, param in cfn_template.parameters.items():
        explicit_value = explicit_params.get(param_name)
        if explicit_value is not None:
            logger.info(f"using explicit value for {param_name}={explicit_value}")
            parameters_dict[param_name] = explicit_value
            continue
        if type_default := type_defaults.get(param_name):
            logger.info(f"using type default for {param_name}={type_default}")
            parameters_dict[param_name] = type_default
            continue
        if env_key := parameters_exported_env_vars.get(param_name):
            if env_value := os.environ.get(env_key):
                logger.info(f"using {env_key} to fill parameter: {param_name}")
                parameters_dict[param_name] = env_value
                continue
        if set(param.allowed_values) == {"true", "false"}:
            logger.info(f"using default false for {param_name}")
            parameters_dict[param_name] = "false"
            continue
        if default := param.default:
            logger.info(f"using default for {param_name}={default}")
            parameters_dict[param_name] = default
            continue
    if unknown_params := {key for key, value in parameters_dict.items() if value == UNKNOWN_PLACEHOLDER}:
        raise CfnTemplateUnknownParametersError(sorted(unknown_params))
    return [{"ParameterKey": key, "ParameterValue": value} for key, value in parameters_dict.items()]


def dump_resource_to_file(
    inputs_dir: Path,
    template_path: Path,
    type_name: str,
    parameters: list[ParameterTypeDef],
) -> Path:
    cfn_template = parse_model(template_path, t=CfnTemplate)
    properties = cfn_template.get_resource_properties(type_name, parameters)
    clean_dir(inputs_dir, recreate=True)
    dest_path = inputs_dir / "inputs_1_create.json"
    dest_json = dump(properties, "pretty_json")
    dest_path.write_text(dest_json)
    return dest_path


def dump_sample_file(
    samples_dir: Path,
    template_path: Path,
    type_name: str,
    parameters: list[ParameterTypeDef],
):
    cfn_template = parse_model(template_path, t=CfnTemplate)
    samples_path = samples_dir / template_path.stem / "create.json"
    create_sample_file(
        samples_path,
        default_log_group_name(CfnType.resource_name(type_name)),
        cfn_template.get_resource_properties(type_name, parameters),
        prev_resource_state={},
    )
    return samples_path


def modify_resource_with_params(resource: CfnResource, resource_params: dict[str, Any]) -> None:
    updates: dict[str, tuple[str, Any]] = {}
    resource_properties = resource.properties
    for path, value in iter_nested_key_values(resource_properties, include_list_indexes=True):
        if not isinstance(value, dict):
            continue
        if "Ref" not in value:
            continue
        param_name = value["Ref"]
        assert isinstance(param_name, str), f"Ref must be a string, {path}, got={param_name!r}"
        if param_value := resource_params.get(param_name):
            updates[param_name] = (path, param_value)
        else:
            logger.warning(f"unable to find parameter {param_name} in resource params, path={path}")

    for param_name, param_value in resource_params.items():
        if update_path_value := updates.get(param_name):
            update(resource_properties, *update_path_value)
        else:
            logger.warning(f"No ref found for {param_name} assumming top level on resource")
            resource_properties[param_name] = param_value
