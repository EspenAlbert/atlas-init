import logging
from pathlib import Path
from typing import Any

from model_lib import Entity, parse_model, parse_payload
from mypy_boto3_cloudformation.type_defs import ParameterTypeDef
from pydantic import Field
from zero_3rdparty.dict_nested import read_nested

from atlas_init.cli_args import cfn_type_normalized
from atlas_init.constants import PascalAlias, cfn_examples_dir
from atlas_init.env_vars import TF_DIR

logger = logging.getLogger(__name__)


def check_execution_role(repo_path: Path, loaded_env_vars: dict[str, str]) -> str:
    execution_role = cfn_examples_dir(repo_path) / "execution-role.yaml"
    execution_raw = parse_payload(execution_role)
    actions_expected = read_nested(
        execution_raw,
        "Resources.ExecutionRole.Properties.Policies.[0].PolicyDocument.Statement.[0].Action",
    )
    actions_found = parse_payload(TF_DIR / "modules/cfn/resource_actions.yaml")
    if diff := set(actions_expected) ^ set(actions_found):
        raise ValueError(f"non-matching execution role actions: {sorted(diff)}")
    services_found = parse_payload(TF_DIR / "modules/cfn/assume_role_services.yaml")
    services_expected = read_nested(
        execution_raw,
        "Resources.ExecutionRole.Properties.AssumeRolePolicyDocument.Statement.[0].Principal.Service",
    )
    if diff := set(services_found) ^ set(services_expected):
        raise ValueError(f"non-matching execution role services: {sorted(diff)}")
    logger.info(f"execution role is up to date with {execution_role}")
    return loaded_env_vars["CFN_EXAMPLE_EXECUTION_ROLE"]


def infer_template_path(repo_path: Path, type_name: str) -> Path:
    examples_dir = cfn_examples_dir(repo_path)
    template_paths: list[Path] = []
    type_setting = f'"Type": "{type_name}"'
    for p in examples_dir.rglob("*.json"):
        if type_setting in p.read_text():
            logger.info(f"found template @ {p}")
            template_paths.append(p)
    if not template_paths:
        raise Exception(f"failed to find template for {type_name} in {examples_dir}")
    if len(template_paths) > 1:
        expected_folder = cfn_type_normalized(type_name)
        if expected_folders := [
            p for p in template_paths if p.parent.name == expected_folder
        ]:
            if len(expected_folders) == 1:
                logger.info(f"using template: {expected_folders[0]}")
                return expected_folders[0]
        raise Exception(
            f"multiple templates for {type_name} in {examples_dir}: {template_paths}"
        )
    return template_paths[0]


parameters_exported_env_vars = {
    "OrgId": "MONGODB_ATLAS_ORG_ID",
    "Profile": "ATLAS_INIT_CFN_PROFILE",
    "KeyId": "MONGODB_ATLAS_ORG_API_KEY_ID",
    "TeamId": "MONGODB_ATLAS_TEAM_ID",
}

STACK_NAME_PARAM = "$STACK_NAME_PARAM$"
type_names_defaults: dict[str, dict[str, str]] = {
    "project": {
        "KeyRoles": "GROUP_OWNER",
        "TeamRoles": "GROUP_OWNER",
        STACK_NAME_PARAM: "Name",
    }
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


class CfnTemplate(Entity):
    model_config = PascalAlias
    parameters: dict[str, CfnParameter]
    resources: dict[str, CfnResource]

    def normalized_type_name(self) -> str:
        key = list(self.resources)[0]
        return cfn_type_normalized(self.resources[key].type)


def decode_parameters(
    exported_env_vars: dict[str, str],
    template_path: Path,
    stack_name: str,
    force_params: dict[str, Any] | None = None,
) -> tuple[list[ParameterTypeDef], set[str]]:
    cfn_template = parse_model(template_path, t=CfnTemplate)
    parameters_dict: dict[str, Any] = {}
    type_defaults = type_names_defaults.get(cfn_template.normalized_type_name(), {})
    if stack_name_param := type_defaults.pop(STACK_NAME_PARAM, None):
        type_defaults[stack_name_param] = stack_name

    for param_name, param in cfn_template.parameters.items():
        if env_key := parameters_exported_env_vars.get(param_name):
            if env_value := exported_env_vars.get(env_key):
                logger.info(f"using {env_key} to fill parameter: {param_name}")
                parameters_dict[param_name] = env_value
                continue
        if set(param.allowed_values) == {"true", "false"}:
            logger.info(f"using default false for {param_name}")
            parameters_dict[param_name] = "false"
            continue
        if default := param.default:
            parameters_dict[param_name] = default
            continue
        if type_default := type_defaults.get(param_name):
            logger.info(f"using type default for {param_name}={type_default}")
            parameters_dict[param_name] = type_default
            continue
        logger.warning(f"unable to auto-filll param: {param_name}")
        parameters_dict[param_name] = "UNKNOWN"

    if force_params:
        logger.warning(f"overiding params: {force_params} for {stack_name}")
        parameters_dict.update(force_params)
    unknown_params = {
        key for key, value in parameters_dict.items() if value == "UNKNOWN"
    }
    parameters: list[ParameterTypeDef] = [
        {"ParameterKey": key, "ParameterValue": value}
        for key, value in parameters_dict.items()
    ]
    return parameters, unknown_params
