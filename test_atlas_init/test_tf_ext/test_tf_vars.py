from atlas_init.tf_ext.tf_vars import parse_all_variables


def test_parse_all_variables(tf_variables_path):
    vars_usage = parse_all_variables([tf_variables_path.parent, tf_variables_path.parent])
    shortened_vars = {key: str(value) for key, value in vars_usage.root.items()}
    assert (
        shortened_vars["org_id"]
        == "TfVarUsage(name='org_id',descriptions={'Unique 24-hexadecimal digit string that identifies your Atlas Organization'},paths_str='/mongodbatlas_stream_instance')"
    )
