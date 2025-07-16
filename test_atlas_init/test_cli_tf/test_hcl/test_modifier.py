from contextlib import suppress
from pathlib import Path
from typing import Dict, List
from hcl2.transformer import Attribute, DictTransformer
import hcl2
from lark import Token, Transformer, Tree, v_args
import pytest

from atlas_init.cli_tf.hcl.modifier import (
    BLOCK_TYPE_OUTPUT,
    BLOCK_TYPE_VARIABLE,
    read_block_attribute_object_keys,
    safe_parse,
    update_descriptions,
)

example_variables_tf = """variable "cluster_name" {
  type = string
}
variable "replication_specs" {
  description = "List of replication specifications in legacy mongodbatlas_cluster format"
  default     = []
  type = list(object({
    num_shards = number
    zone_name  = string
    regions_config = set(object({
      region_name     = string
      electable_nodes = number
      priority        = number
      read_only_nodes = optional(number, 0)
    }))
  }))
}

variable "provider_name" {
  type    = string
  default = "" # optional in v3
}
"""

_existing_descriptions_variables = {
    "cluster_name": [""],
    "provider_name": [""],
    "replication_specs": ["List of replication specifications in legacy "],
}

example_outputs_tf = """provider "mongodbatlas" {
  public_key  = var.public_key
  private_key = var.private_key
}

module "cluster" {
  source = "../../module_maintainer/v3"

  cluster_name           = var.cluster_name
  cluster_type           = var.cluster_type
  mongo_db_major_version = var.mongo_db_major_version
  project_id             = var.project_id
  replication_specs_new  = var.replication_specs_new
  tags                   = var.tags
}

output "mongodb_connection_strings" {
  value = module.cluster.mongodb_connection_strings
}

output "with_desc" {
  value = "with_desc"
  description = "description old"
}
"""
_existing_descriptions_outputs = {
    "mongodb_connection_strings": [""],
    "with_desc": ["description old"],
}


@pytest.mark.parametrize(
    ("block_type", "new_names", "existing_descriptions", "tf_config"),
    [
        (
            BLOCK_TYPE_VARIABLE,
            {
                "cluster_name": 'description of "cluster" name',
                "provider_name": "azure/aws/gcp",
            },
            _existing_descriptions_variables,
            example_variables_tf,
        ),
        (
            BLOCK_TYPE_OUTPUT,
            {
                "with_desc": "description new",
                "mongodb_connection_strings": "new connection strings desc",
            },
            _existing_descriptions_outputs,
            example_outputs_tf,
        ),
    ],
    ids=[BLOCK_TYPE_VARIABLE, BLOCK_TYPE_OUTPUT],
)
def test_process_variables(tmp_path, file_regression, block_type, new_names, existing_descriptions, tf_config):
    example_tf_path = tmp_path / "example.tf"
    example_tf_path.write_text(tf_config)

    def update_description(name: str, old_description: str, path: Path) -> str:
        return new_names.get(name, old_description)

    new_tf, existing_descriptions = update_descriptions(example_tf_path, update_description, block_type=block_type)
    file_regression.check(new_tf, extension=".tf")
    assert dict(existing_descriptions.items()) == existing_descriptions


out_example_env_vars = """\
output "env_vars" {
  value = {
    MONGODB_ATLAS_PROFILE         = var.cfn_profile
    MONGODB_ATLAS_PUBLIC_API_KEY  = var.atlas_public_key
    MONGODB_ATLAS_PRIVATE_API_KEY = var.atlas_private_key
    # cfn-e2e
    MONGODB_ATLAS_SECRET_PROFILE = var.cfn_profile
    CFN_EXAMPLE_EXECUTION_ROLE   = aws_iam_role.execution_role.arn
  }
  description = "Environment variables for the example"
}
"""


def test_output_env_vars_keys(tmp_path):
    example_tf_path = tmp_path / "example.tf"
    example_tf_path.write_text(out_example_env_vars)
    env_vars = read_block_attribute_object_keys(
        example_tf_path,
        block_type=BLOCK_TYPE_OUTPUT,
        block_name="env_vars",
        block_key="value",
    )
    assert env_vars == [
        "MONGODB_ATLAS_PROFILE",
        "MONGODB_ATLAS_PUBLIC_API_KEY",
        "MONGODB_ATLAS_PRIVATE_API_KEY",
        "MONGODB_ATLAS_SECRET_PROFILE",
        "CFN_EXAMPLE_EXECUTION_ROLE",
    ]


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


def find_object_string_value(tree: Tree, obj_key: str) -> str:
    obj_value: str | None = None

    def look_for_obj_key_value(maybe_object_elem: Tree) -> bool:
        nonlocal obj_value
        if maybe_object_elem.data != "object_elem":
            return False
        obj_elems = [
            child
            for child in maybe_object_elem.children
            if isinstance(child, Tree) and child.data in {"object_elem_key", "expr_term"}
        ]
        if len(obj_elems) != 2:
            return False
        object_elem_key, object_elem_value = obj_elems
        if identifier_name(object_elem_key) == obj_key:
            token = object_elem_value.children[0]
            if isinstance(token, Token) and token.type == "STRING_LIT":
                obj_value = token.value  # type: ignore
                return True
        return False

    for _ in tree.find_pred(look_for_obj_key_value):
        if obj_value is not None:
            return obj_value.strip('"')
    raise ValueError(f"Key '{obj_key}' not found in object")


