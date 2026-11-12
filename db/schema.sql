-- ClickHouse schema for the Living Liquidz target app.
-- Exported from the reference database; run once against the target database (e.g. clickhouse-client --multiquery < db/schema.sql).
-- Target tables use ReplacingMergeTree(version): saving a row inserts a new version; FINAL returns the latest one.
-- Rows are never deleted by the app: is_active = 0 retires them.

CREATE TABLE IF NOT EXISTS branch_wise_monthly_target
(
    `month` Date,
    `branch_name` String,
    `series_group` String,
    `target_value1` Decimal(10, 2),
    `incentive_value1` Decimal(10, 2),
    `target_value2` Decimal(10, 2),
    `incentive_value2` Decimal(10, 2),
    `target_value3` Decimal(10, 2),
    `incentive_value3` Decimal(10, 2),
    `target_value4` Decimal(10, 2),
    `incentive_value4` Decimal(10, 2),
    `target_value5` Decimal(10, 2),
    `incentive_value5` Decimal(10, 2),
    `version` UInt32 DEFAULT toUnixTimestamp(now()),
    `updated_at` DateTime DEFAULT now(),
    `is_active` UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (month, branch_name, series_group)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS brand_wise_monthly_target
(
    `month` Date,
    `branch_name` String,
    `series_group` String,
    `item_code` String,
    `item_name` String,
    `pack_name` String,
    `target_qty1` Decimal(10, 2),
    `incentive_value1` Decimal(10, 2),
    `target_qty2` Decimal(10, 2),
    `incentive_value2` Decimal(10, 2),
    `target_qty3` Decimal(10, 2),
    `incentive_value3` Decimal(10, 2),
    `target_qty4` Decimal(10, 2),
    `incentive_value4` Decimal(10, 2),
    `target_qty5` Decimal(10, 2),
    `incentive_value5` Decimal(10, 2),
    `version` UInt32 DEFAULT toUnixTimestamp(now()),
    `updated_at` DateTime DEFAULT now(),
    `is_active` UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (month, branch_name, series_group, item_code, item_name)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS date_branch_wise_target
(
    `date` Date,
    `branch_name` String,
    `series_group` String,
    `target_value1` Decimal(10, 2),
    `incentive_value1` Decimal(10, 2),
    `target_value2` Decimal(10, 2),
    `incentive_value2` Decimal(10, 2),
    `target_value3` Decimal(10, 2),
    `incentive_value3` Decimal(10, 2),
    `target_value4` Decimal(10, 2),
    `incentive_value4` Decimal(10, 2),
    `target_value5` Decimal(10, 2),
    `incentive_value5` Decimal(10, 2),
    `version` UInt32 DEFAULT toUnixTimestamp(now()),
    `updated_at` DateTime DEFAULT now(),
    `is_active` UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (date, branch_name, series_group)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS target_system_audit_logs
(
    `log_id` UUID DEFAULT generateUUIDv4(),
    `timestamp` DateTime DEFAULT now(),
    `session_id` String,
    `user_email` String,
    `action_type` String,
    `target_table` String,
    `record_count` Int32,
    `before_state` String,
    `after_state` String,
    `device_info` String,
    `ip_address` String,
    `error_message` String,
    `metadata` String
)
ENGINE = MergeTree
ORDER BY (timestamp, action_type)
SETTINGS index_granularity = 8192;
