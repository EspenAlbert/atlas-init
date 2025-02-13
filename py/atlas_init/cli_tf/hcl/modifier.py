import logging
from copy import deepcopy

from lark import Token, Tree

logger = logging.getLogger(__name__)


def process_token(node: Token, indent=0):
    logger.debug(f"[{indent}] (token)\t|", " " * indent, node.type, node.value)
    return deepcopy(node)


def is_identifier_variable(tree: Tree | Token) -> bool:
    if not isinstance(tree, Tree):
        return False
    try:
        return tree.children[0].value == "variable"
    except (IndexError, AttributeError):
        return False


def is_variable_block(tree: Tree) -> bool:
    try:
        return tree.data == "block" and is_identifier_variable(tree.children[0])
    except (IndexError, AttributeError):
        return False


def update_description(tree: Tree, new_descriptions: dict[str, str]) -> Tree:
    new_children = tree.children.copy()
    assert new_children[2].data == "body"
    name = variable_name(new_children[1]) # type: ignore
    new_description = new_descriptions.get(name, "")
    if not new_description:
        logger.warning(f"no description found for variable {name}")
        return tree
    new_children[2] = update_body_with_description(new_children[2], new_description)
    return Tree(tree.data, new_children)


def variable_name(token: Token) -> str:
    return token.value.strip('"')

def update_body_with_description(tree: Tree, new_description: str) -> Tree:
    new_children = tree.children.copy()
    found_description = False
    for i, maybe_attribute in enumerate(new_children):
        if (
            maybe_attribute.data == "attribute"
            and maybe_attribute.children[0].children[0].value == "description"
        ):
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


def create_description_attribute(description_value: str) -> Tree:
    children = [
        Tree(Token("RULE", "identifier"), [Token("NAME", "description")]),
        Token("EQ", " ="),
        Tree(
            Token("RULE", "expr_term"), [Token("STRING_LIT", f'"{description_value}"')]
        ),
    ]
    return Tree(Token("RULE", "attribute"), children)


def process_variables(node: Tree, name_updates: dict[str, str], depth=0) -> Tree:
    new_children = []
    logger.debug(f"[{depth}] (tree)\t|", " " * depth, node.data)
    for child in node.children:
        if isinstance(child, Tree):
            if is_variable_block(child):
                child = update_description(child, name_updates) # noqa: PLW2901

            new_children.append(process_variables(child, name_updates, depth + 1))

        else:
            new_children.append(process_token(child, depth + 1))

    return Tree(node.data, new_children)
