import json
from dataclasses import asdict
from pathlib import Path

import pytest

from . import mongodbatlas_advanced_cluster


@pytest.fixture()
def input_dict() -> dict:
    input_json = Path(__file__).with_name("input_existing_test.json")
    return json.loads(input_json.read_text())


def region(
    name: str = "US_EAST_1",
    node_count: int = 0,
    node_count_analytics: int = 0,
    node_count_read_only: int = 0,
    shard_index: int | None = None,
    zone_name: str | None = None,
    provider_name: str | None = None,
    instance_size: str | None = None,
) -> mongodbatlas_advanced_cluster.Region:
    return mongodbatlas_advanced_cluster.Region(
        name=name,
        node_count=node_count,
        shard_index=shard_index,
        zone_name=zone_name,
        provider_name=provider_name,
        instance_size=instance_size,
        node_count_analytics=node_count_analytics,
        node_count_read_only=node_count_read_only,
    )


def auto_scaling(
    min_instance_size: str = "M30", max_instance_size: str = "M50"
) -> mongodbatlas_advanced_cluster.Autoscaling:
    return mongodbatlas_advanced_cluster.Autoscaling(
        compute_min_instance_size=min_instance_size,
        compute_max_instance_size=max_instance_size,
        compute_enabled=True,
        disk_gb_enabled=True,
        compute_scale_down_enabled=True,
    )


def as_resource(raw_dict: dict) -> mongodbatlas_advanced_cluster.ResourceExt:
    return mongodbatlas_advanced_cluster.ResourceExt(**raw_dict)


def test_instance_size_found_on_existing(input_dict):
    resource = resource_with_modifications(input_dict, [region()], auto_scaling=auto_scaling())
    assert resource
    assert resource.auto_scaling
    default_instance_size = resource.auto_scaling.compute_min_instance_size
    assert default_instance_size == "M30"
    assert resource.get_instance_size_electable(region(), 0, 0) == "M10"  # from the old cluster
    assert resource.get_instance_size_electable(region(), 99, 99) == default_instance_size


def test_instance_size_no_existing_uses_compute_min_size(input_dict):
    resource = resource_with_modifications(input_dict, [region()], auto_scaling=auto_scaling(), skip_old=True)
    assert resource
    assert resource.auto_scaling
    assert resource.auto_scaling.compute_min_instance_size == "M30"
    assert resource.get_instance_size_electable(region(), 0, 0) == "M30"


def resource_with_modifications(
    input_dict: dict,
    regions: list[mongodbatlas_advanced_cluster.Region],
    auto_scaling: mongodbatlas_advanced_cluster.Autoscaling | None = None,
    auto_scaling_analytics: mongodbatlas_advanced_cluster.Autoscaling | None = None,
    pop_fields: list[str] | None = None,
    skip_old: bool = False,
    **updates,
) -> mongodbatlas_advanced_cluster.ResourceExt:
    if pop_fields is None:
        pop_fields = ["instance_size"]
    if skip_old:
        pop_fields.append("old_cluster")
    input_dict["regions"] = [asdict(region) for region in regions]
    if auto_scaling:
        input_dict["auto_scaling"] = asdict(auto_scaling)
    if auto_scaling_analytics:
        input_dict["auto_scaling_analytics"] = asdict(auto_scaling_analytics)
    for name in pop_fields:
        input_dict.pop(name, None)
    return as_resource(input_dict | updates)


def get_errors(resource: mongodbatlas_advanced_cluster.ResourceExt) -> list[str]:
    return list(mongodbatlas_advanced_cluster.errors(resource))


def test_validation_error_for_replicaset(input_dict):
    resource = resource_with_modifications(
        input_dict, [region(shard_index=0), region(zone_name="z1")], provider_name="AWS"
    )
    errors = get_errors(resource)
    assert errors == [
        "Replicaset cluster should not define shard_index: regions[0].shard_index=0",
        "Replicaset cluster should not define zone_name: regions[1].zone_name=z1",
    ]


def test_validation_error_for_sharded(input_dict):
    resource = resource_with_modifications(
        input_dict, [region(), region(zone_name="z2")], cluster_type="SHARDED", provider_name="AWS"
    )
    errors = get_errors(resource)
    assert errors == [
        "Must use `regions.*.shard_index` when cluster_type is SHARDED: shard_index missing @ index 0,shard_index missing @ index 1",
        "Sharded cluster should not define zone_name: regions[1].zone_name=z2",
    ]


