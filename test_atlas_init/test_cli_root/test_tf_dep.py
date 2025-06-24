import logging
import os
from pathlib import Path
from unittest.mock import MagicMock
from pydot import Graph
import pytest
from atlas_init.cli_root.tf_dep import create_dot_graph, parse_graphs

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
    dot_graph: Graph = create_dot_graph(atlas_graph)
    assert dot_graph is not None
