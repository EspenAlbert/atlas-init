// Code generated by terraform-plugin-framework-generator DO NOT EDIT.

package resourcepolicy

import (
	"context"
	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"regexp"

	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
)

func DataSourceSchemaPlural(ctx context.Context) schema.Schema {
	dsAttributes := dataSourceSchema(true)
	return schema.Schema{
		Attributes: map[string]schema.Attribute{
			"org_id": schema.StringAttribute{
				Required:            true,
				Description:         "Unique 24-hexadecimal digit string that identifies the organization that contains your projects. Use the [/orgs](#tag/Organizations/operation/listOrganizations) endpoint to retrieve all organizations to which the authenticated user has access.",
				MarkdownDescription: "Unique 24-hexadecimal digit string that identifies the organization that contains your projects. Use the [/orgs](#tag/Organizations/operation/listOrganizations) endpoint to retrieve all organizations to which the authenticated user has access.",
				Validators: []validator.String{
					stringvalidator.LengthBetween(24, 24),
					stringvalidator.RegexMatches(regexp.MustCompile("^([a-f0-9]{24})$"), ""),
				},
			},
			"resource_policies": schema.ListNestedAttribute{
				NestedObject: schema.NestedAttributeObject{
					Attributes: dsAttributes,
				},
				Computed: true,
			},
		},
	}
}

type ResourcePoliciesModel struct {
	OrgId            types.String `tfsdk:"org_id"`
	ResourcePolicies types.List    `tfsdk:"resource_policies"`
}
