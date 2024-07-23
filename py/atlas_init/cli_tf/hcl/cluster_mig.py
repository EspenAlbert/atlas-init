from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Literal, Self

from atlas_init.cli_tf.hcl.parser import (
    Block,
    ResourceBlock,
    hcl_attrs,
    iter_blocks,
    iter_resource_blocks,
)

logger = logging.getLogger(__name__)
INDENT = "  "


def indent(level: int, line: str) -> str:
    return INDENT * level + line


def convert_cluster_config(hcl_config: str) -> str:
    """
    For the given HCL config, convert the `mongodbatlas_cluster` resource to `mongodbatlas_advanced_cluster`.

    Strategy:
    - support find all resource blocks, e.g. `resource "mongodbatlas_cluster" "project_cluster_free"`
    - for each resource block
        - rename the resource_type to `mongodbatlas_advanced_cluster`
        - Iterate through all root attributes and copy them to the new resource.
        - Iterate through all the block attributes
            - If the block attribute is `replication_specs`:
                - Iterate through all the attributes and copy them.
                - Iterate through all the nested_blocks and copy them
            - Otherwise, copy the block attribute as is.
        for every copy, lookup:
            - if the key has been renamed in the new resource.
    Special attributes:
    - disk_size_gb (only set on root in legacy but in electable_specs in new)
    - provider_name (only set on root in legacy but in replication_specs in new)
    - node_counts are specs in new
    - auto_scaling_xx has moved to a block
    """
    replacements = {}
    for block in iter_resource_blocks(hcl_config):
        if block.type != "mongodbatlas_cluster":
            continue
        replacements[block] = convert_cluster_block(block)
    logger.info(f"found {len(replacements)} blocks to replace")
    for block, new_block in replacements.items():
        hcl_config = hcl_config.replace(block.hcl, new_block)
    return hcl_config


_removed_attributes_root = {
    "provider_name",
    "provider_instance_size_name",
    "auto_scaling_disk_gb_enabled",
    "auto_scaling_compute_enabled",
    "provider_auto_scaling_compute_min_instance_size",
    "provider_auto_scaling_compute_max_instance_size",
    "auto_scaling_compute_scale_down_enabled",
    "backing_provider_name",
    "provider_disk_iops",
    "provider_encrypt_ebs_volume",
    "provider_volume_type",
    "provider_region_name",
    "replication_factor",
}
_removed_attributes_region_config = {
    "electable_nodes",
    "read_only_nodes",
    "analytics_nodes",
}

_renamed_attributes = {
    "cloud_backup": "backup_enabled",
}


def attribute_migration(
    block_name: Literal["root", "", "region_config"], key: str, value: str
) -> tuple[str, str] | None:
    if block_name == "root":
        if key in _removed_attributes_root:
            return None
        key = _renamed_attributes.get(key, key)
        return key, value
    if block_name == "region_config":
        if key in _removed_attributes_region_config:
            return None
        return key, value
    return key, value


def write_attributes(
    level: int, attributes: dict[str, str], block_name: Literal["root", "", "region_config"] = ""
) -> list[str]:
    lines = []
    for key, value in attributes.items():
        migrated_key_value = attribute_migration(block_name, key, value)
        if not migrated_key_value:
            continue
        new_key, new_value = migrated_key_value
        lines.append(f"{'  ' * level}{new_key} = {new_value}")
    return lines


