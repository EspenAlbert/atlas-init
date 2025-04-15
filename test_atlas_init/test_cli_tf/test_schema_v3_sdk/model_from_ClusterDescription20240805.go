package advancedcluster

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework-timeouts/resource/timeouts"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/mongodb/terraform-provider-mongodbatlas/internal/common/conversion"
	"go.mongodb.org/atlas-sdk/v20241023001/admin"
)

func NewTFModel(ctx context.Context, input *admin.ClusterDescription20240805, timeout timeouts.Value) (*TFModel, diag.Diagnostics) {
	diags := &diag.Diagnostics{}
	biConnector := NewBiConnectorObjType(ctx, input.BiConnector, diags)
	connectionStrings := NewConnectionStringsObjType(ctx, input.ConnectionStrings, diags)
	labels := NewLabelsObjType(ctx, input.Labels, diags)
	replicationSpecs := NewReplicationSpecsObjType(ctx, input.ReplicationSpecs, diags)
	tags := NewTagsObjType(ctx, input.Tags, diags)
	if diags.HasError() {
		return nil, *diags
	}
	return &TFModel{
		AcceptDataRisksAndForceReplicaSetReconfig: types.StringPointerValue(conversion.TimePtrToStringPtr(input.AcceptDataRisksAndForceReplicaSetReconfig)),
		BackupEnabled:                    types.BoolPointerValue(input.BackupEnabled),
		BiConnector:                      biConnector,
		ClusterType:                      types.StringPointerValue(input.ClusterType),
		ConfigServerManagementMode:       types.StringPointerValue(input.ConfigServerManagementMode),
		ConfigServerType:                 types.StringPointerValue(input.ConfigServerType),
		ConnectionStrings:                connectionStrings,
		CreateDate:                       types.StringPointerValue(conversion.TimePtrToStringPtr(input.CreateDate)),
		EncryptionAtRestProvider:         types.StringPointerValue(input.EncryptionAtRestProvider),
		GlobalClusterSelfManagedSharding: types.BoolPointerValue(input.GlobalClusterSelfManagedSharding),
		ProjectID:                        types.StringPointerValue(input.GroupId),
		ClusterID:                        types.StringPointerValue(input.Id),
		Labels:                           labels,
		MongoDBMajorVersion:              types.StringPointerValue(input.MongoDBMajorVersion),
		MongoDBVersion:                   types.StringPointerValue(input.MongoDBVersion),
		Name:                             types.StringPointerValue(input.Name),
		Paused:                           types.BoolPointerValue(input.Paused),
		PitEnabled:                       types.BoolPointerValue(input.PitEnabled),
		RedactClientLogData:              types.BoolPointerValue(input.RedactClientLogData),
		ReplicaSetScalingStrategy:        types.StringPointerValue(input.ReplicaSetScalingStrategy),
		ReplicationSpecs:                 replicationSpecs,
		RootCertType:                     types.StringPointerValue(input.RootCertType),
		StateName:                        types.StringPointerValue(input.StateName),
		Tags:                             tags,
		TerminationProtectionEnabled:     types.BoolPointerValue(input.TerminationProtectionEnabled),
		VersionReleaseSystem:             types.StringPointerValue(input.VersionReleaseSystem),
		Timeouts:                         timeout,
	}, nil
}

