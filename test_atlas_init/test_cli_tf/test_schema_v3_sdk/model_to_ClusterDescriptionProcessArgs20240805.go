package advancedclusterprocessargs

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/mongodb/terraform-provider-mongodbatlas/internal/common/conversion"
	"go.mongodb.org/atlas-sdk/v20241023001/admin"
)

func NewAtlasReq(ctx context.Context, input *TFModel, diags *diag.Diagnostics) *admin.ClusterDescriptionProcessArgs20240805 {
	return &admin.ClusterDescriptionProcessArgs20240805{
		ChangeStreamOptionsPreAndPostImagesExpireAfterSeconds: conversion.NilForUnknown(input.ChangeStreamOptionsPreAndPostImagesExpireAfterSeconds, conversion.Int64PtrToIntPtr(input.ChangeStreamOptionsPreAndPostImagesExpireAfterSeconds.ValueInt64Pointer())),
		ChunkMigrationConcurrency:                             conversion.NilForUnknown(input.ChunkMigrationConcurrency, conversion.Int64PtrToIntPtr(input.ChunkMigrationConcurrency.ValueInt64Pointer())),
		DefaultMaxTimeMS:                                      conversion.NilForUnknown(input.DefaultMaxTimeMs, conversion.Int64PtrToIntPtr(input.DefaultMaxTimeMs.ValueInt64Pointer())),
		DefaultWriteConcern:                                   conversion.NilForUnknown(input.DefaultWriteConcern, input.DefaultWriteConcern.ValueStringPointer()),
		JavascriptEnabled:                                     conversion.NilForUnknown(input.JavascriptEnabled, input.JavascriptEnabled.ValueBoolPointer()),
		MinimumEnabledTlsProtocol:                             conversion.NilForUnknown(input.MinimumEnabledTlsProtocol, input.MinimumEnabledTlsProtocol.ValueStringPointer()),
		NoTableScan:                                           conversion.NilForUnknown(input.NoTableScan, input.NoTableScan.ValueBoolPointer()),
		OplogMinRetentionHours:                                conversion.NilForUnknown(input.OplogMinRetentionHours, input.OplogMinRetentionHours.ValueFloat64Pointer()),
		OplogSizeMB:                                           conversion.NilForUnknown(input.OplogSizeMb, conversion.Int64PtrToIntPtr(input.OplogSizeMb.ValueInt64Pointer())),
		QueryStatsLogVerbosity:                                conversion.NilForUnknown(input.QueryStatsLogVerbosity, conversion.Int64PtrToIntPtr(input.QueryStatsLogVerbosity.ValueInt64Pointer())),
		TransactionLifetimeLimitSeconds:                       conversion.NilForUnknown(input.TransactionLifetimeLimitSeconds, input.TransactionLifetimeLimitSeconds.ValueInt64Pointer()),
	}
}