def identifier_name(tree: Tree) -> str | None:
    with suppress(Exception):
        identifier_tree = tree.children[0]
        assert identifier_tree.data == "identifier"
        name_token = identifier_tree.children[0]
        assert isinstance(name_token, Token)
        if name_token.type == "NAME":
            return name_token.value


def find_attribute_object_str_value(tree: Tree, attr_name: str, obj_key: str) -> str:
    def attribute_with_name_mongodbatlas(tree: Tree) -> bool:
        return tree.data == "attribute" and identifier_name(tree) == attr_name

    mongodbatlas_attributes = list(tree.find_pred(attribute_with_name_mongodbatlas))
    assert len(mongodbatlas_attributes) == 1
    attribute = mongodbatlas_attributes[0]
    return find_object_string_value(attribute, obj_key)


def find_attribute_object_str_value2(tree: Tree, attr_name: str, obj_key: str) -> str:
    values_found: list[str] = []

    class AttributeVisitor(DictTransformer):
        def attribute(self, args: list) -> Attribute:
            match args:
                case [match_name, Token("EQ", " ="), obj_dict] if attr_name == match_name and obj_key in obj_dict:
                    values_found.append(obj_dict[obj_key])
            return super().attribute(args)

    AttributeVisitor().transform(tree)
    if len(values_found) == 1:
        return values_found[0]
    if values_found:
        raise ValueError(f"Key '{obj_key}' found multiple times for attribute '{attr_name}'")
    raise ValueError(f"Key '{obj_key}' not found for attribute '{attr_name}'")


def attribute_transfomer(attr_name: str, obj_key: str, new_value: str) -> DictTransformer:
    class AttributeTransformer(DictTransformer):
        def attribute(self, args: List) -> Attribute:
            found_attribute = super().attribute(args)
            if found_attribute.key == attr_name:
                return Attribute(attr_name, found_attribute.value | {obj_key: new_value})
            return found_attribute

    return AttributeTransformer(with_meta=True)


def update_attribute_object_str_value(tree: Tree, attr_name: str, obj_key: str, new_value: str) -> Tree:
    class AttributeUpdater(DictTransformer):
        def attribute(self, args: List) -> Attribute:
            found_attribute = super().attribute(args)
            if found_attribute.key == attr_name:
                return Attribute(attr_name, found_attribute.value | {obj_key: new_value})
            return found_attribute

        def body(self, args: List) -> Dict[str, List]:
            return super().body(args)
            # match args:
            #     case ["mongodbatlas", Token("EQ", " ="), {"source": source, "version": version}]:
            #         # return super().attribute(["mongodbatlas", Token('EQ', ' ='), {"source": source, "version": new_value}])
            #         return Attribute(args[0], {"source": source, "version": new_value})
            #         # return super().attribute(args)
            #     case _:
            #         return super().attribute(args)

    as_dict = AttributeUpdater(with_meta=True).transform(tree)
    return hcl2.api.reverse_transform(as_dict)


def update_attribute_object_str_value_for_block(
    tree: Tree, block_name: str, block_transformer: DictTransformer
) -> Tree:
    class BlockUpdater(Transformer):
        @v_args(tree=True)
        def block(self, block_tree: Tree) -> Tree:
            current_block_name = identifier_name(block_tree)
            if current_block_name == block_name:
                tree_dict = block_transformer.transform(tree)
                tree_modified = hcl2.api.reverse_transform(tree_dict)
                assert isinstance(tree_modified, Tree)
                body_tree = tree_modified.children[0]
                assert isinstance(body_tree, Tree)
                block_tree = body_tree.children[0]
                assert isinstance(block_tree, Tree)
                return block_tree
            return block_tree

    return BlockUpdater().transform(tree)


def test_using_visitor_to_find_data(tmp_path):
    file = tmp_path / "provider.tf"
    file.write_text(_provider_example)
    tree = safe_parse(file)
    assert tree is not None
    assert find_attribute_object_str_value2(tree, "mongodbatlas", "version") == "1.33.0"


def test_using_transformer_to_update_data(tmp_path, file_regression):
    file = tmp_path / "provider.tf"
    file.write_text(_provider_example)
    tree = safe_parse(file)
    assert tree is not None
    # new_tree = update_attribute_object_str_value(tree, "mongodbatlas", "version", "1.34.0")
    new_tree = update_attribute_object_str_value_for_block(
        tree, "terraform", attribute_transfomer("mongodbatlas", "version", "1.34.0")
    )
    new_tf = hcl2.writes(new_tree)  # type: ignore
    file_regression.check(new_tf, extension=".tf")
