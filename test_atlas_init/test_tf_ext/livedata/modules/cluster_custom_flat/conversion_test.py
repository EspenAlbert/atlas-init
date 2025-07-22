import json
from pathlib import Path

import pytest

from . import mongodbatlas_advanced_cluster


@pytest.fixture()
def input_dict() -> dict:
    input_json = Path(__file__).with_name("input_existing_test.json")
    return json.loads(input_json.read_text())


def region(name: str = "US_EAST_1", node_count: int = 0) -> mongodbatlas_advanced_cluster.Region:
    return mongodbatlas_advanced_cluster.Region(name=name, node_count=node_count)


def test_instance_size_found_on_existing(input_dict):
    input_dict.pop("instance_size", None)  # ensure no default instance size set
    resource = mongodbatlas_advanced_cluster.ResourceExt(**input_dict)
    assert resource
    assert resource.auto_scaling
    default_instance_size = resource.auto_scaling.compute_min_instance_size
    assert default_instance_size == "M30"
    assert resource.get_instance_size_electable(region(), 0, 0) == "M10"  # from the old cluster
    assert resource.get_instance_size_electable(region(), 99, 99) == default_instance_size


def test_instance_size_no_existing_uses_compute_min_size(input_dict):
    input_dict.pop("instance_size", None)  # ensure no default instance size set
    input_dict.pop("old_cluster", None)  # ensure no old cluster config
    resource = mongodbatlas_advanced_cluster.ResourceExt(**input_dict)
    assert resource
    assert resource.auto_scaling
    assert resource.auto_scaling.compute_min_instance_size == "M30"
    assert resource.get_instance_size_electable(region(), 0, 0) == "M30"
