import logging
import os
from pathlib import Path

import pytest
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.settings.rich_utils import tree_text
from atlas_init.tf_ext.tf_dep import ResourceRef, parse_graph, parse_graph_output
from atlas_init.tf_ext.tf_example_readme import (
    MODULES_JSON_RELATIVE_PATH,
    ResourceGraph,
    create_module_graph,
    create_subgraph,
    parse_modules_json,
)

logger = logging.getLogger(__name__)

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


def _create_graph(
    edges: list[tuple[ResourceRef, ResourceRef]], orphans: set[ResourceRef] | None = None
) -> ResourceGraph:
    graph = ResourceGraph()
    for edge in edges:
        graph.add_edge(*edge)
    return graph


def _create_tree(edges: list[tuple[ResourceRef, ResourceRef]], orphans: set[ResourceRef] | None = None) -> str:
    graph = ResourceGraph()
    for edge in edges:
        graph.add_edge(*edge)
    if orphans:
        for orphan in orphans:
            graph.add_orphan_if_not_found(orphan)
    tree = graph.to_tree("example", include_orphans=True)
    return tree_text(tree)


def test_resource_graph(file_regression):
    a = ResourceRef(full_ref="a")
    b = ResourceRef(full_ref="b")
    c = ResourceRef(full_ref="c")
    edges = [
        (a, b),
        (b, c),
    ]
    file_regression.check(_create_tree(edges))


def test_resource_graph_double_parent(file_regression):
    a = ResourceRef(full_ref="a")
    b = ResourceRef(full_ref="b")
    c = ResourceRef(full_ref="c")
    edges = [
        (a, b),
        (a, c),
        (b, c),
    ]
    file_regression.check(_create_tree(edges))


def test_resource_graph_reverse_order_same(file_regression):
    a = ResourceRef(full_ref="a")
    b = ResourceRef(full_ref="b")
    c = ResourceRef(full_ref="c")
    edges = [
        (a, b),
        (b, c),
    ]
    tree1 = _create_tree(edges)
    tree2 = _create_tree(list(reversed(edges)))
    assert tree1 == tree2


def test_resource_graph_orphans(file_regression):
    a = ResourceRef(full_ref="a")
    b = ResourceRef(full_ref="b")
    c = ResourceRef(full_ref="c")
    edges = [
        (a, b),
    ]
    file_regression.check(_create_tree(edges, {b, c}))


def test_create_subgraph_bool(file_regression):
    a = ResourceRef(full_ref="a")
    b = ResourceRef(full_ref="b")
    c = ResourceRef(full_ref="c")
    edges = [
        (a, b),
        (b, c),
    ]
    a_b_c = _create_graph(edges, {b, c})
    a_b_subgraph = create_subgraph(a_b_c, lambda parent, child: parent == a or child == b)
    subgraph_text = tree_text(a_b_subgraph.to_tree("a_b_subgraph"))
    file_regression.check(subgraph_text)


def test_create_subgraph_tuple(file_regression):
    a = ResourceRef(full_ref="a")
    b = ResourceRef(full_ref="b")
    c = ResourceRef(full_ref="c")
    edges = [
        (a, b),
        (b, c),
    ]
    a_b_c = _create_graph(edges, {b, c})

    def swap_parent_child(parent: ResourceRef, child: ResourceRef) -> tuple[ResourceRef, ResourceRef]:
        return (child, parent)

    c_b_a_subgraph = create_subgraph(a_b_c, swap_parent_child)
    subgraph_text = tree_text(c_b_a_subgraph.to_tree("c_b_a_subgraph"))
    file_regression.check(subgraph_text)


def test_create_module_graph(file_regression):
    def module_ref(module_name: str, name: str) -> ResourceRef:
        return ResourceRef(full_ref=f"module.{module_name}.{name}")

    m1_a = module_ref("m1", "a")
    m1_b = module_ref("m1", "b")
    m2_a = module_ref("m2", "a")
    m2_b = module_ref("m2", "b")
    m3_a = module_ref("m3", "a")
    edges = [
        (m1_a, m1_b),
        (m1_b, m2_a),
        (m2_a, m2_b),
    ]
    resource_graph = _create_graph(edges, {m3_a})
    resource_tree = _create_tree(edges, {m3_a})
    logger.info(f"resource_tree: {resource_tree}")
    module_graph, emoji_counter = create_module_graph(resource_graph)
    assert [str(node) for node in module_graph.sorted_parents()] == [
        "1️⃣ m1",
    ]
    assert emoji_counter.get_emoji("m1") == "1️⃣"
    assert emoji_counter.get_emoji("m2") == "2️⃣"
    assert emoji_counter.get_emoji("m3") == "3️⃣"
    module_tree = module_graph.to_tree("module_graph", include_orphans=True)
    module_tree_text = tree_text(module_tree)
    logger.info(f"module_tree: {module_tree_text}")
    file_regression.check(module_tree_text)


@pytest.mark.skipif(os.environ.get("TF_WORKSPACE_PATH", "") == "", reason="needs os.environ[TF_WORKSPACE_PATH]")
def test_tf_example_readme():
    workspace_path = Path(os.environ["TF_WORKSPACE_PATH"])
    assert workspace_path.exists(), f"TF_WORKSPACE_PATH does not exist: {workspace_path}"
    path, graph_output = parse_graph(workspace_path)
    logger.info(f"graph output: {graph_output}")
    parsed_graph = parse_graph_output(path, graph_output)
    graph = ResourceGraph.from_graph(parsed_graph)
    tree = graph.to_tree("graph", include_orphans=True)
    text = tree_text(tree)
    logger.info(f"tree: {text}")
