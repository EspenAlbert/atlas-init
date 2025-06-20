import logging
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Callable

import hcl2
from lark import Token, Tree

from atlas_init.cli_tf.hcl.modifier2 import safe_parse

logger = logging.getLogger(__name__)

BLOCK_TYPE_VARIABLE = "variable"
BLOCK_TYPE_OUTPUT = "output"


def process_token(node: Token, indent=0):
    debug_log(f"token:{node.type}:{node.value}", indent)
    return deepcopy(node)


def debug_log(message: str, depth=0):
    logger.debug("  " * depth + message.rstrip("\n"))


def is_identifier_block_type(tree: Tree | Token, block_type: str) -> bool:
    if not isinstance(tree, Tree):
        return False
    try:
        return tree.children[0].value == block_type  # type: ignore
    except (IndexError, AttributeError):
        return False


def is_block_type(tree: Tree, block_type: str) -> bool:
    try:
        return tree.data == "block" and is_identifier_block_type(tree.children[0], block_type)
    except (IndexError, AttributeError):
        return False


def update_description(tree: Tree, new_descriptions: dict[str, str], existing_names: dict[str, list[str]]) -> Tree:
    new_children = tree.children.copy()
    variable_body = new_children[2]
    assert variable_body.data == "body"
    name = token_name(new_children[1])
    old_description = read_description_attribute(variable_body)
    existing_names[name].append(old_description)
    new_description = new_descriptions.get(name, "")
    if not new_description:
        debug_log(f"no description found for variable {name}", 0)
        return tree
    new_children[2] = update_body_with_description(variable_body, new_description)
    return Tree(tree.data, new_children)


def token_name(token: Token | Tree) -> str:
    if isinstance(token, Token):
        return token.value.strip('"')
    if isinstance(token, Tree) and token.data == "identifier":
        return token.children[0].value.strip('"')  # type: ignore
    err_msg = f"unexpected token type {type(token)} for token name"
    raise ValueError(err_msg)


def has_attribute_description(maybe_attribute: Token | Tree) -> bool:
    if not isinstance(maybe_attribute, Tree):
        return False
    return maybe_attribute.data == "attribute" and maybe_attribute.children[0].children[0].value == "description"  # type: ignore


def update_body_with_description(tree: Tree, new_description: str) -> Tree:
    new_description = new_description.replace('"', '\\"')
    new_children = tree.children.copy()
    found_description = False
    for i, maybe_attribute in enumerate(new_children):
        if has_attribute_description(maybe_attribute):
            found_description = True
            new_children[i] = create_description_attribute(new_description)
    if not found_description:
        new_children.insert(0, new_line())
        new_children.insert(1, create_description_attribute(new_description))
    return Tree(tree.data, new_children)


def new_line() -> Tree:
    return Tree(
        Token("RULE", "new_line_or_comment"),
        [Token("NL_OR_COMMENT", "\n  ")],
    )


def read_description_attribute(tree: Tree) -> str:
    return next(
        (
            token_name(maybe_attribute.children[-1].children[0])
            for maybe_attribute in tree.children
            if has_attribute_description(maybe_attribute)
        ),
        "",
    )


def create_description_attribute(description_value: str) -> Tree:
    children = [
        Tree(Token("RULE", "identifier"), [Token("NAME", "description")]),
        Token("EQ", " ="),
        Tree(Token("RULE", "expr_term"), [Token("STRING_LIT", f'"{description_value}"')]),
    ]
    return Tree(Token("RULE", "attribute"), children)


def process_generic(
    node: Tree,
    tree_match: Callable[[Tree], bool],
    tree_call: Callable[[Tree], Tree],
    depth=0,
):
    new_children = []
    debug_log(f"tree:{node.data}", depth)
    for child in node.children:
        if isinstance(child, Tree):
            if tree_match(child):
                child = tree_call(child)
            new_children.append(process_generic(child, tree_match, tree_call, depth + 1))
        else:
            new_children.append(process_token(child, depth + 1))
    return Tree(node.data, new_children)


def process_descriptions(
    node: Tree,
    name_updates: dict[str, str],
    existing_names: dict[str, list[str]],
    depth=0,
    *,
    block_type: str,
) -> Tree:
    def tree_match(tree: Tree) -> bool:
        return is_block_type(tree, block_type)

    def tree_call(tree: Tree) -> Tree:
        return update_description(tree, name_updates, existing_names)

    return process_generic(
        node,
        tree_match,
        tree_call,
        depth=depth,
    )


def update_descriptions(tf_path: Path, new_names: dict[str, str], block_type: str) -> tuple[str, dict[str, list[str]]]:
    tree = safe_parse(tf_path)
    if tree is None:
        return "", {}
    existing_descriptions = defaultdict(list)
    new_tree = process_descriptions(
        tree,
        new_names,
        existing_descriptions,
        block_type=block_type,
    )
    new_tf = hcl2.writes(new_tree)  # type: ignore
    return new_tf, existing_descriptions


def _block_name_body(tree: Tree) -> tuple[str, Tree]:
    try:
        _, name_token, body = tree.children
        name = token_name(name_token)
    except (IndexError, AttributeError) as e:
        raise ValueError("unexpected block structure") from e
    return name, body


def _read_attribute(tree_body: Tree, attribute_name: str) -> Tree | None:
    for attribute in tree_body.children:
        if not isinstance(attribute, Tree):
            continue
        if attribute.data != "attribute":
            continue
        attr_identifier, _, attr_value = attribute.children
        if token_name(attr_identifier.children[0]) != attribute_name:
            continue
        return attr_value


def _is_object(tree_body: Tree) -> bool:
    if not isinstance(tree_body, Tree):
        return False
    if len(tree_body.children) != 1:
        return False
    if not isinstance(tree_body.children[0], Tree):
        return False
    return tree_body.children[0].data == "object"


def _read_object_elems(tree_body: Tree) -> list[Tree]:
    object_elements = []
    for obj_child in tree_body.children[0].children:
        if not isinstance(obj_child, Tree):
            continue
        if obj_child.data != "object_elem":
            continue
        object_elements.append(obj_child)
    return object_elements


def _read_object_elem_key(tree_body: Tree) -> str:
    name_tree, _, _ = tree_body.children
    return token_name(name_tree.children[0])


def read_block_attribute_object_keys(tf_path: Path, block_type: str, block_name: str, block_key: str) -> list[str]:
    tree = safe_parse(tf_path)
    if tree is None:
        return []
    env_vars = []

    def extract_env_vars(tree: Tree) -> bool:
        if not is_block_type(tree, block_type):
            return False
        name, body = _block_name_body(tree)
        if name != block_name:
            return False
        attribute_value = _read_attribute(body, block_key)
        if not attribute_value:
            return False
        if not _is_object(attribute_value):
            return False
        object_elements = _read_object_elems(attribute_value)
        for obj_elem in object_elements:
            key = _read_object_elem_key(obj_elem)
            env_vars.append(key)
        return False

    def tree_call(tree: Tree) -> Tree:
        return tree

    process_generic(
        tree,
        extract_env_vars,
        tree_call,
    )
    return env_vars
