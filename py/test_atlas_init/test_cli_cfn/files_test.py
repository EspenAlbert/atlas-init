import json
import os
from pathlib import Path

import pytest
from model_lib import parse_payload
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.cli_cfn.files import CfnSchema, has_md_link, iterate_schemas

_schema = """\
{
  "typeName": "MongoDB::Atlas::Cluster",
  "description": "The cluster resource provides access to your cluster configurations. The resource lets you create, edit and delete clusters. The resource requires your Project ID."
}"""


def test_parse_schema():
    schema_dict = parse_payload(_schema, format="json")
    schema = CfnSchema(**schema_dict)
    assert schema.type_name == "MongoDB::Atlas::Cluster"


def test_iterate_schemas(tmp_path):
    cluster_path = tmp_path / "cluster/cluster.json"
    ensure_parents_write_text(cluster_path, _schema)
    schemas = list(iterate_schemas(tmp_path))
    assert schemas
    assert schemas[0][1].type_name == "MongoDB::Atlas::Cluster"


def test_has_md_link():
    assert has_md_link("some text [Cloudformation examples](https://github.com/aws-cloudformation/aws-cloudformation-samples/tree/main/resource-types/typescript-example-website-monitor)")
    assert not has_md_link("some other text [with] some random syntax")


def test_has_md_code_snippet():
    assert has_md_link("some `code_text`")
    assert not has_md_link("some `other text`")


@pytest.mark.skipif(os.environ.get("JSON_FMT_PATH", "") == "", reason="needs os.environ[JSON_FMT_PATH]")
def test_format_json():
    path = Path(os.environ["JSON_FMT_PATH"])
    json_dict = parse_payload(path)
    new_json = json.dumps(json_dict, indent=4, sort_keys=False)
    path.write_text(new_json)