@dataclass()
class ClusterMigContext:
    # root level
    provider_name: str = ""
    provider_instance_size_name: str = ""
    auto_scaling_disk_gb_enabled: str = ""
    auto_scaling_compute_enabled: str = ""
    provider_auto_scaling_compute_min_instance_size: str = ""
    provider_auto_scaling_compute_max_instance_size: str = ""
    auto_scaling_compute_scale_down_enabled: str = ""
    backing_provider_name: str = ""
    provider_disk_iops: str = ""
    provider_encrypt_ebs_volume: str = ""
    provider_volume_type: str = ""
    provider_region_name: str = ""

    # region_config
    electable_nodes: str = ""
    read_only_nodes: str = ""
    analytics_nodes: str = ""

    def add_region_config(self, region_config: dict[str, str]) -> Self:
        return type(self)(**as_mig_context_kwargs(region_config), **asdict(self))

    @property
    def auto_scaling_lines(self) -> list[str]:
        auto_scaling_block = {}
        if self.auto_scaling_disk_gb_enabled:
            auto_scaling_block["disk_gb_enabled"] = self.auto_scaling_disk_gb_enabled
        if self.auto_scaling_compute_enabled:
            auto_scaling_block["compute_enabled"] = self.auto_scaling_compute_enabled
        if self.provider_auto_scaling_compute_min_instance_size:
            auto_scaling_block["compute_min_instance_size"] = self.provider_auto_scaling_compute_min_instance_size
        if self.provider_auto_scaling_compute_max_instance_size:
            auto_scaling_block["compute_max_instance_size"] = self.provider_auto_scaling_compute_max_instance_size
        if self.auto_scaling_compute_scale_down_enabled:
            auto_scaling_block["compute_scale_down_enabled"] = self.auto_scaling_compute_scale_down_enabled
        if not auto_scaling_block:
            return []
        return [
            indent(3, "auto_scaling {", *write_attributes(4, auto_scaling_block)),
            indent(3, "}"),
        ]

    def hardware_spec(self, node_count: str) -> dict[str, str]:
        hardware_spec = {}
        if node_count:
            hardware_spec["node_count"] = node_count
        if self.provider_instance_size_name:
            hardware_spec["instance_size"] = self.provider_instance_size_name
        if self.provider_disk_iops:
            hardware_spec["disk_iops"] = self.provider_disk_iops
        if self.provider_volume_type:
            hardware_spec["ebs_volume_type"] = self.provider_volume_type
        return hardware_spec

    @property
    def electable_spec_lines(self) -> list[str]:
        if not self.electable_nodes and not self.provider_instance_size_name:
            return []

        electable_block = self.hardware_spec(self.electable_nodes)
        return [
            indent(3, "electable_specs {"),
            *write_attributes(4, electable_block),
            indent(3, "}"),
        ]

    @property
    def analytics_spec_lines(self) -> list[str]:
        if not self.analytics_nodes:
            return []
        analytics_block = self.hardware_spec(self.analytics_nodes)
        return [
            indent(3, "analytics_specs {", *write_attributes(4, analytics_block)),
            indent(3, "}"),
        ]

    @property
    def read_only_spec_lines(self) -> list[str]:
        if not self.read_only_nodes:
            return []
        read_only_block = self.hardware_spec(self.read_only_nodes)
        return [
            indent(3, "read_only_specs {", *write_attributes(4, read_only_block)),
            indent(3, "}"),
        ]

    def region_config_lines(self, attributes: dict[str, str]) -> list[str]:
        if self.provider_region_name:
            attributes.setdefault("region_name", self.provider_region_name)
        if self.provider_name:
            attributes.setdefault("provider_name", self.provider_name)
        if self.backing_provider_name:
            attributes.setdefault("backing_provider_name", self.backing_provider_name)
        return [
            indent(2, "region_configs {"),
            *write_attributes(3, attributes, "region_config"),
            *self.auto_scaling_lines,
            *self.electable_spec_lines,
            *self.analytics_spec_lines,
            *self.read_only_spec_lines,
            indent(2, "}"),
        ]


_mig_context_fields = set(asdict(ClusterMigContext()))


def as_mig_context_kwargs(attributes: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in attributes.items() if k in _mig_context_fields}


_default_replication_spec_legacy = """\
  replication_specs {
    region_config {
      priority = 7
    }
  }"""


def default_replication_spec(line_start: int) -> Block:
    hcl = _default_replication_spec_legacy
    return Block(
        name="replication_specs",
        level=1,
        line_start=line_start,
        line_end=line_start + len(hcl.split("\n")),
        hcl=hcl,
    )


def convert_cluster_block(root_block: ResourceBlock) -> str:
    root_blocks = list(iter_blocks(root_block))
    attributes_root = hcl_attrs(root_block)
    attributes_root.setdefault("cluster_type", '"REPLICASET"')
    cluster_content = [
        f'resource "mongodbatlas_advanced_cluster" "{root_block.name}" {{',
    ]
    cluster_content.extend(write_attributes(1, attributes_root, "root"))
    mig_context = ClusterMigContext(**as_mig_context_kwargs(attributes_root))
    replication_spec_blocks = get_replication_specs(root_block)
    if not replication_spec_blocks:
        line_start = len(root_block.content_lines())
        root_blocks.append(default_replication_spec(line_start))
    for block in root_blocks:
        if block.name == "replication_specs":
            cluster_content.extend(write_replication_spec(block, mig_context))
        else:
            cluster_content.append(block.hcl)
    cluster_content.append("}")
    return "\n".join(cluster_content)


def write_replication_spec(block: Block, mig_context: ClusterMigContext) -> list[str]:
    nested_blocks = list(iter_blocks(block))
    attributes = hcl_attrs(block)
    lines = [
        "  replication_specs {",
        *write_attributes(2, attributes),
    ]
    for block in nested_blocks:
        if block.name == "region_config":
            lines.extend(write_region_config(block, mig_context))
        else:
            lines.append(block.hcl)
    lines.append("  }")
    return lines


def write_region_config(block: Block, mig_context: ClusterMigContext) -> list[str]:
    attributes = hcl_attrs(block)
    region_config_mig = mig_context.add_region_config(attributes)
    return region_config_mig.region_config_lines(attributes)


def get_replication_specs(resource: Block) -> list[Block]:
    return [block for block in iter_blocks(resource) if block.name == "replication_specs"]
