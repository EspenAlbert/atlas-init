package streamprocessor

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/mongodb/terraform-provider-mongodbatlas/internal/common/schemafunc"
	"github.com/mongodb/terraform-provider-mongodbatlas/internal/common/validate"
)

func ResourceSchema(ctx context.Context) schema.Schema {
	return schema.Schema{
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Description: "Unique 24-hexadecimal character string that identifies the stream processor.",
				Computed:    true,
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"instance_name": schema.StringAttribute{
				Description: "Human-readable label that identifies the stream instance.",
				Required:    true,
			},
			"options": schema.SingleNestedAttribute{
				Description: "Optional configuration for the stream processor.",
				Optional:    true,
				Attributes: map[string]schema.Attribute{
					"dlq": schema.SingleNestedAttribute{
						Description: "Dead letter queue for the stream processor.",
						Required:    true,
						Attributes: map[string]schema.Attribute{
							"coll": schema.StringAttribute{
								Description: "Name of the collection that will be used for the DLQ.",
								Required:    true,
							},
							"connection_name": schema.StringAttribute{
								Description: "Connection name that will be used to write DLQ messages to. Has to be an Atlas connection.",
								Required:    true,
							},
							"db": schema.StringAttribute{
								Description: "Name of the database that will be used for the DLQ.",
								Required:    true,
							},
						},
					},
				},
			},
			"pipeline": schema.StringAttribute{
				Description: "Stream aggregation pipeline you want to apply to your streaming data.",
				Required:    true,
				Validators: []validator.String{
					validate.StringIsJSON(),
				},
				PlanModifiers: []planmodifier.String{
					schemafunc.DiffSuppressJSON(),
				},
			},
			"processor_name": schema.StringAttribute{
				Description: "Human-readable name of the stream processor.",
				Required:    true,
			},
			"project_id": schema.StringAttribute{
				Description: "Unique 24-hexadecimal digit string that identifies your project. Use the [/groups](#tag/Projects/operation/listProjects) endpoint to retrieve all projects to which the authenticated user has access.\n\n**NOTE**: Groups and projects are synonymous terms. Your group id is the same as your project id. For existing groups, your group/project id remains the same. The resource and corresponding endpoints use the term groups.",
				Required:    true,
			},
			"state": schema.StringAttribute{
				Description: "The state of the stream processor.",
				Optional:    true,
				Computed:    true,
			},
			"stats": schema.StringAttribute{
				Description: "The stats associated with the stream processor.",
				Computed:    true,
			},
		},
	}
}

type TFStreamProcessorRSModel struct {
	ID            types.String `tfsdk:"id"`
	InstanceName  types.String `tfsdk:"instance_name"`
	Options       types.Object `tfsdk:"options"`
	Pipeline      types.String `tfsdk:"pipeline"`
	ProcessorName types.String `tfsdk:"processor_name"`
	ProjectID     types.String `tfsdk:"project_id"`
	State         types.String `tfsdk:"state"`
	Stats         types.String `tfsdk:"stats"`
}

type TFOptionsModel struct {
	Dlq types.Object `tfsdk:"dlq"`
}

var OptionsObjectType = types.ObjectType{AttrTypes: map[string]attr.Type{
	"dlq": DlqObjectType,
}}

type TFDlqModel struct {
	Coll           types.String `tfsdk:"coll"`
	ConnectionName types.String `tfsdk:"connection_name"`
	DB             types.String `tfsdk:"db"`
}

var DlqObjectType = types.ObjectType{AttrTypes: map[string]attr.Type{
	"coll":            types.StringType,
	"connection_name": types.StringType,
	"db":              types.StringType,
}}
