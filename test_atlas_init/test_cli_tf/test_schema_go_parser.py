from collections import Counter

from atlas_init.cli_tf.schema_go_parser import parse_schema_functions


def test_go_parser(go_schema_paths):
    program = go_schema_paths()["TPF"].read_text()
    attributes, _ = parse_schema_functions(program)
    attribute_names = {a.name for a in attributes}
    expected_names = {
        "analytics_auto_scaling",
        "analytics_specs",
        "electable_specs",
        "read_only_specs",
        "zone_id",
    }
    missing_names = expected_names - attribute_names
    assert not missing_names, f"missing: {missing_names}"
    counts = Counter()
    # sourcery skip: no-loop-in-tests
    for a in attributes:
        counts[a.name] += 1
    duplicates = len(attributes) - len(attribute_names)
    assert sorted(counts.most_common(duplicates)) == [
        ("disk_size_gb", 2),
        ("key", 2),
        ("provider_name", 2),
        ("value", 2),
    ]
    by_name = {a.name: a for a in attributes}
    assert by_name["analytics_specs"].start_end == (389, 423)
    by_schema_path = {a.attribute_path: a for a in attributes}
    assert len(by_schema_path) == len(attributes)
    assert by_name["analytics_specs"].attribute_path == "replication_specs.region_configs.analytics_specs"
    assert by_name["analytics_specs"].parent_attribute_names() == [
        "replication_specs",
        "region_configs",
    ]
    assert by_name["cluster_type"].is_required
    assert by_name["region_configs"].attribute_path == "replication_specs.region_configs"
    assert by_name["advanced_configuration"].attribute_path == "advanced_configuration"
    assert by_name["compute_enabled"].attribute_path == "(analytics_auto_scaling|auto_scaling).compute_enabled"
    assert (
        by_name["ebs_volume_type"].attribute_path == "(analytics_specs|electable_specs|read_only_specs).ebs_volume_type"
    )
    assert by_name["ebs_volume_type"].parent_attribute_names() == [
        "analytics_specs",
        "electable_specs",
        "read_only_specs",
    ]

    required_attributes = sorted(a.name for a in attributes if a.is_required)
    assert required_attributes == [
        "cluster_type",
        "key",
        "key",
        "name",
        "priority",
        "project_id",
        "provider_name",
        "region_configs",
        "region_name",
        "replication_specs",
        "value",
        "value",
    ]
    absolute_paths = [a.absolute_attribute_path for a in sorted(attributes)]
    first, *_, last = absolute_paths
    assert first == "accept_data_risks_and_force_replica_set_reconfig"
    assert last == "version_release_system"
