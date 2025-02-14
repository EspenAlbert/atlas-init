import logging
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import hcl2
from lark import Token, Tree, UnexpectedToken

logger = logging.getLogger(__name__)

BLOCK_TYPE_VARIABLE = "variable"
BLOCK_TYPE_OUTPUT = "output"


def process_token(node: Token, indent=0):
    logger.debug(f"[{indent}] (token)\t|", " " * indent, node.type, node.value)
    return deepcopy(node)


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
        logger.debug(f"no description found for variable {name}")
        return tree
    new_children[2] = update_body_with_description(variable_body, new_description)
    return Tree(tree.data, new_children)


def token_name(token: Token | Tree) -> str:
    if isinstance(token, Token):
        return token.value.strip('"')
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


def process_descriptions(
    node: Tree,
    name_updates: dict[str, str],
    existing_names: dict[str, list[str]],
    depth=0,
    *,
    block_type: str,
) -> Tree:
    new_children = []
    logger.debug(f"[{depth}] (tree)\t|", " " * depth, node.data)
    for child in node.children:
        if isinstance(child, Tree):
            if is_block_type(child, block_type):
                child = update_description(  # noqa: PLW2901
                    child, name_updates, existing_names
                )
            new_children.append(
                process_descriptions(child, name_updates, existing_names, depth + 1, block_type=block_type)
            )
        else:
            new_children.append(process_token(child, depth + 1))

    return Tree(node.data, new_children)


def update_descriptions(tf_path: Path, new_names: dict[str, str], block_type: str) -> tuple[str, dict[str, list[str]]]:
    try:
        tree = hcl2.parses(tf_path.read_text())
    except UnexpectedToken as e:
        logger.warning(f"failed to parse {tf_path}: {e}")
        return "", {}
    existing_descriptions = defaultdict(list)
    new_tree = process_descriptions(
        tree,
        new_names,
        existing_descriptions,
        block_type=block_type,
    )
    new_tf = hcl2.writes(new_tree)
    return new_tf, existing_descriptions
