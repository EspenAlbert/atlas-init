from pathlib import Path

from atlas_init.tf_ext.tf_resource_usage import (
    ExampleSrc,
    ResourceUsage,
    build_simple_graph,
    dump_usage_md,
    iter_rows,
    _iter_edges,
)

_example = """\
resource "mongodbatlas_cloud_provider_access_setup" "this" {
  project_id    = var.project_id
  provider_name = "AWS"
}

resource "mongodbatlas_cloud_provider_access_authorization" "this" {
  project_id = var.project_id
  role_id    = mongodbatlas_cloud_provider_access_setup.this.role_id

  aws {
    iam_assumed_role_arn = local.aws_iam_role_arn
  }
}
"""


def test__iter_edges():
    assert sorted(
        _iter_edges(
            set(["mongodbatlas_cloud_provider_access_setup", "mongodbatlas_cloud_provider_access_authorization"]),
            "mongodbatlas_cloud_provider_access_authorization",
            _example,
        )
    ) == [("mongodbatlas_cloud_provider_access_setup", "mongodbatlas_cloud_provider_access_authorization")]


def test_resource_usage(tmp_path: Path, file_regression):
    tf_path = tmp_path / "main.tf"
    tf_path.write_text(_example)
    tf_path2 = tmp_path / "main2.tf"
    tf_path2.write_text(_example)
    usage = ResourceUsage(root_path=tmp_path)
    for row in iter_rows(ExampleSrc.UserSpecified, tmp_path, set(), ["*.tf"]):
        usage.add_row(row)
    out_md = tmp_path / "resource_usage.md"
    dump_usage_md(usage, out_md)
    file_regression.check(out_md.read_text(), extension=".md")
    graph = build_simple_graph(usage)
    assert graph.parent_child_edges == {
        "mongodbatlas_cloud_provider_access_setup": {"mongodbatlas_cloud_provider_access_authorization"},
    }


_example_rst = """\
  .. code-block::
   :copyable: true

   # Create a Group to Assign to Project 
   resource "mongodbatlas_team" "project_group" {
     org_id = var.atlas_org_id
     name   = var.atlas_group_name
     usernames = [
       "user1@example.com",
       "user2@example.com"
     ]
   }
"""


def test_resource_usage_rst(tmp_path: Path):
    tf_path = tmp_path / "main.rst"
    tf_path.write_text(_example_rst)
    usage = ResourceUsage(root_path=tmp_path)
    for row in iter_rows(ExampleSrc.Registry, tmp_path, set(), ["*.rst"]):
        usage.add_row(row)
    assert len(usage.rows) == 1
    assert "mongodbatlas_team" in usage.rows
