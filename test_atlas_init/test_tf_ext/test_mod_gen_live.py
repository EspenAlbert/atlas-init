import logging
import os
from pathlib import Path

from model_lib import dump
import pytest
from zero_3rdparty.file_utils import clean_dir, copy, ensure_parents_write_text

from atlas_init.tf_ext.models_module import ModuleGenConfig
from atlas_init.tf_ext.settings import TfExtSettings
from atlas_init.tf_ext.tf_mod_gen import generate_module, module_pipeline
from atlas_init.tf_ext.plan_diffs import (
    parse_resources_from_plan_json,
    dump_plan_output_resources,
    dump_plan_output_variables,
)


logger = logging.getLogger(__name__)


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

_custom_flat_vars = """
aws_regions = {
    EU_WEST_1 = 3
    US_EAST_1 = 2
}
azure_regions = {
    US_WEST_2 = 2
}
cloud_order = ["aws", "azure"]
instance_size = "M10"
num_shards = 2

project_id   = "664619d870c247237f4b86a6"
name         = "created-from-custom-flat"
"""


class _ModuleNames:
    CLUSTER_PLAIN = "cluster_plain"
    CLUSTER_CUSTOM = "cluster_custom"
    CLUSTER_CUSTOM_FLAT = "cluster_custom_flat"
    CLUSTER_SKIP_PYTHON = "cluster_skip_python"

    ALL = [CLUSTER_PLAIN, CLUSTER_CUSTOM, CLUSTER_CUSTOM_FLAT, CLUSTER_SKIP_PYTHON]

    @classmethod
    def auto_tfvars(cls, name) -> str:
        return {
            cls.CLUSTER_PLAIN: _normal_replication_spec_vars,
            cls.CLUSTER_CUSTOM: _electable_and_auto_scaling_vars,
            cls.CLUSTER_CUSTOM_FLAT: _custom_flat_vars,
            cls.CLUSTER_SKIP_PYTHON: skip_python_config,
        }.get(name, "")

    @classmethod
    def required_variables(cls, name: str) -> set[str]:
        return {cls.CLUSTER_SKIP_PYTHON: {"project_id", "name", "cluster_type", "replication_specs"}}.get(name, set())

    @classmethod
    def write_extra_files(cls, module_out: Path, name: str):
        live_path = livedata_module_path(name)
        for src_file in live_path.glob("*"):
            copy(src_file, module_out / src_file.name)  # should also copy directories

    @classmethod
    def create_by_name(cls, name: str, settings: TfExtSettings, *, clean_and_write: bool) -> ModuleGenConfig:
        config = ModuleGenConfig(
            name=name,
            resource_types=["mongodbatlas_advanced_cluster"],
            settings=settings,
            minimal_tfvars=cls.auto_tfvars(name),
            skip_python=cls.CLUSTER_SKIP_PYTHON == name,
            required_variables=cls.required_variables(name),
        )
        if clean_and_write:
            clean_dir(config.module_path)
        cls.write_extra_files(config.module_path, name)
        return config


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


@pytest.mark.parametrize("module_config_name", _ModuleNames.ALL)
def test_generate_module(module_config_name: str, tf_ext_settings_repo_path):
    module_config = _ModuleNames.create_by_name(module_config_name, tf_ext_settings_repo_path, clean_and_write=True)
    module_path = generate_module(module_config)
    assert module_path.exists()
    logger.info(f"Created module at {module_path}")


def livedata_module_path(module_config_name: str) -> Path:
    return Path(__file__).parent / f"livedata/modules/{module_config_name}"


@pytest.mark.parametrize("module_config_name", [_ModuleNames.CLUSTER_SKIP_PYTHON])
def test_generated_module_pipeline(module_config_name: str, tf_ext_settings_repo_path):
    module_config = _ModuleNames.create_by_name(
        module_config_name,
        tf_ext_settings_repo_path,
        clean_and_write=False,
    )
    module_path = module_pipeline(module_config)
    assert module_path.exists()
    logger.info(f"Created module at {module_path}")


def test_export_planned_resources(tf_ext_settings_repo_path):
    plan_output_path = Path(os.environ["TF_PLAN_OUTPUT"])
    assert plan_output_path.exists(), f"Plan output file {plan_output_path} does not exist"
    plan_output = parse_resources_from_plan_json(plan_output_path)
    output_dir = tf_ext_settings_repo_path.output_plan_dumps / plan_output_path.parent.name
    plan_output_yaml = dump(plan_output, "yaml")
    output_file = output_dir / f"{plan_output_path.stem}.yaml"
    ensure_parents_write_text(output_file, plan_output_yaml)
    logger.info(f"wrote parsed plan to {output_file}")
    dumped_resources = dump_plan_output_resources(output_dir, plan_output)
    logger.info(f"wrote plan resources to {len(dumped_resources)} files")
    dumped_variables = dump_plan_output_variables(output_dir, plan_output)
    logger.info(f"wrote plan variables to {dumped_variables}")