def test_validation_error_for_geosharded(input_dict):
    resource = resource_with_modifications(
        input_dict, [region(shard_index=3), region(zone_name="z4")], cluster_type="GEOSHARDED", provider_name="AWS"
    )
    errors = get_errors(resource)
    assert errors == [
        "Must use `regions.*.zone_name` when cluster_type is GEOSHARDED: zone_name missing @ index 0",
        "Geosharded cluster should not define shard_index: regions[0].shard_index=3",
    ]


ResourceExt = mongodbatlas_advanced_cluster.ResourceExt
VARIABLE_PLACEHOLDER = "var."
VARIABLES: dict[str, str] = {
    "project_id": VARIABLE_PLACEHOLDER,
    "name": VARIABLE_PLACEHOLDER,
}

auto_scale = auto_scaling(min_instance_size="M30", max_instance_size="M60")
auto_scale_analytics = auto_scaling(min_instance_size="M10", max_instance_size="M30")
EXAMPLES: dict[str, ResourceExt] = {
    "01_single_region": ResourceExt(
        regions=[region(node_count=3, provider_name="AWS", name="US_EAST_1")],
        auto_scaling=auto_scaling(),
        **VARIABLES,
    ),
    "02_single_region_with_analytics": ResourceExt(
        regions=[region(node_count=3, node_count_analytics=1)],
        auto_scaling=auto_scale,
        auto_scaling_analytics=auto_scale_analytics,
        **VARIABLES,
    ),
    "03_single_region_sharded": ResourceExt(
        regions=[
            region(name="US_EAST_1", shard_index=0, instance_size="M40", node_count=3),
            region(name="US_EAST_1", shard_index=1, instance_size="M30", node_count=3),
        ],
        **VARIABLES,
    ),
    "04_multi_region_single_geo": ResourceExt(
        regions=[
            region(name="US_EAST_1", node_count=2),
            region(name="US_EAST_2", node_count=1, node_count_read_only=2),
        ],
        provider_name="AWS",
        auto_scaling=auto_scale,
        **VARIABLES,
    ),
    "05_multi_region_multi_geo": ResourceExt(
        regions=[
            region(shard_index=0, name="US_EAST_1", node_count=3),
            region(shard_index=1, name="EU_WEST_1", node_count=2),
        ],
        provider_name="AWS",
        auto_scaling=auto_scale,
        **VARIABLES,
    ),
    "06_multi_geo_zone_sharded": ResourceExt(
        regions=[
            region(zone_name="US", name="US_EAST_1", node_count=3),
            region(zone_name="EU", name="EU_WEST_1", node_count=3),
        ],
        provider_name="AWS",
        auto_scaling=auto_scale,
        **VARIABLES,
    ),
    "07_multi_cloud": ResourceExt(
        regions=[
            region(provider_name="AZURE", name="US_WEST_2", node_count=2, shard_index=0),
            region(provider_name="AWS", name="US_EAST_2", node_count=1, shard_index=1),
        ],
        provider_name="AWS",
        auto_scaling=auto_scale,
        **VARIABLES,
    ),
}

for name, resource in EXAMPLES.items():
    resource.name = "-".join(name.split("_")[1:])


def test_example01_single_region_checks():
    resource = EXAMPLES["01_single_region"]
    final_resource = mongodbatlas_advanced_cluster.modify_out(resource)
    specs = final_resource.replication_specs
    assert specs
    assert len(specs) == 1
    assert final_resource.cluster_type == "REPLICASET"
    region_configs = specs[0].region_configs
    assert region_configs
    assert len(region_configs) == 1
    assert region_configs[0].electable_specs
    assert region_configs[0].electable_specs.instance_size == auto_scale.compute_min_instance_size
    assert region_configs[0].auto_scaling
    assert not region_configs[0].analytics_specs
    assert not region_configs[0].read_only_specs
    assert not region_configs[0].analytics_auto_scaling


def test_02_single_region_with_analytics():
    resource = EXAMPLES["02_single_region_with_analytics"]
    final_resource = mongodbatlas_advanced_cluster.modify_out(resource)

    specs = final_resource.replication_specs
    assert specs
    assert len(specs) == 1
    assert final_resource.cluster_type == "REPLICASET"
    region_configs = specs[0].region_configs
    assert region_configs
    assert len(region_configs) == 1
    assert region_configs[0].electable_specs
    assert region_configs[0].electable_specs.instance_size == auto_scale.compute_min_instance_size
    assert region_configs[0].auto_scaling
    assert region_configs[0].analytics_specs
    assert region_configs[0].analytics_specs.instance_size == auto_scale_analytics.compute_min_instance_size
    assert region_configs[0].analytics_auto_scaling


