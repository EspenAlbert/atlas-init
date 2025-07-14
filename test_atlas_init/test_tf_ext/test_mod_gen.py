from __future__ import annotations

import logging
from pathlib import Path

import pytest
from model_lib import dump, parse_model
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.gen_resource_main import ResourceAbs, generate_resource_main
from atlas_init.tf_ext.gen_resource_variables import generate_resource_variables
from atlas_init.tf_ext.provider_schema import ResourceSchema, parse_provider_resource_schema
from atlas_init.tf_ext.schema_to_dataclass import convert_and_format, import_resource_type_dataclass
from atlas_init.tf_ext.tf_mod_gen import generate_module

logger = logging.getLogger(__name__)


def resource_type_schema_path(resource_type: str) -> Path:
    return Path(__file__).parent / "testdata/resources" / f"{resource_type}.json"


def generated_dataclass_path(resource_type: str) -> Path:
    return Path(__file__).parent / "testdata/dataclasses" / f"{resource_type}.py"


def generated_main_path(resource_type: str) -> Path:
    return Path(__file__).parent / "testdata/main" / f"{resource_type}.tf"


def generated_variables_path(resource_type: str) -> Path:
    return Path(__file__).parent / "testdata/variables" / f"{resource_type}.tf"


def test_dump_resource_schemas(atlas_schemas_dict):
    resource_schema = parse_provider_resource_schema(atlas_schemas_dict, ATLAS_PROVIDER_NAME)
    assert resource_schema
    for resource_type, details in resource_schema.items():
        resource_file = resource_type_schema_path(resource_type)
        ensure_parents_write_text(resource_file, dump(details, "json"))


def test_check_if_all_schemas_are_parseable(atlas_schemas_dict):
    resource_schema = parse_provider_resource_schema(atlas_schemas_dict, ATLAS_PROVIDER_NAME)
    assert resource_schema
    for resource_type in resource_schema.keys():
        resource_file = resource_type_schema_path(resource_type)
        parse_model(resource_file, ResourceSchema)
        logger.info(f"Parsed resource schema for {resource_type}")


def read_resource_schema(resource_type: str) -> ResourceSchema:
    resource_file = resource_type_schema_path(resource_type)
    resource_schema = parse_model(resource_file, ResourceSchema)
    assert resource_schema
    return resource_schema


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_dataclass(resource_type: str, file_regression):
    resource_schema = read_resource_schema(resource_type)
    dataclass_code = convert_and_format(resource_schema)
    dataclass_path = generated_dataclass_path(resource_type)
    ensure_parents_write_text(dataclass_path, dataclass_code)
    file_regression.check(dataclass_code, extension=".py", basename=resource_type)


def _import_resource_type_dataclass(resource_type: str) -> type[ResourceAbs]:
    dataclass_path = generated_dataclass_path(resource_type)
    return import_resource_type_dataclass(resource_type, dataclass_path)


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_main(resource_type: str, file_regression):
    resource = _import_resource_type_dataclass(resource_type)
    main_code = generate_resource_main(resource_type, resource)
    ensure_parents_write_text(generated_main_path(resource_type), main_code)
    file_regression.check(main_code, extension=".tf", basename=f"{resource_type}_main")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_variables(resource_type: str, file_regression):
    resource = _import_resource_type_dataclass(resource_type)
    variables_code = generate_resource_variables(resource)
    ensure_parents_write_text(generated_variables_path(resource_type), variables_code)
    file_regression.check(variables_code, extension=".tf", basename=f"{resource_type}_variables")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_generate_module(resource_type: str, tf_ext_settings_repo_path):
    module_path = generate_module(resource_type, tf_ext_settings_repo_path)
    assert module_path.exists()
    logger.info(f"Created module at {module_path}")
