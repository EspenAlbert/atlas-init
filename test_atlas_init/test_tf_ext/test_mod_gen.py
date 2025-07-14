from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from model_lib import dump, parse_model
import pytest
from zero_3rdparty.file_utils import ensure_parents_write_text
from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.gen_resource_main import generate_resource_main
from atlas_init.tf_ext.gen_resource_variables import generate_resource_variables
from atlas_init.tf_ext.provider_schema import ResourceSchema, parse_provider_resource_schema
from atlas_init.tf_ext.schema_to_dataclass import convert_to_dataclass

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


def import_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_dataclass(resource_type: str):
    resource_file = resource_type_schema_path(resource_type)
    resource_schema = parse_model(resource_file, ResourceSchema)
    assert resource_schema
    logger.info(f"required attributes for {resource_type}: {resource_schema.required_attributes()}")
    dataclass_code = convert_to_dataclass(resource_schema)
    dataclass_path = generated_dataclass_path(resource_type)
    ensure_parents_write_text(dataclass_path, dataclass_code)
    module = import_from_path(resource_type, dataclass_path)
    assert module
    resource = getattr(module, "Resource")
    assert resource

    main_code = generate_resource_main(resource_type, resource)
    ensure_parents_write_text(generated_main_path(resource_type), main_code)

    variables_code = generate_resource_variables(resource)
    ensure_parents_write_text(generated_variables_path(resource_type), variables_code)