def test_03_single_region_sharded():
    resource = EXAMPLES["03_single_region_sharded"]
    final_resource = mongodbatlas_advanced_cluster.modify_out(resource)
    assert final_resource.cluster_type == "SHARDED"
    assert final_resource.replication_specs
    specs: list[mongodbatlas_advanced_cluster.ReplicationSpec] = final_resource.replication_specs
    assert specs
    assert len(specs) == 2
    spec1, spec2 = specs

    assert spec1.region_configs
    assert len(spec1.region_configs) == 1
    assert spec1.region_configs[0].auto_scaling is None
    assert spec1.region_configs[0].electable_specs
    assert spec1.region_configs[0].electable_specs.instance_size == "M40"

    assert spec2.region_configs
    assert len(spec2.region_configs) == 1
    assert spec2.region_configs[0].auto_scaling is None
    assert spec2.region_configs[0].electable_specs
    assert spec2.region_configs[0].electable_specs.instance_size == "M30"


def test_04_multi_region_single_geo():
    resource = EXAMPLES["04_multi_region_single_geo"]
    final_resource = mongodbatlas_advanced_cluster.modify_out(resource)
    assert final_resource.cluster_type == "REPLICASET"
    assert final_resource.replication_specs
    specs: list[mongodbatlas_advanced_cluster.ReplicationSpec] = final_resource.replication_specs
    assert specs
    assert len(specs) == 1
    spec1 = specs[0]
    assert spec1.region_configs
    assert len(spec1.region_configs) == 2
    config1, config2 = spec1.region_configs
    assert config1.region_name == "US_EAST_1"
    assert config1.provider_name == "AWS"
    assert config1.electable_specs
    assert config1.electable_specs.instance_size == auto_scale.compute_min_instance_size
    assert config1.read_only_specs is None

    assert config2.region_name == "US_EAST_2"
    assert config2.provider_name == "AWS"
    assert config2.electable_specs
    assert config2.electable_specs.instance_size == auto_scale.compute_min_instance_size
    assert config2.read_only_specs
    assert config2.read_only_specs.instance_size == auto_scale.compute_min_instance_size


def test_05_multi_region_geo_sharded():
    resource = EXAMPLES["05_multi_region_multi_geo"]
    final_resource = mongodbatlas_advanced_cluster.modify_out(resource)
    assert final_resource.cluster_type == "SHARDED"
    assert final_resource.replication_specs
    assert len(final_resource.replication_specs) == 2
    specs = final_resource.replication_specs
    spec1, spec2 = specs
    assert [spec1.region_configs[0].region_name, spec2.region_configs[0].region_name] == ["US_EAST_1", "EU_WEST_1"]


def test_06_multi_geo_zone_sharded():
    resource = EXAMPLES["06_multi_geo_zone_sharded"]
    final_resource = mongodbatlas_advanced_cluster.modify_out(resource)
    assert final_resource.cluster_type == "GEOSHARDED"
    assert final_resource.replication_specs
    assert len(final_resource.replication_specs) == 2
    specs = final_resource.replication_specs
    spec1, spec2 = specs
    assert [spec1.region_configs[0].region_name, spec2.region_configs[0].region_name] == ["US_EAST_1", "EU_WEST_1"]
    assert [spec1.region_configs[0].electable_specs.node_count, spec2.region_configs[0].electable_specs.node_count] == [
        3,
        3,
    ]


def test_07_multi_cloud():
    resource = EXAMPLES["07_multi_cloud"]
    final_resource = mongodbatlas_advanced_cluster.modify_out(resource)
    assert final_resource.cluster_type == "SHARDED"
    specs = final_resource.replication_specs
    assert specs
    assert len(specs) == 2
    spec1_region1, spec2_region2 = [specs[0].region_configs[0], specs[1].region_configs[0]]
    assert spec1_region1.provider_name == "AZURE"
    assert spec1_region1.electable_specs.node_count == 2

    assert spec2_region2.provider_name == "AWS"
    assert spec2_region2.electable_specs.node_count == 1
