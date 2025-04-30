from atlas_init.settings.config import TerraformVars, TestSuite


def test_TerraformVars_add():
    vars1 = TerraformVars()
    vars2 = TerraformVars(cluster_info=True)
    vars3 = TerraformVars(use_private_link=True)
    combined = sum([vars1, vars2, vars3], TerraformVars())
    assert combined.cluster_info
    assert combined.use_private_link
    assert not combined.use_vpc_peering


def test_ChangeGroup():
    group = TestSuite(name="g1", repo_go_packages={"tf": ["internal/service/streamconnection"]})
    assert group.is_active("tf", ["internal/service/streamconnection/model_stream_connection.go"])
    assert not group.is_active("tf", ["internal/service/streamconnection"])
    assert not group.is_active("tf", ["internal/service/another/model_stream_connection.go"])
