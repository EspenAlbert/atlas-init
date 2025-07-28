from __future__ import annotations

import logging

import pytest
from model_lib import dump, parse_model
from zero_3rdparty.file_utils import copy, ensure_parents_write_text

from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.gen_examples import generate_module_examples
from atlas_init.tf_ext.gen_resource_main import format_tf_content, generate_resource_main
from atlas_init.tf_ext.gen_resource_output import generate_resource_output
from atlas_init.tf_ext.gen_resource_variables import generate_module_variables
from atlas_init.tf_ext.models_module import ModuleGenConfig, ResourceGenConfig, ResourceTypePythonModule
from atlas_init.tf_ext.provider_schema import ResourceSchema, parse_provider_resource_schema
from atlas_init.tf_ext.schema_to_dataclass import (
    convert_and_format,
    import_resource_type_python_module,
)

logger = logging.getLogger(__name__)
ADV_CLUSTER_CUSTOM = "mongodbatlas_advanced_cluster_custom"


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


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster", "mongodbatlas_cloud_backup_schedule"])
def test_create_dataclass(resource_type: str, file_regression, resource_type_schema_path, generated_dataclass_path):
    resource_schema = read_resource_schema(resource_type, resource_type_schema_path)
    dataclass_code = convert_and_format(
        resource_type,
        resource_schema,
        config=ModuleGenConfig(resources=[ResourceGenConfig(name=resource_type, skip_variables_extra={"labels"})]),
    )
    dataclass_path = generated_dataclass_path(resource_type)
    ensure_parents_write_text(dataclass_path, dataclass_code)
    file_regression.check(dataclass_code, extension=".py", basename=resource_type)


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_dataclass_with_required(resource_type: str, file_regression, resource_type_schema_path):
    resource_schema = read_resource_schema(resource_type, resource_type_schema_path)
    dataclass_code = convert_and_format(
        resource_type,
        resource_schema,
        config=ModuleGenConfig(
            resources=[
                ResourceGenConfig(
                    name=resource_type,
                    skip_variables_extra={"labels"},
                    required_variables={"name", "replication_specs"},
                )
            ]
        ),
    )
    file_regression.check(dataclass_code, extension=".py", basename=f"{resource_type}_required")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_dataclass_with_custom(
    resource_type: str, file_regression, resource_type_schema_path, dataclass_manual_path
):
    resource_schema = read_resource_schema(resource_type, resource_type_schema_path)
    existing_path = dataclass_manual_path(ADV_CLUSTER_CUSTOM)
    dataclass_code = convert_and_format(
        resource_type,
        resource_schema,
        ModuleGenConfig(resources=[ResourceGenConfig(name=resource_type)]),
        existing_path,
    )
    file_regression.check(dataclass_code, extension=".py", basename=f"{resource_type}_custom")


def _import_resource_type_dataclass(resource_type: str, generated_dataclass_path) -> ResourceTypePythonModule:
    dataclass_path = generated_dataclass_path(resource_type)
    return import_resource_type_python_module(resource_type, dataclass_path)


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_main(resource_type: str, file_regression, generated_dataclass_path, generated_main_path):
    python_module = _import_resource_type_dataclass(resource_type, generated_dataclass_path)
    main_code = generate_resource_main(
        python_module, ModuleGenConfig(resources=[ResourceGenConfig(name=resource_type)])
    )
    ensure_parents_write_text(generated_main_path(resource_type), main_code)
    file_regression.check(main_code, extension=".tf", basename=f"{resource_type}_main")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_main_custom(resource_type: str, file_regression, generated_main_path, dataclass_manual_path):
    existing_path = dataclass_manual_path(ADV_CLUSTER_CUSTOM)
    python_module = import_resource_type_python_module(resource_type, existing_path)
    main_code = generate_resource_main(
        python_module, ModuleGenConfig(resources=[ResourceGenConfig(name=resource_type)])
    )
    ensure_parents_write_text(generated_main_path(resource_type), main_code)
    file_regression.check(main_code, extension=".tf", basename=f"{resource_type}_main_custom")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_variables(resource_type: str, file_regression, generated_dataclass_path, generated_variables_path):
    py_module = _import_resource_type_dataclass(resource_type, generated_dataclass_path)
    variables_code, _ = generate_module_variables(
        py_module, ResourceGenConfig(name=resource_type, skip_variables_extra={"labels"})
    )
    ensure_parents_write_text(generated_variables_path(resource_type), variables_code)
    file_regression.check(variables_code, extension=".tf", basename=f"{resource_type}_variablesx")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_variables_custom(resource_type: str, file_regression, dataclass_manual_path):
    existing_path = dataclass_manual_path(ADV_CLUSTER_CUSTOM)
    python_module = import_resource_type_python_module(resource_type, existing_path)
    _, variables_code = generate_module_variables(
        python_module,
        ResourceGenConfig(name=resource_type, skip_variables_extra={"labels"}),
    )
    file_regression.check(variables_code, extension=".tf", basename=f"{resource_type}_variables")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_cloud_backup_schedule"])
def test_create_variables_flat(resource_type: str, file_regression, generated_dataclass_path):
    py_module = _import_resource_type_dataclass(resource_type, generated_dataclass_path)
    variables_code, _ = generate_module_variables(py_module, ResourceGenConfig(name=resource_type, flat_variables=True))
    file_regression.check(variables_code, extension=".tf", basename=f"{resource_type}_variablesx")


def test_generate_examples_advanced_cluster(file_regression, dataclass_manual_path, tmp_path):
    resource_type = "mongodbatlas_advanced_cluster"
    python_module = _import_resource_type_dataclass(ADV_CLUSTER_CUSTOM, dataclass_manual_path)
    test_file = dataclass_manual_path(ModuleGenConfig.FILENAME_EXAMPLES_TEST)
    copy(test_file, tmp_path / ModuleGenConfig.FILENAME_EXAMPLES_TEST)
    ensure_parents_write_text(tmp_path / "__init__.py", "")
    config = ModuleGenConfig(
        name=resource_type,
        resources=[ResourceGenConfig(name=resource_type)],
        out_dir=tmp_path,
        in_dir=test_file.parent,
        skip_python=True,
    )
    copy(
        dataclass_manual_path(ADV_CLUSTER_CUSTOM),
        config.dataclass_path(resource_type).with_name(f"{ADV_CLUSTER_CUSTOM}.py"),
    )
    examples = generate_module_examples(config, python_module, resource_type=resource_type)
    examples_contents = "\n".join(
        f"# {example.name} - {example_file.stem}\n{format_tf_content(example_file.read_text())}"
        for example in sorted(examples)
        for example_file in sorted(example.glob("*.tf"))
    )
    file_regression.check(examples_contents, extension=".tf", basename=f"{resource_type}_examples")


def test_create_output_tf(file_regression, generated_dataclass_path):
    resource_type = "mongodbatlas_advanced_cluster"
    python_module = _import_resource_type_dataclass(resource_type, generated_dataclass_path)
    output_code = generate_resource_output(
        python_module, ModuleGenConfig(resources=[ResourceGenConfig(name=resource_type)])
    )
    file_regression.check(output_code, extension=".tf", basename=f"{resource_type}_output")
