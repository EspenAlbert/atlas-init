import logging
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import hcl2
from lark import Token, Tree

logger = logging.getLogger(__name__)


def process_token(node: Token, indent=0):
    logger.debug(f"[{indent}] (token)\t|", " " * indent, node.type, node.value)
    return deepcopy(node)


def is_identifier_variable(tree: Tree | Token) -> bool:
    if not isinstance(tree, Tree):
        return False
    try:
        return tree.children[0].value == "variable"  # type: ignore
    except (IndexError, AttributeError):
        return False


def is_variable_block(tree: Tree) -> bool:
    try:
        return tree.data == "block" and is_identifier_variable(tree.children[0])
    except (IndexError, AttributeError):
        return False


def update_description(tree: Tree, new_descriptions: dict[str, str], existing_names: dict[str, list[str]]) -> Tree:
    new_children = tree.children.copy()
    variable_body = new_children[2]
    assert variable_body.data == "body"
    name = variable_name(new_children[1])
    old_description = read_description_attribute(variable_body)
    existing_names[name].append(old_description)
    new_description = new_descriptions.get(name, "")
    if not new_description:
        logger.warning(f"no description found for variable {name}")
        return tree
    new_children[2] = update_body_with_description(variable_body, new_description)
    return Tree(tree.data, new_children)


def variable_name(token: Token | Tree) -> str:
    if isinstance(token, Token):
        return token.value.strip('"')
    err_msg = f"unexpected token type {type(token)} for variable name"
    raise ValueError(err_msg)


def has_attribute_description(maybe_attribute: Token | Tree) -> bool:
    if not isinstance(maybe_attribute, Tree):
        return False
    return maybe_attribute.data == "attribute" and maybe_attribute.children[0].children[0].value == "description"  # type: ignore


def update_body_with_description(tree: Tree, new_description: str) -> Tree:
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
            variable_name(maybe_attribute.children[-1].children[0])
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


def process_variables(
    node: Tree,
    name_updates: dict[str, str],
    existing_names: dict[str, list[str]],
    depth=0,
) -> Tree:
    new_children = []
    logger.debug(f"[{depth}] (tree)\t|", " " * depth, node.data)
    for child in node.children:
        if isinstance(child, Tree):
            if is_variable_block(child):
                child = update_description(  # noqa: PLW2901
                    child, name_updates, existing_names
                )
            new_children.append(process_variables(child, name_updates, existing_names, depth + 1))
        else:
            new_children.append(process_token(child, depth + 1))

    return Tree(node.data, new_children)


def update_descriptions(tf_path: Path, new_names: dict[str, str]) -> tuple[str, dict[str, list[str]]]:
    tree = hcl2.parses(tf_path.read_text())
    existing_descriptions = defaultdict(list)

    new_tree = process_variables(
        tree,
        new_names,
        existing_descriptions,
    )
    new_tf = hcl2.writes(new_tree)
    return new_tf, existing_descriptions
