import logging
import os
from pathlib import Path
from unittest.mock import MagicMock
from pydot import Graph
import pytest
from atlas_init.tf_ext.tf_dep import (
    find_variable_resource_type_usages,
    find_variables,
    parse_graphs,
)
from atlas_init.tf_ext.tf_modules import color_coder, create_internal_dependencies

logger = logging.getLogger(__name__)


@pytest.mark.skipif(os.environ.get("EXAMPLE_PATH", "") == "", reason="needs os.environ[EXAMPLE_PATH]")
def test_parse_graph():
    path = Path(os.environ["EXAMPLE_PATH"])
    atlas_graph = parse_graphs([path], MagicMock())
    assert atlas_graph.parent_child_edges == {
        "mongodbatlas_cloud_provider_access_authorization": {"mongodbatlas_encryption_at_rest"},
        "mongodbatlas_encryption_at_rest": {"mongodbatlas_advanced_cluster"},
    }
    assert atlas_graph.external_parents == {
        "mongodbatlas_cloud_provider_access_authorization": {"aws_iam_role"},
        "mongodbatlas_encryption_at_rest": {"aws_kms_key"},
    }
    dot_graph: Graph = create_internal_dependencies(atlas_graph, color_coder(atlas_graph, keep_provider_name=False))
    assert dot_graph is not None


def test_parse_search_deployment_graph(tf_search_deployment_example_path):
    graph = parse_graphs([tf_search_deployment_example_path], MagicMock())
    assert graph.parent_child_edges["mongodbatlas_advanced_cluster"] == {"mongodbatlas_search_deployment"}


def test_find_variables(tf_variables_path):
    expected_vars = {
        "public_key": "Public API key to authenticate to Atlas",
        "private_key": "Private API key to authenticate to Atlas",
        "org_id": "Unique 24-hexadecimal digit string that identifies your Atlas Organization",
    }
    assert find_variables(tf_variables_path) == expected_vars
    usages = find_variable_resource_type_usages(set(expected_vars), tf_variables_path.parent)
    assert usages == {
        "org_id": {"mongodbatlas_project"},
    }
