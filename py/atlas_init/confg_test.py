from atlas_init.config import ChangeGroup, TerraformVars


def test_TerraformVars_add():
    vars1 = TerraformVars()
    vars2 = TerraformVars(cluster_info=True)
    vars3 = TerraformVars(use_private_link=True)
    combined = sum([vars1, vars2, vars3], TerraformVars())
    assert combined.cluster_info
    assert combined.use_private_link
    assert not combined.use_cluster


def test_ChangeGroup():
    group = ChangeGroup(name="g1", repo_go_packages={"tf": ["internal/service/streamconnection"]})
    assert group.is_active("tf", ["internal/service/streamconnection/model_stream_connection.go"])
    assert group.is_active("tf", ["internal/service/streamconnection"])
    assert not group.is_active("tf", ["internal/service/another/model_stream_connection.go"])