func NewBiConnectorObjType(ctx context.Context, input *admin.BiConnector, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(BiConnectorObjType.AttrTypes)
	}
	tfModel := TFBiConnectorModel{
		Enabled:        types.BoolPointerValue(input.Enabled),
		ReadPreference: types.StringPointerValue(input.ReadPreference),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, BiConnectorObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewConnectionStringsObjType(ctx context.Context, input *admin.ClusterConnectionStrings, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(ConnectionStringsObjType.AttrTypes)
	}
	privateEndpoint := NewPrivateEndpointObjType(ctx, input.PrivateEndpoint, diags)
	tfModel := TFConnectionStringsModel{
		Private:         types.StringPointerValue(input.Private),
		PrivateEndpoint: privateEndpoint,
		PrivateSrv:      types.StringPointerValue(input.PrivateSrv),
		Standard:        types.StringPointerValue(input.Standard),
		StandardSrv:     types.StringPointerValue(input.StandardSrv),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, ConnectionStringsObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewLabelsObjType(ctx context.Context, input *[]admin.ComponentLabel, diags *diag.Diagnostics) types.List {
	if input == nil {
		return types.ListNull(LabelsObjType)
	}
	tfModels := make([]TFLabelsModel, len(*input))
	for i, item := range *input {
		tfModels[i] = TFLabelsModel{
			Key:   types.StringPointerValue(item.Key),
			Value: types.StringPointerValue(item.Value),
		}
	}
	listType, diagsLocal := types.ListValueFrom(ctx, LabelsObjType, tfModels)
	diags.Append(diagsLocal...)
	return listType
}

func NewReplicationSpecsObjType(ctx context.Context, input *[]admin.ReplicationSpec20240805, diags *diag.Diagnostics) types.List {
	if input == nil {
		return types.ListNull(ReplicationSpecsObjType)
	}
	tfModels := make([]TFReplicationSpecsModel, len(*input))
	for i, item := range *input {
		regionConfigs := NewRegionConfigsObjType(ctx, item.RegionConfigs, diags)
		tfModels[i] = TFReplicationSpecsModel{
			ClusterID:     types.StringPointerValue(item.Id),
			RegionConfigs: regionConfigs,
			ZoneId:        types.StringPointerValue(item.ZoneId),
			ZoneName:      types.StringPointerValue(item.ZoneName),
		}
	}
	listType, diagsLocal := types.ListValueFrom(ctx, ReplicationSpecsObjType, tfModels)
	diags.Append(diagsLocal...)
	return listType
}

func NewTagsObjType(ctx context.Context, input *[]admin.ResourceTag, diags *diag.Diagnostics) types.List {
	if input == nil {
		return types.ListNull(TagsObjType)
	}
	tfModels := make([]TFTagsModel, len(*input))
	for i, item := range *input {
		tfModels[i] = TFTagsModel{
			Key:   types.StringValue(item.Key),
			Value: types.StringValue(item.Value),
		}
	}
	listType, diagsLocal := types.ListValueFrom(ctx, TagsObjType, tfModels)
	diags.Append(diagsLocal...)
	return listType
}

func NewPrivateEndpointObjType(ctx context.Context, input *[]admin.ClusterDescriptionConnectionStringsPrivateEndpoint, diags *diag.Diagnostics) types.List {
	if input == nil {
		return types.ListNull(PrivateEndpointObjType)
	}
	tfModels := make([]TFPrivateEndpointModel, len(*input))
	for i, item := range *input {
		endpoints := NewEndpointsObjType(ctx, item.Endpoints, diags)
		tfModels[i] = TFPrivateEndpointModel{
			ConnectionString:                  types.StringPointerValue(item.ConnectionString),
			Endpoints:                         endpoints,
			SrvConnectionString:               types.StringPointerValue(item.SrvConnectionString),
			SrvShardOptimizedConnectionString: types.StringPointerValue(item.SrvShardOptimizedConnectionString),
			Type:                              types.StringPointerValue(item.Type),
		}
	}
	listType, diagsLocal := types.ListValueFrom(ctx, PrivateEndpointObjType, tfModels)
	diags.Append(diagsLocal...)
	return listType
}

func NewRegionConfigsObjType(ctx context.Context, input *[]admin.CloudRegionConfig20240805, diags *diag.Diagnostics) types.List {
	if input == nil {
		return types.ListNull(RegionConfigsObjType)
	}
	tfModels := make([]TFRegionConfigsModel, len(*input))
	for i, item := range *input {
		analyticsAutoScaling := NewAnalyticsAutoScalingObjType(ctx, item.AnalyticsAutoScaling, diags)
		analyticsSpecs := NewAnalyticsSpecsObjType(ctx, item.AnalyticsSpecs, diags)
		autoScaling := NewAutoScalingObjType(ctx, item.AutoScaling, diags)
		electableSpecs := NewElectableSpecsObjType(ctx, item.ElectableSpecs, diags)
		readOnlySpecs := NewReadOnlySpecsObjType(ctx, item.ReadOnlySpecs, diags)
		tfModels[i] = TFRegionConfigsModel{
			AnalyticsAutoScaling: analyticsAutoScaling,
			AnalyticsSpecs:       analyticsSpecs,
			AutoScaling:          autoScaling,
			BackingProviderName:  types.StringPointerValue(item.BackingProviderName),
			ElectableSpecs:       electableSpecs,
			Priority:             types.Int64PointerValue(conversion.IntPtrToInt64Ptr(item.Priority)),
			ProviderName:         types.StringPointerValue(item.ProviderName),
			ReadOnlySpecs:        readOnlySpecs,
			RegionName:           types.StringPointerValue(item.RegionName),
		}
	}
	listType, diagsLocal := types.ListValueFrom(ctx, RegionConfigsObjType, tfModels)
	diags.Append(diagsLocal...)
	return listType
}

func NewEndpointsObjType(ctx context.Context, input *[]admin.ClusterDescriptionConnectionStringsPrivateEndpointEndpoint, diags *diag.Diagnostics) types.List {
	if input == nil {
		return types.ListNull(EndpointsObjType)
	}
	tfModels := make([]TFEndpointsModel, len(*input))
	for i, item := range *input {
		tfModels[i] = TFEndpointsModel{
			EndpointId:   types.StringPointerValue(item.EndpointId),
			ProviderName: types.StringPointerValue(item.ProviderName),
			Region:       types.StringPointerValue(item.Region),
		}
	}
	listType, diagsLocal := types.ListValueFrom(ctx, EndpointsObjType, tfModels)
	diags.Append(diagsLocal...)
	return listType
}

func NewAnalyticsAutoScalingObjType(ctx context.Context, input *admin.AdvancedAutoScalingSettings, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(AnalyticsAutoScalingObjType.AttrTypes)
	}
	compute := NewComputeObjType(ctx, input.Compute, diags)
	diskGB := NewDiskGbObjType(ctx, input.DiskGB, diags)
	tfModel := TFAnalyticsAutoScalingModel{
		Compute: compute,
		DiskGb:  diskGB,
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, AnalyticsAutoScalingObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewAnalyticsSpecsObjType(ctx context.Context, input *admin.DedicatedHardwareSpec20240805, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(AnalyticsSpecsObjType.AttrTypes)
	}
	tfModel := TFAnalyticsSpecsModel{
		DiskIops:      types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.DiskIOPS)),
		DiskSizeGb:    types.Float64PointerValue(input.DiskSizeGB),
		EbsVolumeType: types.StringPointerValue(input.EbsVolumeType),
		InstanceSize:  types.StringPointerValue(input.InstanceSize),
		NodeCount:     types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.NodeCount)),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, AnalyticsSpecsObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewAutoScalingObjType(ctx context.Context, input *admin.AdvancedAutoScalingSettings, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(AutoScalingObjType.AttrTypes)
	}
	compute := NewComputeObjType(ctx, input.Compute, diags)
	diskGB := NewDiskGbObjType(ctx, input.DiskGB, diags)
	tfModel := TFAutoScalingModel{
		Compute: compute,
		DiskGb:  diskGB,
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, AutoScalingObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewElectableSpecsObjType(ctx context.Context, input *admin.HardwareSpec20240805, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(ElectableSpecsObjType.AttrTypes)
	}
	tfModel := TFElectableSpecsModel{
		DiskIops:      types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.DiskIOPS)),
		DiskSizeGb:    types.Float64PointerValue(input.DiskSizeGB),
		EbsVolumeType: types.StringPointerValue(input.EbsVolumeType),
		InstanceSize:  types.StringPointerValue(input.InstanceSize),
		NodeCount:     types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.NodeCount)),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, ElectableSpecsObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewReadOnlySpecsObjType(ctx context.Context, input *admin.DedicatedHardwareSpec20240805, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(ReadOnlySpecsObjType.AttrTypes)
	}
	tfModel := TFReadOnlySpecsModel{
		DiskIops:      types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.DiskIOPS)),
		DiskSizeGb:    types.Float64PointerValue(input.DiskSizeGB),
		EbsVolumeType: types.StringPointerValue(input.EbsVolumeType),
		InstanceSize:  types.StringPointerValue(input.InstanceSize),
		NodeCount:     types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.NodeCount)),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, ReadOnlySpecsObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewComputeObjType(ctx context.Context, input *admin.AdvancedComputeAutoScaling, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(ComputeObjType.AttrTypes)
	}
	tfModel := TFComputeModel{
		Enabled:          types.BoolPointerValue(input.Enabled),
		MaxInstanceSize:  types.StringPointerValue(input.MaxInstanceSize),
		MinInstanceSize:  types.StringPointerValue(input.MinInstanceSize),
		ScaleDownEnabled: types.BoolPointerValue(input.ScaleDownEnabled),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, ComputeObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewDiskGbObjType(ctx context.Context, input *admin.DiskGBAutoScaling, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(DiskGbObjType.AttrTypes)
	}
	tfModel := TFDiskGbModel{
		Enabled: types.BoolPointerValue(input.Enabled),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, DiskGbObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewComputeObjType(ctx context.Context, input *admin.AdvancedComputeAutoScaling, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(ComputeObjType.AttrTypes)
	}
	tfModel := TFComputeModel{
		Enabled:          types.BoolPointerValue(input.Enabled),
		MaxInstanceSize:  types.StringPointerValue(input.MaxInstanceSize),
		MinInstanceSize:  types.StringPointerValue(input.MinInstanceSize),
		ScaleDownEnabled: types.BoolPointerValue(input.ScaleDownEnabled),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, ComputeObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}

func NewDiskGbObjType(ctx context.Context, input *admin.DiskGBAutoScaling, diags *diag.Diagnostics) types.Object {
	if input == nil {
		return types.ObjectNull(DiskGbObjType.AttrTypes)
	}
	tfModel := TFDiskGbModel{
		Enabled: types.BoolPointerValue(input.Enabled),
	}
	objType, diagsLocal := types.ObjectValueFrom(ctx, DiskGbObjType.AttrTypes, tfModel)
	diags.Append(diagsLocal...)
	return objType
}
