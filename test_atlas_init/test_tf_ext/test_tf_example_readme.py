from typing import Protocol

import pytest
from rich.console import Console
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.tf_ext.tf_dep import ResourceRef
from atlas_init.tf_ext.tf_example_readme import MODULES_JSON_RELATIVE_PATH, ResourceGraph, parse_modules_json

_example_modules_json = """
{
    "Modules": [
        {
            "Key": "",
            "Source": "",
            "Dir": "."
        },
        {
            "Key": "alert_configuration",
            "Source": "../../../modules/03_alert_configuration",
            "Dir": "../../../modules/03_alert_configuration"
        },
        {
            "Key": "atlas_cluster",
            "Source": "../../../modules/01_cluster",
            "Dir": "../../../modules/01_cluster"
        },
        {
            "Key": "atlas_project",
            "Source": "../../../modules/02_project",
            "Dir": "../../../modules/02_project"
        },
        {
            "Key": "auth_db",
            "Source": "../../../modules/05_auth_db",
            "Dir": "../../../modules/05_auth_db"
        },
        {
            "Key": "automated_backup_test_cluster",
            "Source": "../../../modules/01_cluster",
            "Dir": "../../../modules/01_cluster"
        },
        {
            "Key": "cloud_provider_aws",
            "Source": "../../../modules/04_cloud_provider_aws",
            "Dir": "../../../modules/04_cloud_provider_aws"
        },
        {
            "Key": "networking_aws",
            "Source": "../../../modules/06_networking_aws",
            "Dir": "../../../modules/06_networking_aws"
        },
        {
            "Key": "vpc",
            "Source": "registry.terraform.io/terraform-aws-modules/vpc/aws",
            "Version": "5.1.0",
            "Dir": ".terraform/modules/vpc"
        }
    ]
}
"""


def test_parse_modules_json(tmp_path):
    example_path = tmp_path / "example"
    example_path.mkdir()
    modules_json_path = example_path / MODULES_JSON_RELATIVE_PATH
    ensure_parents_write_text(modules_json_path, _example_modules_json)
    configs = parse_modules_json(example_path)
    assert len(configs.modules) == 8
    assert configs.modules["vpc"].keys == ["vpc"]
    assert configs.modules["vpc"].source == "registry.terraform.io/terraform-aws-modules/vpc/aws"
    assert configs.modules["vpc"].version == "5.1.0"
    assert configs.modules["vpc"].rel_path == ".terraform/modules/vpc"
    assert configs.modules["alert_configuration"].keys == ["alert_configuration"]
    assert configs.modules["alert_configuration"].source == "../../../modules/03_alert_configuration"
    assert configs.modules["alert_configuration"].version == ""
    assert configs.modules["alert_configuration"].rel_path == "../../../modules/03_alert_configuration"
    assert configs.modules["atlas_cluster"].keys == ["atlas_cluster", "automated_backup_test_cluster"]
    assert len(configs.modules_included(skip_keys=["vpc"])) == 7
    assert len(configs.modules_included(skip_keys=["atlas_cluster"])) == 6


# https://github.com/Textualize/rich/blob/8c4d3d1d50047e3aaa4140d0ffc1e0c9f1df5af4/tests/test_live.py#L11
def create_capture_console(*, width: int = 60, height: int = 80, force_terminal: bool = True) -> Console:
    return Console(
        width=width,
        height=height,
        force_terminal=force_terminal,
        legacy_windows=False,
        color_system=None,  # use no color system to reduce complexity of output,
        _environ={},
    )


class _CreateTree(Protocol):
    def __call__(
        self, edges: list[tuple[ResourceRef, ResourceRef]], orphans: set[ResourceRef] | None = None
    ) -> str: ...


@pytest.fixture()
def create_tree() -> _CreateTree:
    def _create_tree(edges: list[tuple[ResourceRef, ResourceRef]], orphans: set[ResourceRef] | None = None) -> str:
        graph = ResourceGraph()
        for edge in edges:
            graph.add_edge(*edge)
        if orphans:
            for orphan in orphans:
                graph.add_orphan_if_not_found(orphan)
        tree = graph.to_tree("example", include_orphans=True)
        console = create_capture_console()
        console.begin_capture()
        console.print(tree)
        ended = console.end_capture()
        return ended

    return _create_tree


def test_resource_graph(file_regression, create_tree):
    a = ResourceRef(full_ref="a")
    b = ResourceRef(full_ref="b")
    c = ResourceRef(full_ref="c")
    edges = [
        (a, b),
        (b, c),
    ]
    file_regression.check(create_tree(edges))


def test_resource_graph_double_parent(file_regression, create_tree):
    a = ResourceRef(full_ref="a")
    b = ResourceRef(full_ref="b")
    c = ResourceRef(full_ref="c")
    edges = [
        (a, b),
        (a, c),
        (b, c),
    ]
    file_regression.check(create_tree(edges))


def test_resource_graph_reverse_order_same(file_regression, create_tree):
    a = ResourceRef(full_ref="a")
    b = ResourceRef(full_ref="b")
    c = ResourceRef(full_ref="c")
    edges = [
        (a, b),
        (b, c),
    ]
    tree1 = create_tree(edges)
    tree2 = create_tree(list(reversed(edges)))
    assert tree1 == tree2


def test_resource_graph_orphans(file_regression, create_tree):
    a = ResourceRef(full_ref="a")
    b = ResourceRef(full_ref="b")
    c = ResourceRef(full_ref="c")
    edges = [
        (a, b),
    ]
    file_regression.check(create_tree(edges, {b, c}))
