from dataclasses import dataclass  # noqa: F401
from typing import Optional  # noqa: F401

from atlas_init.tf_ext.py_gen import ensure_dataclass_use_conversion

_dataclasses_py = """
@dataclass
class _Nested:
    name: str
    age: int
"""
exec(_dataclasses_py, globals())

_dataclasses_py2 = """
@dataclass
class _MyCls:
    string: str
    number: int
    floating_point: float
    boolean: bool
    flat_list: list[str]
    flat_dict: dict[str, str]
    nested_dict: dict[str, _Nested]
    nested_list: list[_Nested]
    optional_nested: Optional[_Nested]
    required_nested: _Nested
    optional_string: Optional[str] = None
    optional_number: Optional[int] = None
    optional_floating_point: Optional[float] = None
    optional_boolean: Optional[bool] = None
    optional_flat_list: Optional[list[str]] = None
    optional_flat_dict: Optional[dict[str, str]] = None
    optional_nested_dict: Optional[dict[str, _Nested]] = None
    optional_nested_list: Optional[list[_Nested]] = None


"""
exec(_dataclasses_py2, globals())

_extra_imports = "from typing import Optional\nfrom dataclasses import dataclass\n"


def test_make_post_init_line_from_field(tmp_path, file_regression):
    py_path = tmp_path / "test.py"
    py_path.write_text(_extra_imports + _dataclasses_py + _dataclasses_py2)
    dataclasses = {key: globals()[key] for key in ("_MyCls", "_Nested")}
    ensure_dataclass_use_conversion(dataclasses, py_path, set())
    file_regression.check(py_path.read_text(), basename="post_init_generation", extension=".py")
