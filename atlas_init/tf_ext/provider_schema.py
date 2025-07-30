from __future__ import annotations
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from ask_shell import run_and_wait
from model_lib import Entity, dump, parse_dict
from pydantic import BaseModel
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.tf_ext.args import TF_CLI_CONFIG_FILE_ENV_NAME
from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.models_module import ProviderGenConfig
from atlas_init.tf_ext.settings import TfExtSettings


logger = logging.getLogger(__name__)


def parse_provider_resource_schema(schema: dict, provider_name: str) -> dict:
    schemas = schema.get("provider_schemas", {})
    for provider_url, provider_schema in schemas.items():
        if provider_url.endswith(provider_name):
            return provider_schema.get("resource_schemas", {})
    raise ValueError(f"Provider '{provider_name}' not found in schema.")


_providers_tf_with_external = """
terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "~> 1.26"
    }
    external = {
      source  = "hashicorp/external"
      version = "~>2.0"
    }
  }
  required_version = ">= 1.8"
}
"""

_providers_tf = """
terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "~> 1.26"
    }
  }
  required_version = ">= 1.8"
}
"""
_providers_tf_minimal = """
terraform {
  required_version = ">= 1.8"
}
"""


def get_providers_tf(skip_python: bool = True, minimal: bool = False) -> str:
    if minimal:
        return _providers_tf_minimal
    return _providers_tf if skip_python else _providers_tf_with_external


class AtlasSchemaInfo(Entity):
    resource_types: list[str]
    deprecated_resource_types: list[str]
    raw_resource_schema: dict[str, dict]
    providers_tf: str = _providers_tf


class SchemaAttribute(BaseModel):
    type: str | list | dict | None = None
    description: str | None = None
    description_kind: str | None = None
    optional: bool | None = None
    required: bool | None = None
    computed: bool | None = None
    deprecated: bool | None = None
    sensitive: bool | None = None
    nested_type: SchemaBlock | None = None
    default: object | None = None
    enum: list[object] | None = None
    allowed_values: list[object] | None = None
    force_new: bool | None = None
    conflicts_with: list[str] | None = None
    exactly_one_of: list[str] | None = None
    at_least_one_of: list[str] | None = None
    required_with: list[str] | None = None
    deprecated_message: str | None = None
    validators: list[dict] | None = None
    element_type: str | dict | None = None


class SchemaBlockType(BaseModel):
    block: SchemaBlock
    nesting_mode: str
    min_items: int | None = None
    max_items: int | None = None
    required: bool | None = None
    optional: bool | None = None
    description_kind: str | None = None
    deprecated: bool | None = None
    description: str | None = None
    default: object | None = None
    validators: list[dict] | None = None

    @property
    def block_with_nesting_mode(self) -> SchemaBlock:
        return self.block.model_copy(update={"nesting_mode": self.nesting_mode})


class SchemaBlock(BaseModel):
    attributes: dict[str, SchemaAttribute] | None = None
    block_types: dict[str, SchemaBlockType] | None = None
    description_kind: str | None = None
    description: str | None = None
    deprecated: bool | None = None
    nesting_mode: str | None = None


class ResourceSchema(BaseModel):
    block: SchemaBlock
    version: int | None = None
    description_kind: str | None = None

    def required_attributes(self) -> dict[str, SchemaAttribute]:
        return {name: attr for name, attr in (self.block.attributes or {}).items() if attr.required}


SchemaAttribute.model_rebuild()
SchemaBlockType.model_rebuild()
SchemaBlock.model_rebuild()


def parse_atlas_schema_from_settings(settings: TfExtSettings, provider_config: ProviderGenConfig) -> AtlasSchemaInfo:
    repo_path = settings.repo_path_atlas_provider
    assert repo_path, "repo_path_atlas_provider is required"
    current_sha = run_and_wait("git rev-parse HEAD", cwd=repo_path).stdout_one_line
    cache_dir = settings.provider_cache_dir(provider_config.provider_name)
    if provider_config.last_gen_sha == current_sha:
        return read_cached_atlas_schema(cache_dir, current_sha, settings.tf_cli_config_file)
    schema = parse_atlas_schema()
    provider_config.last_gen_sha = current_sha
    provider_yaml = dump(provider_config.config_dump(), "yaml")
    settings.repo_out.provider_settings_path(provider_config.provider_name).write_text(provider_yaml)
    return schema


def read_cached_atlas_schema(cache_dir: Path, sha: str, tf_cli_config_file: Path | None = None) -> AtlasSchemaInfo:
    json_response_path = cache_dir / f"{sha}.json"
    if not json_response_path.exists():
        logger.info(f"Cache miss for sha = {sha}, parsing atlas schema")
        return parse_atlas_schema(store_path=json_response_path, tf_cli_config_file=tf_cli_config_file)
    parsed_dict = parse_dict(json_response_path)
    return _parse_dict_schema(parsed_dict)


def parse_atlas_schema(store_path: Path | None = None, tf_cli_config_file: Path | None = None) -> AtlasSchemaInfo:
    tf_cli_config_file_str = (
        str(tf_cli_config_file) if tf_cli_config_file else os.environ.get(TF_CLI_CONFIG_FILE_ENV_NAME)
    )
    assert tf_cli_config_file_str, f"{TF_CLI_CONFIG_FILE_ENV_NAME} is required"
    with TemporaryDirectory() as example_dir:
        tmp_path = Path(example_dir)
        providers_tf = tmp_path / "providers.tf"
        providers_tf.write_text(_providers_tf)
        run_and_wait("terraform init", cwd=example_dir)
        schema_run = run_and_wait(
            "terraform providers schema -json",
            cwd=example_dir,
            ansi_content=False,
            env={
                TF_CLI_CONFIG_FILE_ENV_NAME: tf_cli_config_file_str,
                "MONGODB_ATLAS_PREVIEW_PROVIDER_V2_ADVANCED_CLUSTER": "true",
            },
        )
    parsed_dict = schema_run.parse_output(dict, output_format="json")
    if store_path:
        ensure_parents_write_text(store_path, schema_run.stdout_one_line)
    return _parse_dict_schema(parsed_dict)


def _parse_dict_schema(parsed: dict) -> AtlasSchemaInfo:
    resource_schema = parse_provider_resource_schema(parsed, ATLAS_PROVIDER_NAME)

    def is_deprecated(resource_details: dict) -> bool:
        return resource_details["block"].get("deprecated", False)

    deprecated_resource_types = [name for name, details in resource_schema.items() if is_deprecated(details)]
    return AtlasSchemaInfo(
        resource_types=sorted(resource_schema.keys()),
        deprecated_resource_types=sorted(deprecated_resource_types),
        raw_resource_schema=resource_schema,
    )
