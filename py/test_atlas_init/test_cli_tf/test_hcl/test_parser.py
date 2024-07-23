from atlas_init.cli_tf.hcl.parser import (
    Block,
    ResourceBlock,
    hcl_attrs,
    iter_blocks,
    iter_resource_blocks,
)

after1 = """\
resource "mongodbatlas_advanced_cluster" "project_cluster_free" {
  count      = local.use_free_cluster ? 1 : 0
  project_id = var.project_id
  name       = var.cluster_name
  cluster_type = "REPLICASET"

  replication_specs {
    region_configs {
      auto_scaling {
        disk_gb_enabled = false
      }
      priority = 7
      provider_name               = "TENANT"
      backing_provider_name       = "AWS"
      region_name = var.region
      electable_specs {
        instance_size = var.instance_size
      }
    }
  }
}"""
before1 = """\
resource "mongodbatlas_cluster" "project_cluster_free" {
  count      = local.use_free_cluster ? 1 : 0
  project_id = var.project_id
  name       = var.cluster_name

  provider_name               = "TENANT"
  backing_provider_name       = "AWS"
  provider_region_name        = var.region
  provider_instance_size_name = var.instance_size
}"""


def test_iter_resource_blocks():
    assert list(iter_resource_blocks(before1)) == [
        ResourceBlock(
            name="project_cluster_free",
            type="mongodbatlas_cluster",
            line_start=1,
            indent="",
            hcl=before1,
            line_end=10,
        )
    ]
    assert list(iter_resource_blocks(after1)) == [
        ResourceBlock(
            name="project_cluster_free",
            type="mongodbatlas_advanced_cluster",
            line_start=1,
            indent="",
            hcl=after1,
            line_end=21,
        )
    ]


_block_example = """\
resource "mongodbatlas_advanced_cluster" "project_cluster_free" {
  count      = local.use_free_cluster ? 1 : 0
  project_id = var.project_id
  name       = var.cluster_name
  cluster_type = "REPLICASET"

  advanced_configuration {
    default_read_concern                 = null
    default_write_concern                = null
    fail_index_key_too_long              = false
    javascript_enabled                   = true
    minimum_enabled_tls_protocol         = "TLS1_2"
    no_table_scan                        = false
    oplog_min_retention_hours            = 0
    oplog_size_mb                        = 0
    sample_refresh_interval_bi_connector = 0
    sample_size_bi_connector             = 0
    transaction_lifetime_limit_seconds   = 0
  }
  bi_connector_config {
    enabled         = false
    read_preference = "secondary"
  }
  
  replication_specs {
    zone_name = "zone 1"
    region_configs {
      auto_scaling {
        disk_gb_enabled = false
      }
      priority = 7
      provider_name               = "TENANT"
      backing_provider_name       = "AWS"
      region_name = var.region
      electable_specs {
        instance_size = var.instance_size
      }
    }
    region_configs {
      auto_scaling {
        disk_gb_enabled = true
      }
      priority = 7
      provider_name               = "TENANT"
      backing_provider_name       = "AWS"
      region_name = var.region
      electable_specs {
        instance_size = var.instance_size
      }
    }
  }
  replication_specs {
    zone_name = "zone 2"
    region_configs {
      auto_scaling {
        disk_gb_enabled = false
      }
      priority = 7
      provider_name               = "TENANT"
      backing_provider_name       = "AWS"
      region_name = var.region2
      electable_specs {
        instance_size = var.instance_size
      }
    }
  }
}"""


def get_replication_specs(resource: Block) -> list[Block]:
    return [
        block for block in iter_blocks(resource) if block.name == "replication_specs"
    ]


def test_iter_blocks():
    resource = get_resource_block()
    blocks = list(iter_blocks(resource, level=1))
    assert len(blocks) == 4
    assert [b.name for b in blocks] == [
        "advanced_configuration",
        "bi_connector_config",
        "replication_specs",
        "replication_specs",
    ]
    replication_spec1 = blocks[2]
    two_region_configs = list(iter_blocks(replication_spec1, level=2))
    assert len(two_region_configs) == 2
    assert [b.name for b in two_region_configs] == ["region_configs", "region_configs"]
    region_spec_blocks = list(iter_blocks(two_region_configs[0], level=3))
    assert len(region_spec_blocks) == 2
    assert [b.name for b in region_spec_blocks] == ["auto_scaling", "electable_specs"]

    replication_spec2 = blocks[3]
    one_region_config = list(iter_blocks(replication_spec2, level=2))
    assert len(one_region_config) == 1
    assert [b.name for b in one_region_config] == ["region_configs"]


def get_resource_block():
    example_resources = list(iter_resource_blocks(_block_example))
    assert len(example_resources) == 1
    resource = example_resources[0]
    assert resource.name == "project_cluster_free"
    assert resource.type == "mongodbatlas_advanced_cluster"
    return resource


def test_hcl_attrs():
    resource = get_resource_block()
    root_attributes = hcl_attrs(resource)
    assert root_attributes == {
        "count": "local.use_free_cluster ? 1 : 0",
        "project_id": "var.project_id",
        "name": "var.cluster_name",
        "cluster_type": '"REPLICASET"',
    }
    rep_spec1, rep_spec2 = get_replication_specs(resource)
    rep_spec1_attributes = hcl_attrs(rep_spec1)
    assert rep_spec1_attributes == {
        "zone_name": '"zone 1"',
    }
    rep_spec2_attributes = hcl_attrs(rep_spec2)
    assert rep_spec2_attributes == {
        "zone_name": '"zone 2"',
    }
    region_configs1 = list(iter_blocks(rep_spec1))
    assert len(region_configs1) == 2
    region_configs_attributes = hcl_attrs(region_configs1[0])
    assert region_configs_attributes == {
        "priority": "7",
        "provider_name": '"TENANT"',
        "backing_provider_name": '"AWS"',
        "region_name": "var.region",
    }
