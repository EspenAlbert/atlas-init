"""Compat shim for python-hcl2 v7/v8.

Vendors the v7 DictTransformer + Attribute (MIT, depends only on lark)
with additional handlers for v8 grammar rules. Wraps API functions
that changed between v7 and v8.
"""

import json
import re
import sys
from collections import namedtuple
from typing import Any

from lark import Token, Tree
from lark.tree import Meta
from lark.visitors import Discard, Transformer, _DiscardType, v_args

try:
    from hcl2 import parses_to_tree, reconstruct

    _V8 = True
except ImportError:
    _V8 = False

HEREDOC_PATTERN = re.compile(r"<<([a-zA-Z][a-zA-Z0-9._-]+)\n([\s\S]*)\1", re.S)
HEREDOC_TRIM_PATTERN = re.compile(r"<<-([a-zA-Z][a-zA-Z0-9._-]+)\n([\s\S]*)\1", re.S)

START_LINE = "__start_line__"
END_LINE = "__end_line__"

_STRUCTURAL_TOKEN_TYPES = frozenset(
    {
        "LBRACE",
        "RBRACE",
        "LSQB",
        "RSQB",
        "LPAR",
        "RPAR",
        "COMMA",
        "QMARK",
        "COLON",
        "DBLQUOTE",
        "DOT",
        "INTERP_START",
        "FOR",
        "IN",
    }
)

Attribute = namedtuple("Attribute", ("key", "value"))


def _reverse_quotes_within_interpolation(interp_s: str) -> str:
    return re.sub(r"\$\{(.*)}", lambda m: m.group(0).replace('\\"', '"'), interp_s)


def parses_compat(text: str):
    if _V8:
        return parses_to_tree(text)
    from hcl2.api import parses

    return parses(text)


def writes_compat(tree) -> str:
    if _V8:
        return reconstruct(tree)
    from hcl2.api import writes

    return writes(tree)


def reverse_transform_compat(data: dict):
    if _V8:
        return _HCLReverseTransformer().transform(data)
    from hcl2.api import reverse_transform

    return reverse_transform(data)


def _make_identifier(name: str) -> Tree:
    return Tree(Token("RULE", "identifier"), [Token("NAME", name)])


def _make_string_token(value: str) -> Tree:
    if _V8:
        return Tree(
            Token("RULE", "string"),
            [
                Token("DBLQUOTE", '"'),
                Tree(Token("RULE", "string_part"), [Token("STRING_CHARS", value)]),
                Token("DBLQUOTE", '"'),
            ],
        )
    return Tree(Token("RULE", "expr_term"), [Token("STRING_LIT", f'"{value}"')])


def _make_string_label(value: str):
    if _V8:
        return Tree(
            Token("RULE", "string"),
            [
                Token("DBLQUOTE", '"'),
                Tree(Token("RULE", "string_part"), [Token("STRING_CHARS", value)]),
                Token("DBLQUOTE", '"'),
            ],
        )
    return Token("STRING_LIT", f'"{value}"')


_INTERP_RE = re.compile(r"\$\{(.*)}")
_IS_WRAPPED_TF_RE = re.compile(r"\$?\{|}")


