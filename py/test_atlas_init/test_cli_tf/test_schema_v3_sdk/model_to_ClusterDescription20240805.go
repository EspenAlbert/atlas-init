package advancedcluster

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/hashicorp/terraform-plugin-framework/types/basetypes"
	"github.com/mongodb/terraform-provider-mongodbatlas/internal/common/conversion"
	"go.mongodb.org/atlas-sdk/v20241023001/admin"
)

func NewAtlasReq(ctx context.Context, input *TFModel, diags *diag.Diagnostics) *admin.ClusterDescription20240805 {
	return &admin.ClusterDescription20240805{
		AcceptDataRisksAndForceReplicaSetReconfig: conversion.NilForUnknown(input.AcceptDataRisksAndForceReplicaSetReconfig, conversion.StringPtrToTimePtr(input.AcceptDataRisksAndForceReplicaSetReconfig.ValueStringPointer())),
		BackupEnabled:                    conversion.NilForUnknown(input.BackupEnabled, input.BackupEnabled.ValueBoolPointer()),
		BiConnector:                      newBiConnector(ctx, input.BiConnector, diags),
		ClusterType:                      input.ClusterType.ValueStringPointer(),
		ConfigServerManagementMode:       conversion.NilForUnknown(input.ConfigServerManagementMode, input.ConfigServerManagementMode.ValueStringPointer()),
		EncryptionAtRestProvider:         conversion.NilForUnknown(input.EncryptionAtRestProvider, input.EncryptionAtRestProvider.ValueStringPointer()),
		GlobalClusterSelfManagedSharding: conversion.NilForUnknown(input.GlobalClusterSelfManagedSharding, input.GlobalClusterSelfManagedSharding.ValueBoolPointer()),
		GroupId:                          input.ProjectId.ValueStringPointer(),
		Labels:                           newComponentLabel(ctx, input.Labels, diags),
		MongoDBMajorVersion:              conversion.NilForUnknown(input.MongoDbMajorVersion, input.MongoDbMajorVersion.ValueStringPointer()),
		Name:                             input.Name.ValueStringPointer(),
		Paused:                           conversion.NilForUnknown(input.Paused, input.Paused.ValueBoolPointer()),
		PitEnabled:                       conversion.NilForUnknown(input.PitEnabled, input.PitEnabled.ValueBoolPointer()),
		RedactClientLogData:              conversion.NilForUnknown(input.RedactClientLogData, input.RedactClientLogData.ValueBoolPointer()),
		ReplicaSetScalingStrategy:        conversion.NilForUnknown(input.ReplicaSetScalingStrategy, input.ReplicaSetScalingStrategy.ValueStringPointer()),
		ReplicationSpecs:                 newReplicationSpec20240805(ctx, input.ReplicationSpecs, diags),
		RootCertType:                     conversion.NilForUnknown(input.RootCertType, input.RootCertType.ValueStringPointer()),
		Tags:                             newResourceTag(ctx, input.Tags, diags),
		TerminationProtectionEnabled:     conversion.NilForUnknown(input.TerminationProtectionEnabled, input.TerminationProtectionEnabled.ValueBoolPointer()),
		VersionReleaseSystem:             conversion.NilForUnknown(input.VersionReleaseSystem, input.VersionReleaseSystem.ValueStringPointer()),
	}
}
func newBiConnector(ctx context.Context, input types.Object, diags *diag.Diagnostics) *admin.BiConnector {
	var resp *admin.BiConnector
	if input.IsUnknown() || input.IsNull() {
		return resp
	}
	item := &TFBiConnectorModel{}
	if localDiags := input.As(ctx, item, basetypes.ObjectAsOptions{}); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return resp
	}
	return &admin.BiConnector{
		Enabled:        conversion.NilForUnknown(item.Enabled, item.Enabled.ValueBoolPointer()),
		ReadPreference: conversion.NilForUnknown(item.ReadPreference, item.ReadPreference.ValueStringPointer()),
	}
}
func newComponentLabel(ctx context.Context, input types.List, diags *diag.Diagnostics) *[]admin.ComponentLabel {
	if input.IsUnknown() || input.IsNull() {
		return nil
	}
	elements := make([]TFLabelsModel, len(input.Elements()))
	if localDiags := input.ElementsAs(ctx, &elements, false); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return nil
	}
	resp := make([]admin.ComponentLabel, len(input.Elements()))
	for i := range elements {
		item := &elements[i]
		resp[i] = admin.ComponentLabel{
			Key:   item.Key.ValueStringPointer(),
			Value: item.Value.ValueStringPointer(),
		}
	}
	return &resp
}
func newReplicationSpec20240805(ctx context.Context, input types.List, diags *diag.Diagnostics) *[]admin.ReplicationSpec20240805 {
	if input.IsUnknown() || input.IsNull() {
		return nil
	}
	elements := make([]TFReplicationSpecsModel, len(input.Elements()))
	if localDiags := input.ElementsAs(ctx, &elements, false); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return nil
	}
	resp := make([]admin.ReplicationSpec20240805, len(input.Elements()))
	for i := range elements {
		item := &elements[i]
		resp[i] = admin.ReplicationSpec20240805{
			RegionConfigs: newCloudRegionConfig20240805(ctx, item.RegionConfigs, diags),
			ZoneName:      conversion.NilForUnknown(item.ZoneName, item.ZoneName.ValueStringPointer()),
		}
	}
	return &resp
}
func newResourceTag(ctx context.Context, input types.List, diags *diag.Diagnostics) *[]admin.ResourceTag {
	if input.IsUnknown() || input.IsNull() {
		return nil
	}
	elements := make([]TFTagsModel, len(input.Elements()))
	if localDiags := input.ElementsAs(ctx, &elements, false); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return nil
	}
	resp := make([]admin.ResourceTag, len(input.Elements()))
	for i := range elements {
		item := &elements[i]
		resp[i] = admin.ResourceTag{
			Key:   item.Key.ValueString(),
			Value: item.Value.ValueString(),
		}
	}
	return &resp
}
func newCloudRegionConfig20240805(ctx context.Context, input types.List, diags *diag.Diagnostics) *[]admin.CloudRegionConfig20240805 {
	if input.IsUnknown() || input.IsNull() {
		return nil
	}
	elements := make([]TFRegionConfigsModel, len(input.Elements()))
	if localDiags := input.ElementsAs(ctx, &elements, false); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return nil
	}
	resp := make([]admin.CloudRegionConfig20240805, len(input.Elements()))
	for i := range elements {
		item := &elements[i]
		resp[i] = admin.CloudRegionConfig20240805{
			AnalyticsAutoScaling: newAdvancedAutoScalingSettings(ctx, item.AnalyticsAutoScaling, diags),
			AnalyticsSpecs:       newDedicatedHardwareSpec20240805(ctx, item.AnalyticsSpecs, diags),
			AutoScaling:          newAdvancedAutoScalingSettings(ctx, item.AutoScaling, diags),
			BackingProviderName:  conversion.NilForUnknown(item.BackingProviderName, item.BackingProviderName.ValueStringPointer()),
			ElectableSpecs:       newHardwareSpec20240805(ctx, item.ElectableSpecs, diags),
			Priority:             conversion.Int64PtrToIntPtr(item.Priority.ValueInt64Pointer()),
			ProviderName:         item.ProviderName.ValueStringPointer(),
			ReadOnlySpecs:        newDedicatedHardwareSpec20240805(ctx, item.ReadOnlySpecs, diags),
			RegionName:           item.RegionName.ValueStringPointer(),
		}
	}
	return &resp
}
func newAdvancedAutoScalingSettings(ctx context.Context, input types.Object, diags *diag.Diagnostics) *admin.AdvancedAutoScalingSettings {
	var resp *admin.AdvancedAutoScalingSettings
	if input.IsUnknown() || input.IsNull() {
		return resp
	}
	item := &TFAnalyticsAutoScalingModel{}
	if localDiags := input.As(ctx, item, basetypes.ObjectAsOptions{}); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return resp
	}
	return &admin.AdvancedAutoScalingSettings{
		Compute: newAdvancedComputeAutoScaling(ctx, item.Compute, diags),
		DiskGB:  newDiskGBAutoScaling(ctx, item.DiskGb, diags),
	}
}
func newDedicatedHardwareSpec20240805(ctx context.Context, input types.Object, diags *diag.Diagnostics) *admin.DedicatedHardwareSpec20240805 {
	var resp *admin.DedicatedHardwareSpec20240805
	if input.IsUnknown() || input.IsNull() {
		return resp
	}
	item := &TFAnalyticsSpecsModel{}
	if localDiags := input.As(ctx, item, basetypes.ObjectAsOptions{}); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return resp
	}
	return &admin.DedicatedHardwareSpec20240805{
		DiskIOPS:      conversion.NilForUnknown(item.DiskIops, conversion.Int64PtrToIntPtr(item.DiskIops.ValueInt64Pointer())),
		DiskSizeGB:    conversion.NilForUnknown(item.DiskSizeGb, item.DiskSizeGb.ValueFloat64Pointer()),
		EbsVolumeType: conversion.NilForUnknown(item.EbsVolumeType, item.EbsVolumeType.ValueStringPointer()),
		InstanceSize:  conversion.NilForUnknown(item.InstanceSize, item.InstanceSize.ValueStringPointer()),
		NodeCount:     conversion.NilForUnknown(item.NodeCount, conversion.Int64PtrToIntPtr(item.NodeCount.ValueInt64Pointer())),
	}
}
func newAdvancedAutoScalingSettings(ctx context.Context, input types.Object, diags *diag.Diagnostics) *admin.AdvancedAutoScalingSettings {
	var resp *admin.AdvancedAutoScalingSettings
	if input.IsUnknown() || input.IsNull() {
		return resp
	}
	item := &TFAutoScalingModel{}
	if localDiags := input.As(ctx, item, basetypes.ObjectAsOptions{}); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return resp
	}
	return &admin.AdvancedAutoScalingSettings{
		Compute: newAdvancedComputeAutoScaling(ctx, item.Compute, diags),
		DiskGB:  newDiskGBAutoScaling(ctx, item.DiskGb, diags),
	}
}
func newHardwareSpec20240805(ctx context.Context, input types.Object, diags *diag.Diagnostics) *admin.HardwareSpec20240805 {
	var resp *admin.HardwareSpec20240805
	if input.IsUnknown() || input.IsNull() {
		return resp
	}
	item := &TFElectableSpecsModel{}
	if localDiags := input.As(ctx, item, basetypes.ObjectAsOptions{}); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return resp
	}
	return &admin.HardwareSpec20240805{
		DiskIOPS:      conversion.NilForUnknown(item.DiskIops, conversion.Int64PtrToIntPtr(item.DiskIops.ValueInt64Pointer())),
		DiskSizeGB:    conversion.NilForUnknown(item.DiskSizeGb, item.DiskSizeGb.ValueFloat64Pointer()),
		EbsVolumeType: conversion.NilForUnknown(item.EbsVolumeType, item.EbsVolumeType.ValueStringPointer()),
		InstanceSize:  conversion.NilForUnknown(item.InstanceSize, item.InstanceSize.ValueStringPointer()),
		NodeCount:     conversion.NilForUnknown(item.NodeCount, conversion.Int64PtrToIntPtr(item.NodeCount.ValueInt64Pointer())),
	}
}
func newDedicatedHardwareSpec20240805(ctx context.Context, input types.Object, diags *diag.Diagnostics) *admin.DedicatedHardwareSpec20240805 {
	var resp *admin.DedicatedHardwareSpec20240805
	if input.IsUnknown() || input.IsNull() {
		return resp
	}
	item := &TFReadOnlySpecsModel{}
	if localDiags := input.As(ctx, item, basetypes.ObjectAsOptions{}); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return resp
	}
	return &admin.DedicatedHardwareSpec20240805{
		DiskIOPS:      conversion.NilForUnknown(item.DiskIops, conversion.Int64PtrToIntPtr(item.DiskIops.ValueInt64Pointer())),
		DiskSizeGB:    conversion.NilForUnknown(item.DiskSizeGb, item.DiskSizeGb.ValueFloat64Pointer()),
		EbsVolumeType: conversion.NilForUnknown(item.EbsVolumeType, item.EbsVolumeType.ValueStringPointer()),
		InstanceSize:  conversion.NilForUnknown(item.InstanceSize, item.InstanceSize.ValueStringPointer()),
		NodeCount:     conversion.NilForUnknown(item.NodeCount, conversion.Int64PtrToIntPtr(item.NodeCount.ValueInt64Pointer())),
	}
}
func newAdvancedComputeAutoScaling(ctx context.Context, input types.Object, diags *diag.Diagnostics) *admin.AdvancedComputeAutoScaling {
	var resp *admin.AdvancedComputeAutoScaling
	if input.IsUnknown() || input.IsNull() {
		return resp
	}
	item := &TFComputeModel{}
	if localDiags := input.As(ctx, item, basetypes.ObjectAsOptions{}); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return resp
	}
	return &admin.AdvancedComputeAutoScaling{
		Enabled:          conversion.NilForUnknown(item.Enabled, item.Enabled.ValueBoolPointer()),
		MaxInstanceSize:  conversion.NilForUnknown(item.MaxInstanceSize, item.MaxInstanceSize.ValueStringPointer()),
		MinInstanceSize:  conversion.NilForUnknown(item.MinInstanceSize, item.MinInstanceSize.ValueStringPointer()),
		ScaleDownEnabled: conversion.NilForUnknown(item.ScaleDownEnabled, item.ScaleDownEnabled.ValueBoolPointer()),
	}
}
func newDiskGBAutoScaling(ctx context.Context, input types.Object, diags *diag.Diagnostics) *admin.DiskGBAutoScaling {
	var resp *admin.DiskGBAutoScaling
	if input.IsUnknown() || input.IsNull() {
		return resp
	}
	item := &TFDiskGbModel{}
	if localDiags := input.As(ctx, item, basetypes.ObjectAsOptions{}); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return resp
	}
	return &admin.DiskGBAutoScaling{
		Enabled: conversion.NilForUnknown(item.Enabled, item.Enabled.ValueBoolPointer()),
	}
}
func newAdvancedComputeAutoScaling(ctx context.Context, input types.Object, diags *diag.Diagnostics) *admin.AdvancedComputeAutoScaling {
	var resp *admin.AdvancedComputeAutoScaling
	if input.IsUnknown() || input.IsNull() {
		return resp
	}
	item := &TFComputeModel{}
	if localDiags := input.As(ctx, item, basetypes.ObjectAsOptions{}); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return resp
	}
	return &admin.AdvancedComputeAutoScaling{
		Enabled:          conversion.NilForUnknown(item.Enabled, item.Enabled.ValueBoolPointer()),
		MaxInstanceSize:  conversion.NilForUnknown(item.MaxInstanceSize, item.MaxInstanceSize.ValueStringPointer()),
		MinInstanceSize:  conversion.NilForUnknown(item.MinInstanceSize, item.MinInstanceSize.ValueStringPointer()),
		ScaleDownEnabled: conversion.NilForUnknown(item.ScaleDownEnabled, item.ScaleDownEnabled.ValueBoolPointer()),
	}
}
func newDiskGBAutoScaling(ctx context.Context, input types.Object, diags *diag.Diagnostics) *admin.DiskGBAutoScaling {
	var resp *admin.DiskGBAutoScaling
	if input.IsUnknown() || input.IsNull() {
		return resp
	}
	item := &TFDiskGbModel{}
	if localDiags := input.As(ctx, item, basetypes.ObjectAsOptions{}); len(localDiags) > 0 {
		diags.Append(localDiags...)
		return resp
	}
	return &admin.DiskGBAutoScaling{
		Enabled: conversion.NilForUnknown(item.Enabled, item.Enabled.ValueBoolPointer()),
	}
}
