package resourcepolicy

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"go.mongodb.org/atlas-sdk/v20240805004/admin"
)

func NewTFModel(ctx context.Context, input *admin.ApiAtlasResourcePolicy) (*TFModel, diag.Diagnostics) {
	diags := &diag.Diagnostics{}
	createdByUser := NewCreatedByUser(ctx, input.CreatedByUser, diags)
	lastUpdatedByUser := NewLastUpdatedByUser(ctx, input.LastUpdatedByUser, diags)
	policies := NewPolicies(ctx, input.Policies, diags)
	if diags.HasError() {
		return nil, *diags
	}
	return &TFModel{
		createdByUser:     createdByUser,
		createdDate:       input.CreatedDate,
		id:                input.Id,
		lastUpdatedByUser: lastUpdatedByUser,
		lastUpdatedDate:   input.LastUpdatedDate,
		name:              input.Name,
		orgId:             input.OrgId,
		policies:          policies,
		version:           input.Version,
	}, nil
}

func NewCreatedByUserObjectType(ctx context.Context, input *admin.ApiAtlasUserMetadata, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(CreatedByUserObjectType.AttrTypes)
	}
	tfModel := TFCreatedByUser{
		id:   input.Id,
		name: input.Name,
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, CreatedByUserObjectType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewLastUpdatedByUserObjectType(ctx context.Context, input *admin.ApiAtlasUserMetadata, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(LastUpdatedByUserObjectType.AttrTypes)
	}
	tfModel := TFLastUpdatedByUser{
		id:   input.Id,
		name: input.Name,
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, LastUpdatedByUserObjectType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewPoliciesObjectType(ctx context.Context, input *admin.ApiAtlasPolicy, diags *diag.Diagnostics) types.List {
	if input == nil {
		return types.ObjectNull(PoliciesObjectType.AttrTypes)
	}
	tfModels := make([]TFPolicies, len(*input))
	for i, item := range *input {
		tfModels[i] = TFPolicies{
			body: item.Body,
			id:   item.Id,
		}
	}
	listType, diagsLocal := types.ListValueFrom(ctx, PoliciesObjectType, tfModels)
	diags.Append(diagsLocal...)
	return listType
}
