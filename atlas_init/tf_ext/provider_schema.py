import os
from pathlib import Path
from tempfile import TemporaryDirectory

from ask_shell import run_and_wait
from model_lib import Entity

from atlas_init.tf_ext.args import TF_CLI_CONFIG_FILE_ENV_NAME
from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME


def parse_provider_resource_schema(schema: dict, provider_name: str) -> dict:
    schemas = schema.get("provider_schemas", {})
    for provider_url, provider_schema in schemas.items():
        if provider_url.endswith(provider_name):
            return provider_schema.get("resource_schemas", {})
    raise ValueError(f"Provider '{provider_name}' not found in schema.")


class AtlasSchemaInfo(Entity):
    resource_types: list[str]
    deprecated_resource_types: list[str]
    raw_resource_schema: dict[str, dict]


_providers_tf = """
terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "~> 1.26" # irrelevant
    }
  }
  required_version = ">= 1.8"
}

"""


def parse_atlas_schema() -> AtlasSchemaInfo:
    assert os.environ.get(TF_CLI_CONFIG_FILE_ENV_NAME), f"{TF_CLI_CONFIG_FILE_ENV_NAME} is required"
    with TemporaryDirectory() as example_dir:
        tmp_path = Path(example_dir)
        providers_tf = tmp_path / "providers.tf"
        providers_tf.write_text(_providers_tf)
        run_and_wait("terraform init", cwd=example_dir)
        schema_run = run_and_wait(
            "terraform providers schema -json",
            cwd=example_dir,
            ansi_content=False,
            env={"MONGODB_ATLAS_PREVIEW_PROVIDER_V2_ADVANCED_CLUSTER": "false"},
        )
    parsed = schema_run.parse_output(dict, output_format="json")
    resource_schema = parse_provider_resource_schema(parsed, ATLAS_PROVIDER_NAME)

    def is_deprecated(resource_details: dict) -> bool:
        return resource_details["block"].get("deprecated", False)

    deprecated_resource_types = [name for name, details in resource_schema.items() if is_deprecated(details)]
    return AtlasSchemaInfo(
        resource_types=sorted(resource_schema.keys()),
        deprecated_resource_types=sorted(deprecated_resource_types),
        raw_resource_schema=resource_schema,
    )
