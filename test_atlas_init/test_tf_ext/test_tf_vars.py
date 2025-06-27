from unittest.mock import MagicMock
from atlas_init.tf_ext.paths import ResourceVarUsage, find_resource_types_with_usages
from atlas_init.tf_ext.tf_vars import parse_all_variables


def test_parse_all_variables(tf_variables_path):
    vars_usage = parse_all_variables([tf_variables_path.parent, tf_variables_path.parent], MagicMock())
    shortened_vars = {key: str(value) for key, value in vars_usage.root.items()}
    assert (
        shortened_vars["org_id"]
        == "TfVarUsage(name='org_id',descriptions={'Unique 24-hexadecimal digit string that identifies your Atlas Organization'},paths_str='/mongodbatlas_stream_instance')"
    )


def test_parse_resource_types(tf_push_based_log_example):
    usages = find_resource_types_with_usages(tf_push_based_log_example.parent)
    assert "mongodbatlas_push_based_log_export" in usages.root
    assert usages.root["mongodbatlas_push_based_log_export"].example_files[0].name == "main.tf"
    assert not usages.root["mongodbatlas_push_based_log_export"].variable_usage
    assert "mongodbatlas_project" in usages.root
    assert usages.root["mongodbatlas_project"].variable_usage == [
        ResourceVarUsage(var_name="atlas_project_name", attribute_path="name"),
        ResourceVarUsage(var_name="atlas_org_id", attribute_path="org_id"),
    ]
    assert "aws_s3_bucket" in usages.root
    assert usages.root["aws_s3_bucket"].variable_usage == [
        ResourceVarUsage(var_name="s3_bucket_name", attribute_path="bucket"),
    ]
