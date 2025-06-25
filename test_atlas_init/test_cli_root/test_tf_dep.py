import logging
import os
from pathlib import Path
from unittest.mock import MagicMock
from pydot import Graph
import pytest
from atlas_init.cli_root.tf_dep import (
    create_internal_dependencies,
    find_variable_resource_type_usages,
    find_variables,
    parse_graphs,
)

logger = logging.getLogger(__name__)


@pytest.mark.skipif(os.environ.get("EXAMPLE_PATH", "") == "", reason="needs os.environ[EXAMPLE_PATH]")
def test_parse_graph(monkeypatch):
    path = os.environ["PATH"]
    extra_path = os.environ.get("EXTRA_PATH", "")
    monkeypatch.setenv("PATH", f"{path}:{extra_path}")
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
    dot_graph: Graph = create_internal_dependencies(atlas_graph)
    assert dot_graph is not None


@pytest.mark.skipif(os.environ.get("TF_VARIABLES_PATH", "") == "", reason="needs os.environ[TF_VARIABLES_PATH]")
def test_find_variables():
    path = Path(os.environ["TF_VARIABLES_PATH"])
    expected_vars = {"org_id", "private_key", "public_key"}
    assert find_variables(path) == expected_vars
    usages = find_variable_resource_type_usages(expected_vars, path.parent)
    assert usages == {
        "org_id": {"mongodbatlas_project"},
    }
