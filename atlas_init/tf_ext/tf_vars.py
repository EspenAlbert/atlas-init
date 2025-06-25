import logging
from pathlib import Path
from typing import ClassVar

from ask_shell import run_and_wait
from model_lib import IgnoreFalsy, dump
from pydantic import Field, RootModel
from zero_3rdparty.file_utils import ensure_parents_write_text
from zero_3rdparty.str_utils import instance_repr
from atlas_init.tf_ext.args import REPO_PATH_ARG, SKIP_EXAMPLES_DIRS_OPTION
from atlas_init.tf_ext.paths import find_variables, get_example_directories
from atlas_init.tf_ext.settings import TfDepSettings
from atlas_init.tf_ext.tf_dep import ATLAS_PROVIDER_NAME

logger = logging.getLogger(__name__)


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


def tf_vars(
    repo_path: Path = REPO_PATH_ARG,
    skip_names: list[str] = SKIP_EXAMPLES_DIRS_OPTION,
):
    settings = TfDepSettings.from_env()
    logger.info(f"Analyzing Terraform variables in repository: {repo_path}")
    example_dirs = get_example_directories(repo_path, skip_names)
    assert example_dirs, "No example directories found. Please check the repository path and skip names."
    resource_types = parse_schema_resource_types(example_dirs[0])
    logger.info(f"Found {len(resource_types)} resource types in the provider schema.: {', '.join(resource_types)}")
    variables = parse_all_variables(example_dirs)
    logger.info(f"Found {len(variables.root)} variables in the examples.")
    vars_model = variables.model_dump()
    vars_model = dict(sorted(vars_model.items()))
    vars_yaml = dump(vars_model, format="yaml")
    out_path = settings.vars_file_path
    ensure_parents_write_text(out_path, vars_yaml)
    logger.info(f"Variables usage written to {out_path}")


def parse_schema_resource_types(example_dir: Path) -> list[str]:
    schema_run = run_and_wait("terraform providers schema -json", cwd=example_dir, ansi_content=False)
    parsed = schema_run.parse_output(dict, output_format="json")
    resource_schema = parse_provider_resurce_schema(parsed, ATLAS_PROVIDER_NAME)
    return sorted(resource_schema.keys())


def parse_all_variables(examples_dirs: list[Path]) -> TfVarsUsage:
    variables_usage = TfVarsUsage(root={})
    for example_dir in examples_dirs:
        variables_tf = example_dir / "variables.tf"
        if not variables_tf.exists():
            continue
        for variable, variable_desc in find_variables(variables_tf).items():
            variables_usage.add_variable(variable, variable_desc, example_dir)
    return variables_usage
