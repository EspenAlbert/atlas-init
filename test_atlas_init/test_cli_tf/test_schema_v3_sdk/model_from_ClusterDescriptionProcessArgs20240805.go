package advancedclusterprocessargs

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/mongodb/terraform-provider-mongodbatlas/internal/common/conversion"
	"go.mongodb.org/atlas-sdk/v20241023001/admin"
)

func NewTFModel(ctx context.Context, input *admin.ClusterDescriptionProcessArgs20240805) (*TFModel, diag.Diagnostics) {
	return &TFModel{
		ChangeStreamOptionsPreAndPostImagesExpireAfterSeconds: types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.ChangeStreamOptionsPreAndPostImagesExpireAfterSeconds)),
		ChunkMigrationConcurrency:                             types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.ChunkMigrationConcurrency)),
		DefaultMaxTimeMs:                                      types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.DefaultMaxTimeMS)),
		DefaultWriteConcern:                                   types.StringPointerValue(input.DefaultWriteConcern),
		JavascriptEnabled:                                     types.BoolPointerValue(input.JavascriptEnabled),
		MinimumEnabledTlsProtocol:                             types.StringPointerValue(input.MinimumEnabledTlsProtocol),
		NoTableScan:                                           types.BoolPointerValue(input.NoTableScan),
		OplogMinRetentionHours:                                types.Float64PointerValue(input.OplogMinRetentionHours),
		OplogSizeMb:                                           types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.OplogSizeMB)),
		QueryStatsLogVerbosity:                                types.Int64PointerValue(conversion.IntPtrToInt64Ptr(input.QueryStatsLogVerbosity)),
		TransactionLifetimeLimitSeconds:                       types.Int64PointerValue(input.TransactionLifetimeLimitSeconds),
	}, nil
}
