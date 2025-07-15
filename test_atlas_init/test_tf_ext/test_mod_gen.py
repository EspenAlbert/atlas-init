from __future__ import annotations

import logging
from pathlib import Path

import pytest
from model_lib import dump, parse_model
from zero_3rdparty.file_utils import clean_dir, copy, ensure_parents_write_text

from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.gen_resource_main import generate_resource_main
from atlas_init.tf_ext.gen_resource_variables import generate_module_variables
from atlas_init.tf_ext.models_module import ModuleGenConfig, ResourceTypePythonModule
from atlas_init.tf_ext.provider_schema import ResourceSchema, parse_provider_resource_schema
from atlas_init.tf_ext.schema_to_dataclass import convert_and_format, import_resource_type_python_module
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


def dataclass_manual_path(resource_type: str) -> Path:
    return Path(__file__).parent / "testdata/dataclasses" / f"{resource_type}_custom.py"


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
    dataclass_code = convert_and_format(resource_type, resource_schema)
    dataclass_path = generated_dataclass_path(resource_type)
    ensure_parents_write_text(dataclass_path, dataclass_code)
    file_regression.check(dataclass_code, extension=".py", basename=resource_type)


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_dataclass_with_custom(resource_type: str, file_regression):
    resource_schema = read_resource_schema(resource_type)
    existing_path = dataclass_manual_path(resource_type)
    dataclass_code = convert_and_format(resource_type, resource_schema, existing_path)
    file_regression.check(dataclass_code, extension=".py", basename=f"{resource_type}_custom")


def _import_resource_type_dataclass(resource_type: str) -> ResourceTypePythonModule:
    dataclass_path = generated_dataclass_path(resource_type)
    return import_resource_type_python_module(resource_type, dataclass_path)


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_main(resource_type: str, file_regression):
    python_module = _import_resource_type_dataclass(resource_type)
    main_code = generate_resource_main(python_module, ModuleGenConfig(resource_types=[resource_type]))
    ensure_parents_write_text(generated_main_path(resource_type), main_code)
    file_regression.check(main_code, extension=".tf", basename=f"{resource_type}_main")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_main_custom(resource_type: str, file_regression):
    existing_path = dataclass_manual_path(resource_type)
    python_module = import_resource_type_python_module(resource_type, existing_path)
    main_code = generate_resource_main(python_module, ModuleGenConfig(resource_types=[resource_type]))
    ensure_parents_write_text(generated_main_path(resource_type), main_code)
    file_regression.check(main_code, extension=".tf", basename=f"{resource_type}_main_custom")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_variables(resource_type: str, file_regression):
    py_module = _import_resource_type_dataclass(resource_type)
    variables_code, _ = generate_module_variables(py_module, ModuleGenConfig(resource_types=[resource_type]))
    ensure_parents_write_text(generated_variables_path(resource_type), variables_code)
    file_regression.check(variables_code, extension=".tf", basename=f"{resource_type}_variablesx")


@pytest.mark.parametrize("resource_type", ["mongodbatlas_advanced_cluster"])
def test_create_variables_custom(resource_type: str, file_regression):
    existing_path = dataclass_manual_path(resource_type)
    python_module = import_resource_type_python_module(resource_type, existing_path)
    _, variables_code = generate_module_variables(python_module, ModuleGenConfig(resource_types=[resource_type]))
    file_regression.check(variables_code, extension=".tf", basename=f"{resource_type}_variables")


_normal_replication_spec_vars = """
replication_specs = [{
  region_configs = [{
    "provider_name" : "AWS",
    "region_name" : "EU_WEST_1",
    "priority" : 7,
    "analytics_auto_scaling" : {
      "compute_enabled" : true
    },
    "auto_scaling" : {
      "compute_enabled" : false
    }
  }]
}]
"""


class _ModuleNames:
    CLUSTER_PLAIN = "cluster_plain"
    CLUSTER_CUSTOM = "cluster_custom"
    CLUSTER_SKIP_PYTHON = "cluster_skip_python"

    @classmethod
    def extra_files(cls, name) -> dict[Path, str]:
        return {
            cls.CLUSTER_CUSTOM: {
                dataclass_manual_path("mongodbatlas_advanced_cluster"): "mongodbatlas_advanced_cluster.py"
            },
        }.get(name, {})

    @classmethod
    def write_extra_files(cls, module_out: Path, name: str):
        for extra_file, name in cls.extra_files(name).items():
            copy(extra_file, module_out / name)


_cluster_plain = ModuleGenConfig(
    name=_ModuleNames.CLUSTER_PLAIN,
    resource_types=["mongodbatlas_advanced_cluster"],
    auto_tfvars=_normal_replication_spec_vars,
)

_electable_and_auto_scaling_vars = """
electable = {
    disk_size_gb = 30
    regions = [
        {
            provider_name = "AWS"
            name = "EU_WEST_1"
            node_count = 2
        },
        {
            provider_name = "AWS"
            name = "US_EAST_1"
            node_count = 1
        }
    ]
}
auto_scaling_compute = {
    min_size = "M10"
    max_size = "M30"
}
"""

_cluster_custom = ModuleGenConfig(
    name=_ModuleNames.CLUSTER_CUSTOM,
    resource_types=["mongodbatlas_advanced_cluster"],
    auto_tfvars=_electable_and_auto_scaling_vars,
)

skip_python_config = """
backup_enabled = true
replication_specs = [{
  region_configs = [{
    provider_name = "AWS",
    region_name   = "EU_WEST_1",
    priority      = 7,
    electable_specs = {
      node_count    = 3
      instance_size = "M10"
      disk_size_gb  = 10
    }
  }]
}]

project_id   = "664619d870c247237f4b86a6"
name         = "created-from-resource-module"
cluster_type = "REPLICASET"

"""
_cluster_skip_python = ModuleGenConfig(
    name=_ModuleNames.CLUSTER_SKIP_PYTHON,
    resource_types=["mongodbatlas_advanced_cluster"],
    skip_python=True,
    auto_tfvars=skip_python_config,
    required_variables={"project_id", "name", "cluster_type", "replication_specs"},
)

_module_configs = [_cluster_plain, _cluster_custom, _cluster_skip_python]


@pytest.mark.parametrize("module_config", _module_configs, ids=[c.name for c in _module_configs])
def test_generate_module(module_config: ModuleGenConfig, tf_ext_settings_repo_path):
    module_config.settings = tf_ext_settings_repo_path
    clean_dir(module_config.module_path)
    _ModuleNames.write_extra_files(module_config.module_path, module_config.name)
    module_path = generate_module(module_config)
    assert module_path.exists()
    logger.info(f"Created module at {module_path}")