class _HCLReverseTransformer:
    """Vendored from python-hcl2 v7 (MIT). Converts a dict back to a lark Tree."""

    def transform(self, hcl_dict: dict) -> Tree:
        body = self._dict_to_body(hcl_dict, level=0)
        return Tree(Token("RULE", "start"), [body])

    @staticmethod
    def _is_string_wrapped_tf(s: str) -> bool:
        if not s.startswith("${") or not s.endswith("}"):
            return False
        nested: list[str] = []
        for m in _IS_WRAPPED_TF_RE.finditer(s):
            if m.group(0) in ("${", "{"):
                nested.append(m.group(0))
            elif m.group(0) == "}":
                nested.pop()
            if len(nested) == 0 and m.end() != len(s):
                return False
        return True

    @classmethod
    def _unwrap_interpolation(cls, value: str) -> str:
        if cls._is_string_wrapped_tf(value):
            return value[2:-1]
        return value

    def _newline(self, level: int) -> Tree:
        return Tree(Token("RULE", "new_line_or_comment"), [Token("NL_OR_COMMENT", f"\n{'  ' * level}")])

    def _is_block(self, value: Any) -> bool:
        if isinstance(value, dict):
            if START_LINE in value or END_LINE in value:
                return True
            try:
                _, body = next(iter(value.items()))
            except StopIteration:
                return False
            return self._is_block(body)
        if isinstance(value, list) and len(value) > 0:
            return self._is_block(value[0])
        return False

    def _block_labels(self, block: dict) -> tuple[list[str], dict]:
        if len(block.keys()) != 1:
            return [], block
        label = list(block)[0]
        body = block[label]
        if START_LINE in body or END_LINE in body:
            return [label], body
        next_labels, body = self._block_labels(body)
        return [label, *next_labels], body

    def _dict_to_body(self, d: dict, level: int) -> Tree:
        children: list[Tree | Token] = []
        if level > 0 and len(d) > 2:
            children.append(self._newline(level))

        for key, value in d.items():
            if key in (START_LINE, END_LINE):
                continue
            ident = _make_identifier(key)
            if self._is_block(value):
                for block_v in value:
                    labels, body_dict = self._block_labels(block_v)
                    label_tokens = [_make_string_label(lbl) for lbl in labels]
                    body = self._dict_to_body(body_dict, level + 1)
                    if _V8:
                        block = Tree(
                            Token("RULE", "block"),
                            [ident, *label_tokens, Token("LBRACE", "{"), body, Token("RBRACE", "}")],
                        )
                    else:
                        block = Tree(Token("RULE", "block"), [ident, *label_tokens, body])
                    children.append(block)
                    nl = self._newline(level - 1)
                    nl.children.append(self._newline(level).children[0])
                    children.append(nl)
            else:
                expr_term = self._value_to_expr(value, level)
                attr = Tree(Token("RULE", "attribute"), [ident, Token("EQ", " ="), expr_term])
                children.append(attr)
                children.append(self._newline(level))

        if (
            children
            and isinstance(children[-1], Tree)
            and isinstance(children[-1].data, Token)
            and children[-1].data.value == "new_line_or_comment"
        ):
            children[-1] = self._newline(level - 1)

        return Tree(Token("RULE", "body"), children)

    def _value_to_expr(self, value: Any, level: int) -> Tree:
        if isinstance(value, list):
            if _V8:
                elems: list[Tree | Token] = [Token("LSQB", "[")]
                for v in value:
                    elems.append(self._value_to_expr(v, level))
                    elems.append(Token("COMMA", ","))
                elems.append(Token("RSQB", "]"))
                return Tree(Token("RULE", "expr_term"), [Tree(Token("RULE", "tuple"), elems)])
            return Tree(
                Token("RULE", "expr_term"),
                [Tree(Token("RULE", "tuple"), [self._value_to_expr(v, level) for v in value])],
            )

        if value is None:
            if _V8:
                return Tree(Token("RULE", "expr_term"), [Tree(Token("RULE", "literal_value"), [Token("NULL", "null")])])
            return Tree(Token("RULE", "expr_term"), [_make_identifier("null")])

        if isinstance(value, dict):
            elems = []
            if _V8 and value:
                elems.append(Token("LBRACE", "{"))
            if value:
                elems.append(self._newline(level + 1))
            for i, (k, v) in enumerate(value.items()):
                if k in (START_LINE, END_LINE):
                    continue
                k = self._unwrap_interpolation(k)
                val_expr = self._value_to_expr(v, level + 1)
                if _V8:
                    elem_key = Tree(
                        Token("RULE", "object_elem_key"), [Tree(Token("RULE", "expr_term"), [_make_identifier(k)])]
                    )
                else:
                    elem_key = Tree(Token("RULE", "object_elem_key"), [_make_identifier(k)])
                elems.append(Tree(Token("RULE", "object_elem"), [elem_key, Token("EQ", " ="), val_expr]))
                remaining = len([kk for kk in list(value.keys())[i + 1 :] if kk not in (START_LINE, END_LINE)])
                if remaining:
                    elems.append(self._newline(level + 1))
                else:
                    elems.append(self._newline(level))
            if _V8 and value:
                elems.append(Token("RBRACE", "}"))
            return Tree(Token("RULE", "expr_term"), [Tree(Token("RULE", "object"), elems)])

        if isinstance(value, bool):
            if _V8:
                tok_type = "TRUE" if value else "FALSE"
                return Tree(
                    Token("RULE", "expr_term"),
                    [Tree(Token("RULE", "literal_value"), [Token(tok_type, "true" if value else "false")])],
                )
            return Tree(Token("RULE", "expr_term"), [_make_identifier("true" if value else "false")])

        if isinstance(value, int):
            return Tree(
                Token("RULE", "expr_term"), [Tree(Token("RULE", "int_lit"), [Token("DECIMAL", d) for d in str(value)])]
            )

        if isinstance(value, str):
            if self._is_string_wrapped_tf(value):
                wrapped = _INTERP_RE.match(value).group(1)  # type: ignore
                ast = parses_compat(f"value = {wrapped}")
                body = ast.children[0]
                attr = body.children[0]
                return attr.children[2]
            if _V8:
                escaped = json.dumps(value)
                escaped = _reverse_quotes_within_interpolation(escaped)
                inner = escaped[1:-1]
                return Tree(Token("RULE", "expr_term"), [_make_string_token(inner)])
            escaped = json.dumps(value)
            escaped = _reverse_quotes_within_interpolation(escaped)
            return Tree(Token("RULE", "expr_term"), [Token("STRING_LIT", escaped)])

        raise RuntimeError(f"Unknown type to transform {type(value)}")


