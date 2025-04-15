import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(eq=True, frozen=False)
class Block:
    name: str
    line_start: int
    level: int
    hcl: str = ""
    line_end: int = -1

    def __post_init__(self):
        self.name = self.name.strip()

    def end_block(self, line_end: int, hcl: str):
        self.line_end = line_end
        self.hcl = hcl

    @property
    def _lines(self) -> list[str]:
        return self.hcl.splitlines()

    def content_lines(self) -> list[tuple[int, str]]:
        return list(enumerate(self._lines[1:-1], start=1))

    def read_lines(self, start: int, end: int) -> list[str]:
        return self._lines[start : end + 1]

    def __hash__(self) -> int:
        return hash((self.name, self.line_start, self.line_end))


@dataclass
class ResourceBlock(Block):
    type: str = ""

    def __post_init__(self):
        self.name = self.name.strip()
        self.type = self.type.strip()

    def __hash__(self) -> int:
        return hash((self.name, self.type))

    def __str__(self) -> str:
        return f"{self.resource_id} @ L{self.line_start}-{self.line_end}"

    @property
    def resource_id(self) -> str:
        return f"{self.type}.{self.name}"


_resource_pattern = re.compile(r"resource\s+\"(?P<type>[^\"]+)\"\s+\"(?P<name>[^\"]+)\"\s+\{")


def iter_resource_blocks(hcl_config: str) -> Iterable[ResourceBlock]:
    # support line_nr indexing
    lines = ["", *hcl_config.splitlines()]
    current_block = None
    for i, line in enumerate(lines):
        if current_block is not None:
            if line.rstrip() == "}":
                current_block.end_block(i, "\n".join(lines[current_block.line_start : i + 1]))
                yield current_block
                current_block = None
            continue
        if match := _resource_pattern.match(line):
            assert current_block is None, "Nested blocks resource blocks are not supported"
            current_block = ResourceBlock(
                name=match.group("name"),
                type=match.group("type"),
                line_start=i,
                level=0,
            )
    if current_block is not None:
        err_msg = "Final resource block not closed"
        raise ValueError(err_msg)


_block_pattern = re.compile(r"(?P<name>[^\{]+)[\s=]+\{")


def iter_blocks(block: Block, level: int | None = None) -> Iterable[Block]:
    level = level or block.level + 1
    line_level_start_names: dict[int, tuple[int, str]] = {}
    current_level = level
    for line_nr, line in block.content_lines():
        if match := _block_pattern.match(line):
            line_level_start_names[current_level] = (line_nr, match.group("name"))
            current_level += 1
        if line.strip() == "}":
            current_level -= 1
            start_line_nr_name = line_level_start_names.pop(current_level, None)
            if start_line_nr_name is None:
                raise ValueError(f"Unbalanced block @ {line_nr} in {block.name}")
            start_line_nr, name = start_line_nr_name
            if level == current_level:
                block_lines: list[str] = block.read_lines(start_line_nr, line_nr)
                if "=" in block_lines[0]:
                    continue
                yield Block(
                    name=name,
                    line_start=start_line_nr,
                    level=level,
                    line_end=line_nr,
                    hcl="\n".join(block_lines),
                )
    if line_level_start_names.get(level) is not None:
        raise ValueError(f"Unfinished block @ {line_nr} in {block.name} at level {level}")  # pyright: ignore


def hcl_attrs(block: Block) -> dict[str, str]:
    nested_blocks = list(iter_blocks(block, level=block.level + 1))
    block_lines = as_block_lines(nested_blocks)
    return _hcl_attrs(block, block_lines)


def _hcl_attrs(block: Block, block_lines: set[int]) -> dict[str, str]:
    attrs = defaultdict(list)
    attr_name: str | None = None
    for line_nr, line in block.content_lines():
        if line_nr in block_lines:
            continue
        if "=" in line:
            assert attr_name is None, f"unfinished attribute {attr_name}, new attribute at {line_nr}"
            attr_name, attr_value = line.split("=", 1)
            attrs[attr_name.strip()] = [attr_value.strip()]
            if line.rstrip().endswith(("{", "[", ",")):
                raise ValueError(f"unsupported nested attribute assignment on {line_nr} in block: {block.name}")
            attr_name = None
    return {k: "\n".join(v) for k, v in attrs.items()}


def as_block_lines(blocks: list[Block]) -> set[int]:
    block_lines = set()
    for block in blocks:
        block_lines.update(set(range(block.line_start, block.line_end)))
    return block_lines
