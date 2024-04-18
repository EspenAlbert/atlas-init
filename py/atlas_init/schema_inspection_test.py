from atlas_init.schema_inspection import (
    iterate_schema_attributes,
    log_optional_only,
    schema_attributes_plugin_framework,
)

_example_map = """\
import (

	"time"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/mongodb/terraform-provider-mongodbatlas/internal/config"
)
func (r *projectRS) Schema(ctx context.Context, req resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
			"tags": schema.MapAttribute{
				ElementType: types.StringType,
				Optional:    true,
				Computed:    true,
			},
		},"""


def test_iterate_schema_attributes():
    found = list(iterate_schema_attributes(_example_map, "MapAttribute"))
    assert found
    assert found[0].name == "tags"
    assert found[0].optional
    assert found[0].computed


def test_log_optional_only(tmp_path):
    path = tmp_path / "internal/resource_file.go"
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(_example_map)
    log_optional_only(tmp_path)
    assert list(
        schema_attributes_plugin_framework(path, optional=True, computed=True)
    ) == ["tags"]
