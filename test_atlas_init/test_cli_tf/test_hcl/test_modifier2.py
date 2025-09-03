from typing import Any
from hcl2.api import parses, reverse_transform
from lark.tree import Meta
from atlas_init.cli_tf.hcl.modifier import safe_parse
from atlas_init.cli_tf.hcl.modifier2 import (
    AttributeChange,
    TFVar,
    attribute_transfomer,
    print_tree,
    update_attribute_object_str_value_for_block,
    variable_reader_typed,
    write_tree,
)
from hcl2.transformer import Attribute, DictTransformer
from lark import Tree
from lark.visitors import v_args

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
    version_transformer, version_changes = attribute_transfomer("mongodbatlas", "version", "1.34.0")
    new_tree = update_attribute_object_str_value_for_block(tree, "terraform", version_transformer)
    assert version_changes == [AttributeChange("mongodbatlas", "1.33.0", "1.34.0")]
    new_tf = write_tree(new_tree)  # type: ignore
    file_regression.check(new_tf, extension=".tf")


_defaults_example = """\
project_id = "abc"
advanced_configuration = {
  default_write_concern = "majority"
  custom_openssl_cipher_config_tls12 = ["TLS1_2"]
}
"""


class DefaultsReader(DictTransformer):
    def __init__(self, with_meta: bool = False):
        self.found_defaults: dict[str, Tree] = {}
        super().__init__(with_meta)

    def attribute(self, args: list) -> Attribute:
        response = super().attribute(args)
        self.found_defaults[response.key] = response.value
        return response


class VariablesBlockReader(DictTransformer):
    def __init__(self, with_meta: bool = False, defaults: dict[str, Any] | None = None):
        super().__init__(with_meta)
        self.defaults = defaults or {}

    @v_args(meta=True)
    def block(self, meta: Meta, args: list) -> Tree:
        response = super().block(meta, args)
        if variable_dict := response.get("variable"):
            for variable_name, variable_value in variable_dict.items():
                if variable_name in self.defaults:
                    new_value = variable_value["default"] = self.defaults[variable_name]
                    if isinstance(new_value, dict):
                        variable_type = variable_value.get("type", {})
                        if isinstance(variable_type, str) and variable_type.startswith("${object({"):
                            new_tree = parses("dummy = " + variable_type.removeprefix("${object(").removesuffix(")}"))
                            assert isinstance(
                                new_tree, Tree
                            )  # could actually do the reverse parsing here and dump back to a
                            # can use the def object_elem
                            # and add to the expr_term of each field
                            # rich.print(new_tree)

        return response


_variables_example = """
variable "project_id" {
  type = string
}

variable "advanced_configuration" {
  type = object({
    default_write_concern = string
    custom_openssl_cipher_config_tls12 = optional(list(string))
  })
}
"""

_expected_defaults = {
    "project_id": "abc",
    "advanced_configuration": {
        "default_write_concern": "majority",
        "custom_openssl_cipher_config_tls12": ["TLS1_2"],
    },
}


def test_reading_defaults(tmp_path):
    file = tmp_path / "defaults.tf"
    file.write_text(_defaults_example)
    print_tree(file)
    tree = safe_parse(file)
    assert tree is not None
    reader = DefaultsReader()
    reader.transform(tree)
    assert reader.found_defaults == _expected_defaults


def test_updating_defaults(tmp_path, file_regression):
    file = tmp_path / "variables.tf"
    file.write_text(_variables_example)
    tree = safe_parse(file)
    assert tree is not None
    reader = VariablesBlockReader(defaults=_expected_defaults)
    new_tree = reader.transform(tree)
    tree_modified = reverse_transform(new_tree)
    new_vars = write_tree(tree_modified)
    file_regression.check(new_vars, basename="variables_with_defaults", extension=".tf")


_variables_typed_example = """
variable "required_string" {
  type = string
}

variable "optional_string" {
  type = string
  default = "default"
}

variable "sensitive_string" {
  type = string
  sensitive = true
}

variable "object_with_defaults" {
  type = object({
    default_write_concern = string
    custom_openssl_cipher_config_tls12 = optional(list(string))
  })
  default = {
    default_write_concern = "majority"
    custom_openssl_cipher_config_tls12 = ["TLS1_2"]
  }
}
"""


def test_reading_variables_typed(tmp_path):
    file = tmp_path / "variables.tf"
    file.write_text(_variables_typed_example)
    tree = safe_parse(file)
    assert tree is not None
    variables = variable_reader_typed(tree)
    assert variables == {
        "required_string": TFVar(name="required_string", description="", type="string", sensitive=False),
        "optional_string": TFVar(
            name="optional_string",
            description="",
            type="string",
            sensitive=False,
            default="default",
        ),
        "sensitive_string": TFVar(name="sensitive_string", description="", type="string", sensitive=True),
        "object_with_defaults": TFVar(
            name="object_with_defaults",
            description="",
            type='object({"default_write_concern": "string", "custom_openssl_cipher_config_tls12": "${optional(list(string))}"})',
            sensitive=False,
            default={"default_write_concern": "majority", "custom_openssl_cipher_config_tls12": ["TLS1_2"]},
        ),
    }
