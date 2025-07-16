import logging
from pathlib import Path
from typing import Callable

import pytest
from zero_3rdparty.file_utils import clean_dir, copy

from atlas_init.tf_ext.models_module import ModuleGenConfig
from atlas_init.tf_ext.settings import TfExtSettings
from atlas_init.tf_ext.tf_mod_gen import generate_module, module_pipeline

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


class _ModuleNames:
    CLUSTER_PLAIN = "cluster_plain"
    CLUSTER_CUSTOM = "cluster_custom"
    CLUSTER_SKIP_PYTHON = "cluster_skip_python"

    ALL = [CLUSTER_PLAIN, CLUSTER_CUSTOM, CLUSTER_SKIP_PYTHON]

    @classmethod
    def extra_files(cls, name, dataclass_manual_path: Callable[[str], Path]) -> dict[Path, str]:
        return {
            cls.CLUSTER_CUSTOM: {
                dataclass_manual_path("mongodbatlas_advanced_cluster"): "mongodbatlas_advanced_cluster.py"
            },
        }.get(name, {})

    @classmethod
    def auto_tfvars(cls, name) -> str:
        return {
            cls.CLUSTER_PLAIN: _normal_replication_spec_vars,
            cls.CLUSTER_CUSTOM: _electable_and_auto_scaling_vars,
            cls.CLUSTER_SKIP_PYTHON: skip_python_config,
        }.get(name, "")

    @classmethod
    def required_variables(cls, name: str) -> set[str]:
        return {cls.CLUSTER_SKIP_PYTHON: {"project_id", "name", "cluster_type", "replication_specs"}}.get(name, set())

    @classmethod
    def write_extra_files(cls, module_out: Path, name: str, dataclass_manual_path: Callable[[str], Path]):
        for extra_file, name in cls.extra_files(name, dataclass_manual_path).items():
            copy(extra_file, module_out / name)

    @classmethod
    def create_by_name(
        cls, name: str, settings: TfExtSettings, *, clean_and_write: bool, dataclass_manual_path: Callable[[str], Path]
    ) -> ModuleGenConfig:
        config = ModuleGenConfig(
            name=name,
            resource_types=["mongodbatlas_advanced_cluster"],
            settings=settings,
            auto_tfvars=cls.auto_tfvars(name),
            skip_python=cls.CLUSTER_SKIP_PYTHON == name,
            required_variables=cls.required_variables(name),
        )
        if clean_and_write:
            clean_dir(config.module_path)
            cls.write_extra_files(config.module_path, name, dataclass_manual_path)
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
def test_generate_module(module_config_name: str, tf_ext_settings_repo_path, dataclass_manual_path):
    module_config = _ModuleNames.create_by_name(
        module_config_name, tf_ext_settings_repo_path, clean_and_write=True, dataclass_manual_path=dataclass_manual_path
    )
    module_path = generate_module(module_config)
    assert module_path.exists()
    logger.info(f"Created module at {module_path}")


@pytest.mark.parametrize("module_config_name", [_ModuleNames.CLUSTER_SKIP_PYTHON])
def test_generated_module_pipeline(module_config_name: str, tf_ext_settings_repo_path, dataclass_manual_path):
    module_config = _ModuleNames.create_by_name(
        module_config_name,
        tf_ext_settings_repo_path,
        clean_and_write=False,
        dataclass_manual_path=dataclass_manual_path,
    )
    module_path = module_pipeline(module_config)
    assert module_path.exists()
    logger.info(f"Created module at {module_path}")
