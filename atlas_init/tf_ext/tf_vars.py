from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar, NamedTuple

from ask_shell import new_task, run_and_wait
from model_lib import IgnoreFalsy, dump
from pydantic import Field, RootModel
from zero_3rdparty.file_utils import ensure_parents_write_text
from zero_3rdparty.str_utils import instance_repr

from atlas_init.tf_ext.args import REPO_PATH_ARG, SKIP_EXAMPLES_DIRS_OPTION
from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.paths import (
    ResourceTypes,
    find_resource_types_with_usages,
    find_variables,
    get_example_directories,
    is_variable_name_external,
)
from atlas_init.tf_ext.settings import TfDepSettings

logger = logging.getLogger(__name__)


def tf_vars(
    repo_path: Path = REPO_PATH_ARG,
    skip_names: list[str] = SKIP_EXAMPLES_DIRS_OPTION,
):
    settings = TfDepSettings.from_env()
    logger.info(f"Analyzing Terraform variables in repository: {repo_path}")
    example_dirs = get_example_directories(repo_path, skip_names)
    assert example_dirs, "No example directories found. Please check the repository path and skip names."
    with new_task("Parsing provider schema") as task:
        resource_types, resource_types_deprecated = parse_schema_resource_types(example_dirs[0])
        ensure_parents_write_text(settings.schema_resource_types_path, dump(sorted(resource_types), format="yaml"))
        logger.info(f"Provider schema resource types written to {settings.schema_resource_types_path}")
        ensure_parents_write_text(
            settings.schema_resource_types_deprecated_path, dump(sorted(resource_types_deprecated), format="yaml")
        )
        logger.info(
            f"Provider schema deprecated resource types written to {settings.schema_resource_types_deprecated_path}"
        )
    logger.info(f"Found {len(resource_types)} resource types in the provider schema.: {', '.join(resource_types)}")
    with new_task("Parsing variables from examples") as task:
        update_variables(settings, example_dirs, task)
    with new_task("Parsing resource types from examples", total=len(example_dirs)) as task:
        example_resource_types = update_resource_types(settings, example_dirs, task)
    if missing_example_resource_types := set(resource_types) - set(example_resource_types.root):
        logger.warning(f"Missing resource types in examples:\n{'\n'.join(sorted(missing_example_resource_types))}")


def parse_provider_resurce_schema(schema: dict, provider_name: str) -> dict:
    schemas = schema.get("provider_schemas", {})
    for provider_url, provider_schema in schemas.items():
        if provider_url.endswith(provider_name):
            return provider_schema.get("resource_schemas", {})
    raise ValueError(f"Provider '{provider_name}' not found in schema.")


class TfVarUsage(IgnoreFalsy):
    name: str = Field(..., description="Name of the Terraform variable.")
    descriptions: set[str] = Field(default_factory=set, description="Set of descriptions for the variable.")
    example_paths: list[Path] = Field(
        default_factory=list, description="List of example files where the variable is used."
    )

    PARENT_DIR: ClassVar[str] = "examples"

    def update(self, variable_description: str | None, example_dir: Path):
        if variable_description and variable_description not in self.descriptions:
            self.descriptions.add(variable_description)
        assert f"/{self.PARENT_DIR}/" in str(example_dir), "Example directory must be under 'examples/'"
        if example_dir not in self.example_paths:
            self.example_paths.append(example_dir)

    @property
    def paths_str(self) -> str:
        return ", ".join(str(path).split(self.PARENT_DIR)[1] for path in self.example_paths)

    def __str__(self):
        return instance_repr(self, ["name", "descriptions", "paths_str"])

    def dump_dict_modifier(self, payload: dict) -> dict:
        payload["descriptions"] = sorted(self.descriptions)
        payload["example_paths"] = sorted(self.example_paths)
        return payload


class TfVarsUsage(RootModel[dict[str, TfVarUsage]]):
    def add_variable(self, variable: str, variable_description: str | None, example_dir: Path):
        if variable not in self.root:
            self.root[variable] = TfVarUsage(name=variable, example_paths=[])
        self.root[variable].update(variable_description, example_dir)

    def external_vars(self) -> TfVarsUsage:
        return type(self)(root={name: usage for name, usage in self.root.items() if is_variable_name_external(name)})


