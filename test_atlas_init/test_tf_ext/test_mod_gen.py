from __future__ import annotations

import logging

import pytest
from model_lib import dump, parse_model
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.gen_resource_main import generate_resource_main
from atlas_init.tf_ext.gen_resource_variables import generate_module_variables
from atlas_init.tf_ext.models_module import ModuleGenConfig, ResourceTypePythonModule
from atlas_init.tf_ext.provider_schema import ResourceSchema, parse_provider_resource_schema
from atlas_init.tf_ext.schema_to_dataclass import (
    convert_and_format,
    import_resource_type_python_module,
)

logger = logging.getLogger(__name__)


def test_dump_resource_schemas(atlas_schemas_dict, resource_type_schema_path):
    resource_schema = parse_provider_resource_schema(atlas_schemas_dict, ATLAS_PROVIDER_NAME)
    assert resource_schema
    for resource_type, details in resource_schema.items():
        resource_file = resource_type_schema_path(resource_type)
        ensure_parents_write_text(resource_file, dump(details, "json"))


def test_check_if_all_schemas_are_parseable(atlas_schemas_dict, resource_type_schema_path):
    resource_schema = parse_provider_resource_schema(atlas_schemas_dict, ATLAS_PROVIDER_NAME)
    assert resource_schema
    for resource_type in resource_schema.keys():
        resource_file = resource_type_schema_path(resource_type)
        parse_model(resource_file, ResourceSchema)
        logger.info(f"Parsed resource schema for {resource_type}")


def read_resource_schema(resource_type: str, resource_type_schema_path) -> ResourceSchema:
    resource_file = resource_type_schema_path(resource_type)
    resource_schema = parse_model(resource_file, ResourceSchema)
    assert resource_schema
    return resource_schema


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_dataclass(resource_type: str, file_regression, resource_type_schema_path, generated_dataclass_path):
    resource_schema = read_resource_schema(resource_type, resource_type_schema_path)
    dataclass_code = convert_and_format(
        resource_type, resource_schema, config=ModuleGenConfig(resource_types=[resource_type])
    )
    dataclass_path = generated_dataclass_path(resource_type)
    ensure_parents_write_text(dataclass_path, dataclass_code)
    file_regression.check(dataclass_code, extension=".py", basename=resource_type)


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_dataclass_with_custom(
    resource_type: str, file_regression, resource_type_schema_path, dataclass_manual_path
):
    resource_schema = read_resource_schema(resource_type, resource_type_schema_path)
    existing_path = dataclass_manual_path(resource_type)
    dataclass_code = convert_and_format(
        resource_type, resource_schema, ModuleGenConfig(resource_types=[resource_type]), existing_path
    )
    file_regression.check(dataclass_code, extension=".py", basename=f"{resource_type}_custom")


def _import_resource_type_dataclass(resource_type: str, generated_dataclass_path) -> ResourceTypePythonModule:
    dataclass_path = generated_dataclass_path(resource_type)
    return import_resource_type_python_module(resource_type, dataclass_path)


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_main(resource_type: str, file_regression, generated_dataclass_path, generated_main_path):
    python_module = _import_resource_type_dataclass(resource_type, generated_dataclass_path)
    main_code = generate_resource_main(python_module, ModuleGenConfig(resource_types=[resource_type]))
    ensure_parents_write_text(generated_main_path(resource_type), main_code)
    file_regression.check(main_code, extension=".tf", basename=f"{resource_type}_main")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_main_custom(resource_type: str, file_regression, generated_main_path, dataclass_manual_path):
    existing_path = dataclass_manual_path(resource_type)
    python_module = import_resource_type_python_module(resource_type, existing_path)
    main_code = generate_resource_main(python_module, ModuleGenConfig(resource_types=[resource_type]))
    ensure_parents_write_text(generated_main_path(resource_type), main_code)
    file_regression.check(main_code, extension=".tf", basename=f"{resource_type}_main_custom")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_variables(resource_type: str, file_regression, generated_dataclass_path, generated_variables_path):
    py_module = _import_resource_type_dataclass(resource_type, generated_dataclass_path)
    variables_code, _ = generate_module_variables(py_module, ModuleGenConfig(resource_types=[resource_type]))
    ensure_parents_write_text(generated_variables_path(resource_type), variables_code)
    file_regression.check(variables_code, extension=".tf", basename=f"{resource_type}_variablesx")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_variables_custom(resource_type: str, file_regression, dataclass_manual_path, generated_variables_path):
    existing_path = dataclass_manual_path(resource_type)
    python_module = import_resource_type_python_module(resource_type, existing_path)
    _, variables_code = generate_module_variables(python_module, ModuleGenConfig(resource_types=[resource_type]))
    file_regression.check(variables_code, extension=".tf", basename=f"{resource_type}_variables")
