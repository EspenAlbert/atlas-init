from collections import defaultdict
import logging
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple
from lark import Token, Transformer, Tree, UnexpectedToken, v_args
from hcl2.transformer import Attribute, DictTransformer
from hcl2.api import reverse_transform, writes, parses
import rich

logger = logging.getLogger(__name__)


def update_attribute_object_str_value_for_block(
    tree: Tree, block_name: str, block_transformer: DictTransformer
) -> Tree:
    class BlockUpdater(Transformer):
        @v_args(tree=True)
        def block(self, block_tree: Tree) -> Tree:
            current_block_name = _identifier_name(block_tree)
            if current_block_name == block_name:
                tree_dict = block_transformer.transform(tree)
                tree_modified = reverse_transform(tree_dict)
                assert isinstance(tree_modified, Tree)
                body_tree = tree_modified.children[0]
                assert isinstance(body_tree, Tree)
                block_tree = body_tree.children[0]
                assert isinstance(block_tree, Tree)
                return block_tree
            return block_tree

    return BlockUpdater().transform(tree)


class AttributeChange(NamedTuple):
    attribute_name: str
    old_value: str | None
    new_value: str


def attribute_transfomer(attr_name: str, obj_key: str, new_value: str) -> tuple[DictTransformer, list[AttributeChange]]:
    changes: list[AttributeChange] = []

    class AttributeTransformer(DictTransformer):
        def attribute(self, args: list) -> Attribute:
            found_attribute = super().attribute(args)
            if found_attribute.key == attr_name:
                attribute_value = found_attribute.value
                if not isinstance(attribute_value, dict):
                    raise ValueError(f"Expected a dict for attribute {attr_name}, but got {type(attribute_value)}")
                old_value = attribute_value.get(obj_key)
                if old_value == new_value:
                    return found_attribute
                changes.append(AttributeChange(attr_name, old_value, new_value))
                return Attribute(attr_name, found_attribute.value | {obj_key: new_value})
            return found_attribute

    return AttributeTransformer(with_meta=True), changes


def variable_reader(tree: Tree) -> dict[str, str | None]:
    """
    Reads the variable names from a parsed HCL2 tree.
    Returns a variable_name -> description, None if no description is found.
    """
    variables: dict[str, str | None] = {}

    class DescriptionReader(DictTransformer):
        def __init__(self, with_meta: bool = False, *, name: str):
            super().__init__(with_meta)
            self.name = name
            self.description: str | None = None

        def attribute(self, args: list) -> Attribute:
            name = args[0]
            if name == "description":
                description = _parse_attribute_value(args)
                self.description = description
            return super().attribute(args)

    class BlockReader(Transformer):
        @v_args(tree=True)
        def block(self, block_tree: Tree) -> Tree:
            current_block_name = _identifier_name(block_tree)
            if current_block_name == "variable":
                variable_name = token_name(block_tree.children[1])
                reader = DescriptionReader(name=variable_name)
                reader.transform(block_tree)
                variables[variable_name] = reader.description
            return block_tree

    BlockReader().transform(tree)
    return variables


def _parse_attribute_value(args: list) -> str:
    description = args[-1]
    return token_name(description) if isinstance(description, Token) else description.strip('"')


def resource_types_vars_usage(tree: Tree) -> dict[str, dict[str, str]]:
    """
    Reads the resource types and their variable usages from a parsed HCL2 tree.
    Returns a dictionary where keys are resource type names and values are dictionaries
    of variable names and the attribute paths they are used in.
    """
    resource_types: dict[str, dict[str, str]] = defaultdict(dict)

    class ResourceBlockAttributeReader(DictTransformer):
        def __init__(self, with_meta: bool = False, resource_type: str = ""):
            self.resource_type = resource_type
            resource_types.setdefault(self.resource_type, {})
            super().__init__(with_meta)

        def attribute(self, args: list) -> Attribute:
            try:
                value = _parse_attribute_value(args)
            except AttributeError:
                return super().attribute(args)
            if value.startswith("var."):
                variable_name = value[4:]
                resource_types[self.resource_type][variable_name] = args[0]
            return super().attribute(args)

    class BlockReader(Transformer):
        @v_args(tree=True)
        def block(self, block_tree: Tree) -> Tree:
            block_resource_name = _block_resource_name(block_tree)
            if block_resource_name is not None:
                ResourceBlockAttributeReader(with_meta=True, resource_type=block_resource_name).transform(block_tree)
            return block_tree

    BlockReader().transform(tree)
    return resource_types


def variable_usages(variable_names: set[str], tree: Tree) -> dict[str, set[str]]:
    usages = defaultdict(set)
    current_resource_type = None

    class ResourceBlockAttributeReader(DictTransformer):
        def attribute(self, args: list) -> Attribute:
            attr_value = args[-1]
            if isinstance(attr_value, str) and attr_value.startswith("var."):
                variable_name = attr_value[4:]
                if variable_name in variable_names:
                    assert current_resource_type is not None, "current_resource_type should not be None"
                    usages[variable_name].add(current_resource_type)
            return super().attribute(args)

    class BlockReader(Transformer):
        @v_args(tree=True)
        def block(self, block_tree: Tree) -> Tree:
            block_resource_name = _block_resource_name(block_tree)
            if block_resource_name is not None and block_resource_name.startswith("mongodbatlas_"):
                nonlocal current_resource_type
                current_resource_type = block_resource_name
                ResourceBlockAttributeReader().transform(block_tree)
            return block_tree

    BlockReader().transform(tree)
    return usages


def _identifier_name(tree: Tree) -> str | None:
    with suppress(Exception):
        identifier_tree = tree.children[0]
        assert identifier_tree.data == "identifier"
        name_token = identifier_tree.children[0]
        assert isinstance(name_token, Token)
        if name_token.type == "NAME":
            return name_token.value


def _block_resource_name(tree: Tree) -> str | None:
    block_name = _identifier_name(tree)
    if block_name != "resource":
        return None
    token = tree.children[1]
    return token_name(token)


def token_name(token):
    assert isinstance(token, Token)
    token_value = token.value
    assert isinstance(token_value, str)
    return token_value.strip('"')


def write_tree(tree: Tree) -> str:
    return writes(tree)


def print_tree(path: Path) -> None:
    tree = safe_parse(path)
    if tree is None:
        return
    logger.info("=" * 10 + f"tree START of {path.parent.name}/{path.name}" + "=" * 10)
    rich.print(tree)
    logger.info("=" * 10 + f"tree END of {path.parent.name}/{path.name}" + "=" * 10)


def safe_parse(path: Path) -> Tree | None:
    try:
        return parses(path.read_text())  # type: ignore
    except UnexpectedToken as e:
        logger.warning(f"failed to parse {path}: {e}")