def vars_usage_dumping(variables: TfVarsUsage) -> str:
    vars_model = variables.model_dump()
    vars_model = dict(sorted(vars_model.items()))
    return dump(vars_model, format="yaml")


def update_resource_types(settings: TfDepSettings, example_dirs: list[Path], task: new_task) -> ResourceTypes:
    resource_types = ResourceTypes(root={})
    for example_dir in example_dirs:
        example_resources = find_resource_types_with_usages(example_dir)
        for resource_type, usages in example_resources.root.items():
            resource_types.add_resource_type(resource_type, usages.example_files, usages.variable_usage)
        task.update(advance=1)
    logger.info(f"Found {len(resource_types.root)} resource types in the examples.")
    resource_types_yaml = resource_types_dumping(resource_types)
    ensure_parents_write_text(settings.resource_types_file_path, resource_types_yaml)
    logger.info(f"Resource types usage written to {settings.resource_types_file_path}")
    atlas_external_resource_types = resource_types.atlas_resource_type_with_external_var_usages()
    logger.info(f"Found {len(atlas_external_resource_types.root)} Atlas resource types with external variable usages.")
    atlas_external_resource_types_yaml = resource_types_dumping(atlas_external_resource_types, with_external=True)
    ensure_parents_write_text(settings.resource_types_external_file_path, atlas_external_resource_types_yaml)
    logger.info(
        f"Atlas resource types with external variable usages written to {settings.resource_types_external_file_path}"
    )
    return resource_types


def resource_types_dumping(resource_types: ResourceTypes, with_external: bool = False) -> str:
    resource_types_model = resource_types.dump_with_external_vars() if with_external else resource_types.model_dump()
    return dump(dict(sorted(resource_types_model.items())), format="yaml")


def update_variables(settings: TfDepSettings, example_dirs: list[Path], task: new_task):
    variables = parse_all_variables(example_dirs, task)
    logger.info(f"Found {len(variables.root)} variables in the examples.")
    vars_yaml = vars_usage_dumping(variables)
    ensure_parents_write_text(settings.vars_file_path, vars_yaml)
    logger.info(f"Variables usage written to {settings.vars_file_path}")
    external_vars = variables.external_vars()
    if external_vars.root:
        logger.info(f"Found {len(external_vars.root)} external variables: {', '.join(external_vars.root.keys())}")
        external_vars_yaml = vars_usage_dumping(external_vars)
        ensure_parents_write_text(settings.vars_external_file_path, external_vars_yaml)
        logger.info(f"External variables usage written to {settings.vars_external_file_path}")


class ResourceTypesSchema(NamedTuple):
    resource_types: list[str]
    deprecated_resource_types: list[str]


def parse_schema_resource_types(example_dir: Path) -> ResourceTypesSchema:
    schema_run = run_and_wait("terraform providers schema -json", cwd=example_dir, ansi_content=False)
    parsed = schema_run.parse_output(dict, output_format="json")
    resource_schema = parse_provider_resurce_schema(parsed, ATLAS_PROVIDER_NAME)

    def is_deprecated(resource_details: dict) -> bool:
        return resource_details["block"].get("deprecated", False)

    deprecated_resource_types = [name for name, details in resource_schema.items() if is_deprecated(details)]
    return ResourceTypesSchema(sorted(resource_schema.keys()), sorted(deprecated_resource_types))


def parse_all_variables(examples_dirs: list[Path], task: new_task) -> TfVarsUsage:
    variables_usage = TfVarsUsage(root={})
    for example_dir in examples_dirs:
        variables_tf = example_dir / "variables.tf"
        if not variables_tf.exists():
            continue
        for variable, variable_desc in find_variables(variables_tf).items():
            variables_usage.add_variable(variable, variable_desc, example_dir)
        task.update(advance=1)
    return variables_usage
