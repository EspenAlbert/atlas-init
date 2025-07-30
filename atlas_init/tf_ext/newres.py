import logging
from pathlib import Path
from ask_shell import run_and_wait
from ask_shell.settings import clean_dir
from model_lib import dump
from zero_3rdparty import humps
from zero_3rdparty.file_utils import ensure_parents_write_text
from atlas_init.tf_ext.provider_schema import AtlasSchemaInfo, parse_atlas_schema

logger = logging.getLogger(__name__)


def prepare_newres(path: Path):
    if not path.exists():
        path.parent.mkdir(exist_ok=True, parents=True)
        run_and_wait(f"git clone https://github.com/lonegunmanb/newres.git {path.name}", cwd=path.parent)
    schema = parse_atlas_schema()
    modify_newres(path, schema)
    run_and_wait("go fmt ./...", cwd=path)


def _template_resource_go(resource_type: str, resource_type_schema_json: str) -> str:
    json_backticks_escaped = resource_type_schema_json.replace("`", '`+"`"+`')
    return f"""
package custom
import (
  "encoding/json"
  tfjson "github.com/hashicorp/terraform-json"
)

const {humps.camelize(resource_type)} = `
{json_backticks_escaped}
`
func {humps.camelize(resource_type)}Schema() *tfjson.Schema {{
\tvar result tfjson.Schema
\t_ = json.Unmarshal([]byte({humps.camelize(resource_type)}), &result)
\treturn &result
}}

"""


def _register_go(resources: list[str]) -> str:
    resources_key_assignments = "\n".join(
        f'  Resources["{resource}"] = {humps.camelize(resource)}Schema()' for resource in resources
    )
    return f"""
package custom
import (
  tfjson "github.com/hashicorp/terraform-json"
)
var Resources map[string]*tfjson.Schema

func init() {{
  Resources = make(map[string]*tfjson.Schema)
  {resources_key_assignments}  
}}

"""


def modify_newres(new_res_path: Path, schema: AtlasSchemaInfo):
    custom_resource_dir = new_res_path / "pkg/custom"
    clean_dir(custom_resource_dir)
    for resource_type, resource_type_schema in schema.raw_resource_schema.items():
        schema_json = dump(resource_type_schema, format="pretty_json")
        resource_type_go = _template_resource_go(resource_type, schema_json)
        resource_type_file = custom_resource_dir / f"{resource_type}.go"
        ensure_parents_write_text(resource_type_file, resource_type_go)
    register_go = _register_go(schema.resource_types)
    register_file = custom_resource_dir / "register.go"
    ensure_parents_write_text(register_file, register_go)
    logger.info(f"Custom resource files written to {custom_resource_dir}")
    add_to_register_go(new_res_path)


def add_to_register_go(new_res_path: Path):
    register_go = new_res_path / "pkg/resource_register.go"
    in_text = register_go.read_text()
    replacements = {
        "import (": 'import (\n\t"github.com/lonegunmanb/newres/v3/pkg/custom"',
        "resources := []map[string]*tfjson.Schema{": "resources := []map[string]*tfjson.Schema{\n\t\tcustom.Resources,",
    }
    out_text = in_text
    for old, new in replacements.items():
        if new in out_text:
            continue
        out_text = out_text.replace(old, new)
    ensure_parents_write_text(register_go, out_text)
    logger.info(f"Added custom resources to {register_go}")
