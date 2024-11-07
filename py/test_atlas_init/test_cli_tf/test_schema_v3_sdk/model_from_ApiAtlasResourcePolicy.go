package resourcepolicy

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/mongodb/terraform-provider-mongodbatlas/internal/common/conversion"
	"go.mongodb.org/atlas-sdk/v20241023001/admin"
)

func NewTFModel(ctx context.Context, input *admin.ApiAtlasResourcePolicy) (*TFModel, diag.Diagnostics) {
	diags := &diag.Diagnostics{}
	createdByUser := NewCreatedByUserObjType(ctx, input.CreatedByUser, diags)
	lastUpdatedByUser := NewLastUpdatedByUserObjType(ctx, input.LastUpdatedByUser, diags)
	policies := NewPoliciesObjType(ctx, input.Policies, diags)
	if diags.HasError() {
		return nil, *diags
	}
	return &TFModel{
		CreatedByUser:     createdByUser,
		CreatedDate:       types.StringPointerValue(conversion.TimePtrToStringPtr(input.CreatedDate)),
		Id:                types.StringPointerValue(input.Id),
		LastUpdatedByUser: lastUpdatedByUser,
		LastUpdatedDate:   types.StringPointerValue(conversion.TimePtrToStringPtr(input.LastUpdatedDate)),
		Name:              types.StringPointerValue(input.Name),
		OrgId:             types.StringPointerValue(input.OrgId),
		Policies:          policies,
		Version:           types.StringPointerValue(input.Version),
	}, nil
}

func NewCreatedByUserObjType(ctx context.Context, input *admin.ApiAtlasUserMetadata, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(CreatedByUserObjType.AttrTypes)
	}
	tfModel := TFCreatedByUserModel{
		Id:   types.StringPointerValue(input.Id),
		Name: types.StringPointerValue(input.Name),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, CreatedByUserObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewLastUpdatedByUserObjType(ctx context.Context, input *admin.ApiAtlasUserMetadata, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(LastUpdatedByUserObjType.AttrTypes)
	}
	tfModel := TFLastUpdatedByUserModel{
		Id:   types.StringPointerValue(input.Id),
		Name: types.StringPointerValue(input.Name),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, LastUpdatedByUserObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewPoliciesObjType(ctx context.Context, input *[]admin.ApiAtlasPolicy, diags *diag.Diagnostics) types.List {
	if input == nil {
		return types.ListNull(PoliciesObjType)
	}
	tfModels := make([]TFPoliciesModel, len(*input))
	for i, item := range *input {
		tfModels[i] = TFPoliciesModel{
			Body: types.StringPointerValue(item.Body),
			Id:   types.StringPointerValue(item.Id),
		}
	}
	listType, diagsLocal := types.ListValueFrom(ctx, PoliciesObjType, tfModels)
	diags.Append(diagsLocal...)
	return listType
}
