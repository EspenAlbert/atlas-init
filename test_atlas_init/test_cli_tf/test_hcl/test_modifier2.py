from atlas_init.cli_tf.hcl.modifier import safe_parse
from atlas_init.cli_tf.hcl.modifier2 import attribute_transfomer, update_attribute_object_str_value_for_block, write_tree


_provider_example = """\
terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "1.33.0"
    }
  }
  required_version = ">= 1.0"
}"""


def test_using_transformer_to_update_data(tmp_path, file_regression):
    file = tmp_path / "provider.tf"
    file.write_text(_provider_example)
    tree = safe_parse(file)
    assert tree is not None
    new_tree = update_attribute_object_str_value_for_block(tree, "terraform", attribute_transfomer("mongodbatlas", "version", "1.34.0"))
    new_tf = write_tree(new_tree)  # type: ignore
    file_regression.check(new_tf, extension=".tf")