def _is_structural_token(arg: Any) -> bool:
    return isinstance(arg, Token) and arg.type in _STRUCTURAL_TOKEN_TYPES


class DictTransformer(Transformer):
    with_meta: bool

    @staticmethod
    def is_type_keyword(value: str) -> bool:
        return value in {"bool", "number", "string"}

    def __init__(self, with_meta: bool = False):
        self.with_meta = with_meta
        super().__init__()

    def _strip_all(self, args: list) -> list:
        return [a for a in args if a is not Discard and a != "\n" and not _is_structural_token(a)]

    # --- v8-only grammar rules (never called on v7 trees) ---

    def literal_value(self, args: list) -> str:
        return str(args[0])

    def string_part(self, args: list) -> str:
        return str(args[0])

    def string(self, args: list) -> str:
        parts = [a for a in args if not (isinstance(a, Token) and a.type == "DBLQUOTE")]
        return '"' + "".join(str(p) for p in parts) + '"'

    def interpolation(self, args: list) -> str:
        parts = self._strip_all(args)
        return "${" + "".join(str(p) for p in parts) + "}"

    def object_elem_key(self, args: list) -> str:
        return str(args[0])

    def template_string(self, args: list) -> str:
        return "".join(str(a) for a in args)

    # --- v7-only grammar rules (never called on v8 trees) ---

    def string_with_interpolation(self, args: list) -> str:
        return '"' + ("".join(args)) + '"'

    def interpolation_maybe_nested(self, args: list) -> str:
        return "${" + ("".join(args)) + "}"

    def object_elem_key_dot_accessor(self, args: list) -> str:
        return "".join(args)

    def provider_function_call(self, args: list) -> str:
        args = self.strip_new_line_tokens(args)
        args_str = ""
        if len(args) > 5:
            args_str = ", ".join([self.to_tf_inline(arg) for arg in args[5] if arg is not Discard])
        provider_func = "::".join([args[0], args[2], args[4]])
        return f"{provider_func}({args_str})"

    # --- Shared handlers (work on both v7 and v8 trees) ---

    def float_lit(self, args: list) -> float:
        return float("".join([self.to_tf_inline(arg) for arg in args]))

    def int_lit(self, args: list) -> int:
        return int("".join([self.to_tf_inline(arg) for arg in args]))

    def expr_term(self, args: list) -> Any:
        args = self._strip_all(args)
        if args[0] == "true":
            return True
        if args[0] == "false":
            return False
        if args[0] == "null":
            return None
        if args[0] == "(" and args[-1] == ")":
            return "".join(str(arg) for arg in args)
        return args[0]

    def index_expr_term(self, args: list) -> str:
        args = self.strip_new_line_tokens(args)
        return f"{args[0]}{args[1]}"

    def index(self, args: list) -> str:
        args = self._strip_all(args)
        return f"[{args[0]}]"

    def get_attr_expr_term(self, args: list) -> str:
        return f"{args[0]}{args[1]}"

    def get_attr(self, args: list) -> str:
        parts = self._strip_all(args)
        return f".{parts[0]}"

    def attr_splat_expr_term(self, args: list) -> str:
        return f"{args[0]}{args[1]}"

    def attr_splat(self, args: list) -> str:
        args_str = "".join(self.to_tf_inline(arg) for arg in args)
        return f".*{args_str}"

    def full_splat_expr_term(self, args: list) -> str:
        return f"{args[0]}{args[1]}"

    def full_splat(self, args: list) -> str:
        args_str = "".join(self.to_tf_inline(arg) for arg in args)
        return f"[*]{args_str}"

    def tuple(self, args: list) -> list:
        return [self.to_string_dollar(arg) for arg in self._strip_all(args)]

    def object_elem(self, args: list) -> dict:
        if isinstance(args[0], Token) and args[0].type == "LPAR":
            key = self.strip_quotes(str(args[1].children[0]))
            key = f"({key})"
            key = self.to_string_dollar(key)
            value = args[4]
        elif isinstance(args[0], Tree):
            # v7: args[0] is a Tree with children
            key = self.strip_quotes(str(args[0].children[0]))
            value = args[2]
        else:
            # v8: [key_str, Token(EQ), value]
            key = self.strip_quotes(str(args[0]))
            value = args[2]
        value = self.to_string_dollar(value)
        return {key: value}

    def object(self, args: list) -> dict:
        args = self._strip_all(args)
        result: dict[str, Any] = {}
        for arg in args:
            result.update(arg)
        return result

    def function_call(self, args: list) -> str:
        args = self._strip_all(args)
        args_str = ""
        if len(args) > 1:
            args_str = ", ".join([self.to_tf_inline(arg) for arg in args[1] if arg is not Discard])
        return f"{args[0]}({args_str})"

    def arguments(self, args: list) -> list:
        return self.process_nulls(args)

    @v_args(meta=True)
    def block(self, meta: Meta, args: list) -> dict:
        args = self._strip_all(args)
        *block_labels, block_body = args
        result: dict[str, Any] = block_body
        if self.with_meta:
            result.update({START_LINE: meta.line, END_LINE: meta.end_line})
        for label in reversed(block_labels):
            label_str = self.strip_quotes(label)
            result = {label_str: result}
        return result

    def attribute(self, args: list) -> Attribute:
        key = str(args[0])
        if key.startswith('"') and key.endswith('"'):
            key = key[1:-1]
        value = self.to_string_dollar(args[2])
        return Attribute(key, value)

    def conditional(self, args: list) -> str:
        args = self._strip_all(args)
        args = self.process_nulls(args)
        return f"{args[0]} ? {args[1]} : {args[2]}"

    def binary_op(self, args: list) -> str:
        return " ".join([self.to_tf_inline(arg) for arg in args])

    def unary_op(self, args: list) -> str:
        args = self.process_nulls(args)
        return "".join([self.to_tf_inline(arg) for arg in args])

    def binary_term(self, args: list) -> str:
        args = self.strip_new_line_tokens(args)
        args = self.process_nulls(args)
        return " ".join([self.to_tf_inline(arg) for arg in args])

    def body(self, args: list) -> dict[str, list]:
        args = self.strip_new_line_tokens(args)
        attributes = set()
        result: dict[str, Any] = {}
        for arg in args:
            if isinstance(arg, Attribute):
                if arg.key in result:
                    raise RuntimeError(f"{arg.key} already defined")
                result[arg.key] = arg.value
                attributes.add(arg.key)
            elif isinstance(arg, dict):
                for key, value in arg.items():
                    key = str(key)
                    if key in result:
                        if key in attributes:
                            raise RuntimeError(f"{key} already defined")
                        result[key].append(value)
                    else:
                        result[key] = [value]
        return result

    def start(self, args: list) -> dict:
        args = self.strip_new_line_tokens(args)
        return args[0]

    def binary_operator(self, args: list) -> str:
        return str(args[0])

    def heredoc_template(self, args: list) -> str:
        match = HEREDOC_PATTERN.match(str(args[0]))
        if not match:
            raise RuntimeError(f"Invalid Heredoc token: {args[0]}")
        trim_chars = "\n\t "
        return f'"{match.group(2).rstrip(trim_chars)}"'

    def heredoc_template_trim(self, args: list) -> str:
        match = HEREDOC_TRIM_PATTERN.match(str(args[0]))
        if not match:
            raise RuntimeError(f"Invalid Heredoc token: {args[0]}")
        trim_chars = "\n\t "
        text = match.group(2).rstrip(trim_chars)
        lines = text.split("\n")
        min_spaces = sys.maxsize
        for line in lines:
            leading_spaces = len(line) - len(line.lstrip(" "))
            min_spaces = min(min_spaces, leading_spaces)
        lines = [line[min_spaces:] for line in lines]
        return '"%s"' % "\n".join(lines)

    def new_line_or_comment(self, args: list) -> _DiscardType:
        return Discard

    def for_tuple_expr(self, args: list) -> str:
        args = self._strip_all(args)
        for_expr = " ".join([self.to_tf_inline(arg) for arg in args])
        return f"[{for_expr}]"

    def for_intro(self, args: list) -> str:
        args = self._strip_all(args)
        return " ".join([self.to_tf_inline(arg) for arg in args])

    def for_cond(self, args: list) -> str:
        args = self._strip_all(args)
        return " ".join([self.to_tf_inline(arg) for arg in args])

    def for_object_expr(self, args: list) -> str:
        args = self._strip_all(args)
        for_expr = " ".join([self.to_tf_inline(arg) for arg in args])
        return f"{{{for_expr}}}"

    def strip_new_line_tokens(self, args: list) -> list:
        return [arg for arg in args if arg != "\n" and arg is not Discard]

    def to_string_dollar(self, value: Any) -> Any:
        if isinstance(value, str):
            if value.startswith("${") and value.endswith("}"):
                return value
            if value.startswith('"') and value.endswith('"'):
                value = str(value)[1:-1]
                return self.process_escape_sequences(value)
            if self.is_type_keyword(value):
                return value
            return f"${{{value}}}"
        return value

    def strip_quotes(self, value: Any) -> Any:
        if isinstance(value, str):
            if value.startswith('"') and value.endswith('"'):
                value = str(value)[1:-1]
                return self.process_escape_sequences(value)
        return value

    def process_escape_sequences(self, value: str) -> str:
        if isinstance(value, str):
            value = value.replace("\\n", "\n")
            value = value.replace("\\r", "\r")
            value = value.replace("\\t", "\t")
            value = value.replace('\\"', '"')
            value = value.replace("\\\\", "\\")
        return value

    def process_nulls(self, args: list) -> list:
        return ["null" if arg is None else arg for arg in args]

    def to_tf_inline(self, value: Any) -> str:
        if isinstance(value, dict):
            dict_v = json.dumps(value)
            return _reverse_quotes_within_interpolation(dict_v)
        if isinstance(value, list):
            value = [self.to_tf_inline(item) for item in value]
            return f"[{', '.join(value)}]"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        if value is None:
            return "None"
        raise RuntimeError(f"Invalid type to convert to inline HCL: {type(value)}")

    def identifier(self, value: Any) -> Any:
        return str(value[0])
