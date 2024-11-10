from random import shuffle

from atlas_init.cli_tf.schema_table import (
    TFSchemaSrc,
    TFSchemaTableInput,
    file_name_path,
    schema_table,
    sorted_schema_paths,
)


def test_sorted_schema_paths():
    paths = ["", "a", "d", "a.b"]
    shuffle(paths)
    assert sorted_schema_paths(paths) == ["", "a", "d", "a.b"]


def test_schema_table(go_file_path, file_regression):
    path = go_file_path()
    name, _ = file_name_path(str(path))
    name = name.replace("/", "_")
    table = schema_table(
        TFSchemaTableInput(sources=[TFSchemaSrc(name=name, file_path=path)])
    )
    file_regression.check(table, extension=".md", basename=name)
    #TODO: fix computability for func attributes
