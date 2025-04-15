package employeeaccessgrant

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

func ResourceSchema(ctx context.Context) schema.Schema {
	return schema.Schema{
		Attributes: map[string]schema.Attribute{
			"cluster_name": schema.StringAttribute{
				Description:         "Human-readable label that identifies this cluster.",
				MarkdownDescription: "Human-readable label that identifies this cluster.",
				Required:            true,
			},
			"expiration": schema.StringAttribute{
				Description:         "Expiration date for the employee access grant.",
				MarkdownDescription: "Expiration date for the employee access grant.",
				Required:            true,
			},
			"grant_type": schema.StringAttribute{
				Description:         "Level of access to grant to MongoDB Employees.",
				MarkdownDescription: "Level of access to grant to MongoDB Employees.",
				Required:            true,
			},
			"project_id": schema.StringAttribute{
				Description:         "Unique 24-hexadecimal digit string that identifies your project. Use the [/groups](#tag/Projects/operation/listProjects) endpoint to retrieve all projects to which the authenticated user has access.\n\n**NOTE**: Groups and projects are synonymous terms. Your group id is the same as your project id. For existing groups, your group/project id remains the same. The resource and corresponding endpoints use the term groups.",
				MarkdownDescription: "Unique 24-hexadecimal digit string that identifies your project. Use the [/groups](#tag/Projects/operation/listProjects) endpoint to retrieve all projects to which the authenticated user has access.\n\n**NOTE**: Groups and projects are synonymous terms. Your group id is the same as your project id. For existing groups, your group/project id remains the same. The resource and corresponding endpoints use the term groups.",
				Required:            true,
			},
		},
	}
}

type TFEmployeeAccessGrantRSModel struct {
	ClusterName types.String `tfsdk:"cluster_name"`
	Expiration  types.String `tfsdk:"expiration"`
	GrantType   types.String `tfsdk:"grant_type"`
	ProjectID   types.String `tfsdk:"project_id"`
}
