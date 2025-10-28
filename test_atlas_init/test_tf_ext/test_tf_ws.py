from atlas_init.tf_ext.tf_ws import include_ws_path


def test_include_ws_path_max_ws_depth():
    assert include_ws_path("some-example-dir")
    assert include_ws_path("some-example-dir", max_ws_depth=1)
    assert include_ws_path("some-example-dir/main.tf", max_ws_depth=1)
    assert not include_ws_path("some-example-dir/main.tf", max_ws_depth=0)
    assert include_ws_path("some-nested/example/main.tf", max_ws_depth=2)
    assert not include_ws_path("some-nested/example/main.tf", max_ws_depth=1)
