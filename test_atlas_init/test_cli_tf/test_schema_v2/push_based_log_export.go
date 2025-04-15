package pushbasedlogexport

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

func ResourceSchema(ctx context.Context) schema.Schema {
	return schema.Schema{
		Attributes: map[string]schema.Attribute{
			"bucket_name": schema.StringAttribute{
				Description:         "The name of the bucket to which the agent will send the logs to.",
				MarkdownDescription: "The name of the bucket to which the agent will send the logs to.",
				Optional:            true,
				Computed:            true,
			},
			"create_date": schema.StringAttribute{
				Description:         "Date and time that this feature was enabled on.",
				MarkdownDescription: "Date and time that this feature was enabled on.",
				Computed:            true,
			},
			"group_id": schema.StringAttribute{
				Description:         "Unique 24-hexadecimal digit string that identifies your project. Use the [/groups](#tag/Projects/operation/listProjects) endpoint to retrieve all projects to which the authenticated user has access.\n\n**NOTE**: Groups and projects are synonymous terms. Your group id is the same as your project id. For existing groups, your group/project id remains the same. The resource and corresponding endpoints use the term groups.",
				MarkdownDescription: "Unique 24-hexadecimal digit string that identifies your project. Use the [/groups](#tag/Projects/operation/listProjects) endpoint to retrieve all projects to which the authenticated user has access.\n\n**NOTE**: Groups and projects are synonymous terms. Your group id is the same as your project id. For existing groups, your group/project id remains the same. The resource and corresponding endpoints use the term groups.",
				Required:            true,
			},
			"iam_role_id": schema.StringAttribute{
				Description:         "ID of the AWS IAM role that will be used to write to the S3 bucket.",
				MarkdownDescription: "ID of the AWS IAM role that will be used to write to the S3 bucket.",
				Optional:            true,
				Computed:            true,
			},
			"prefix_path": schema.StringAttribute{
				Description:         "S3 directory in which vector will write to in order to store the logs. An empty string denotes the root directory.",
				MarkdownDescription: "S3 directory in which vector will write to in order to store the logs. An empty string denotes the root directory.",
				Optional:            true,
				Computed:            true,
			},
			"state": schema.StringAttribute{
				Description:         "Describes whether or not the feature is enabled and what status it is in.",
				MarkdownDescription: "Describes whether or not the feature is enabled and what status it is in.",
				Computed:            true,
			},
		},
	}
}

type TFPushBasedLogExportRSModel struct {
	BucketName types.String `tfsdk:"bucket_name"`
	CreateDate types.String `tfsdk:"create_date"`
	GroupID    types.String `tfsdk:"group_id"`
	IamRoleID  types.String `tfsdk:"iam_role_id"`
	PrefixPath types.String `tfsdk:"prefix_path"`
	State      types.String `tfsdk:"state"`
}
