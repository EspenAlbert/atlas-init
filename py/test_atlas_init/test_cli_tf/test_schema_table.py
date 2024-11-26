import difflib
import logging
from pathlib import Path
from random import shuffle

import pytest

from atlas_init.cli_tf.schema_table import (
    TFSchemaSrc,
    TFSchemaTableInput,
    schema_table,
    sorted_schema_paths,
)
from atlas_init.cli_tf.schema_table_models import TFSchemaTableColumn

logger = logging.getLogger(__name__)

def test_sorted_schema_paths():
    paths = ["", "a", "d", "a.b"]
    shuffle(paths)
    assert sorted_schema_paths(paths) == ["", "a", "d", "a.b"]


@pytest.mark.parametrize("schema_name", ["TPF", "SDKv2"])
def test_schema_table(go_schema_paths, schema_name, file_regression):
    path = go_schema_paths()[schema_name]
    table = schema_table(
        TFSchemaTableInput(sources=[TFSchemaSrc(name=schema_name, file_path=path)])
    )
    file_regression.check(table, extension=".md", basename=schema_name)


def test_create_html_diff(go_schema_paths):
    tpf_path = go_schema_paths()["TPF"]
    sdk_v2_path = go_schema_paths()["SDKv2"]
    output_dir = Path(__file__).parent / test_schema_table.__name__
    columns = [
        TFSchemaTableColumn.Computability,
        # TFSchemaTableColumn.Deprecated,
        # TFSchemaTableColumn.Type,
    ]
    table_tpf = schema_table(
        TFSchemaTableInput(
            sources=[TFSchemaSrc(name=tpf_path.stem, file_path=tpf_path)],
            columns=columns,
            explode_rows=True,
        )
    )
    table_sdk_v2 = schema_table(
        TFSchemaTableInput(
            sources=[TFSchemaSrc(name=sdk_v2_path.stem, file_path=sdk_v2_path)],
            columns=columns,
            explode_rows=True,
        )
    )
    html_text = difflib.HtmlDiff().make_file(
        table_sdk_v2.splitlines(),
        table_tpf.splitlines(),
        "sdk_v2",
        "tpf",
    )
    output_path = output_dir / f"diff-{columns[0]}.html"
    output_path.write_text(html_text)
    logger.info(f"'chrome {output_path}' to see diff")
