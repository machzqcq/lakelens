"""Inline schema metadata for the system.compute.* node-pool tables.

Used by `routers/chat.py` to add `node_timeline`, `warehouse_events`,
`node_types`, `instance_events`, and `instance_pools` to the LLM context
so the Chatbot can answer cluster-utilization, warehouse-lifecycle, and
instance-pool capacity questions.

Same pattern as `chat_audit_schema.py` / `chat_lineage_schema.py`.

Authoritative Databricks references:
  - https://docs.databricks.com/aws/en/admin/system-tables/compute
"""
from __future__ import annotations


NODE_POOL_TABLES_METADATA = [
    {
        "name": "node_timeline",
        "description": (
            "Per-minute instance utilization snapshot (system.compute.node_timeline). "
            "One row per (instance_id, start_time). High-cardinality table — by far the "
            "biggest in the compute schema. Use `cluster_id` to join back to "
            "clusters / billing_usage; `driver` is true for the driver node. "
            "CPU and memory percentages are 0–100. `disk_free_bytes_per_mount_point` "
            "is a JSON map (key=mount path, value=bytes free). Always add a "
            "`start_time` time-window predicate — unbounded scans will exhaust "
            "memory on real accounts."
        ),
        "columns": [
            {"name": "account_id", "type": "string"},
            {"name": "workspace_id", "type": "string"},
            {"name": "cluster_id", "type": "string", "description": "Joins to clusters.cluster_id and billing_usage.cluster_id."},
            {"name": "instance_id", "type": "string", "description": "Cloud-provider VM id (i-xxx / vm-xxx)."},
            {"name": "start_time", "type": "timestamp", "description": "Always filter on this for time windows."},
            {"name": "end_time", "type": "timestamp"},
            {"name": "event_date", "type": "date", "description": "Pre-extracted CAST(start_time AS DATE)."},
            {"name": "driver", "type": "boolean", "description": "True if this is the driver node of the cluster."},
            {"name": "node_type", "type": "string", "description": "Joins to node_types.node_type."},
            {"name": "cpu_user_percent", "type": "decimal", "description": "0–100."},
            {"name": "cpu_system_percent", "type": "decimal"},
            {"name": "cpu_wait_percent", "type": "decimal"},
            {"name": "mem_used_percent", "type": "decimal"},
            {"name": "mem_swap_percent", "type": "decimal"},
            {"name": "network_sent_bytes", "type": "bigint"},
            {"name": "network_received_bytes", "type": "bigint"},
            {"name": "disk_free_bytes_per_mount_point", "type": "json", "description": "MAP<string, bigint>. Mount-path → free bytes."},
            {"name": "data_origin", "type": "string"},
            {"name": "deleted_at", "type": "timestamp"},
        ],
    },
    {
        "name": "warehouse_events",
        "description": (
            "SQL warehouse lifecycle events (system.compute.warehouse_events). "
            "Each row records a state transition for a SQL warehouse: STARTING, "
            "RUNNING, STOPPING, STOPPED, SCALED_UP, SCALED_DOWN. `cluster_count` "
            "is the active cluster count after the event. Join to `warehouses` "
            "on `warehouse_id` for the warehouse name / configuration."
        ),
        "columns": [
            {"name": "account_id", "type": "string"},
            {"name": "workspace_id", "type": "string"},
            {"name": "warehouse_id", "type": "string", "description": "Joins to warehouses.warehouse_id and billing_usage.warehouse_id."},
            {"name": "event_type", "type": "string", "description": "STARTING | RUNNING | STOPPING | STOPPED | SCALED_UP | SCALED_DOWN."},
            {"name": "cluster_count", "type": "integer", "description": "Active cluster count after this event."},
            {"name": "event_time", "type": "timestamp"},
            {"name": "event_date", "type": "date"},
            {"name": "data_origin", "type": "string"},
            {"name": "deleted_at", "type": "timestamp"},
        ],
    },
    {
        "name": "node_types",
        "description": (
            "Reference catalog of node types Databricks exposes "
            "(system.compute.node_types) with cpu / memory / gpu specs and the "
            "broad category (general-purpose, memory-optimized, gpu, …). "
            "`memory_mb` is whole megabytes. Joins to `clusters.driver_node_type`, "
            "`clusters.worker_node_type`, `billing_usage.node_type`, "
            "`node_timeline.node_type`, `instance_events.node_type`, "
            "`instance_pools.node_type`."
        ),
        "columns": [
            {"name": "account_id", "type": "string"},
            {"name": "node_type", "type": "string"},
            {"name": "core_count", "type": "decimal", "description": "vCPUs — decimal because fractional shares are possible on some serverless tiers."},
            {"name": "memory_mb", "type": "bigint"},
            {"name": "gpu_count", "type": "integer"},
            {"name": "category", "type": "string", "description": "General Purpose | Memory Optimized | Compute Optimized | GPU | Storage Optimized. NOTE: not present in upstream system.compute.node_types — NULL on real data; populated only in demo data."},
            {"name": "data_origin", "type": "string"},
            {"name": "deleted_at", "type": "timestamp"},
        ],
    },
    {
        "name": "instance_events",
        "description": (
            "VM/node lifecycle events (system.compute.node_events, surfaced as "
            "`instance_events` to match the Databricks UI label). One row per "
            "instance state transition — node-add, node-remove, node-lost, "
            "spot-loss, etc. `event_details` is a JSON STRUCT with the "
            "transition's payload (varies by event_type)."
        ),
        "columns": [
            {"name": "account_id", "type": "string"},
            {"name": "workspace_id", "type": "string"},
            {"name": "cluster_id", "type": "string"},
            {"name": "instance_id", "type": "string"},
            {"name": "instance_pool_id", "type": "string", "description": "NULL when the instance was created outside any pool."},
            {"name": "event_type", "type": "string", "description": "NODE_ADD | NODE_TERMINATING | SPOT_LOSS | RESIZED | …"},
            {"name": "event_time", "type": "timestamp"},
            {"name": "event_date", "type": "date"},
            {"name": "node_type", "type": "string"},
            {"name": "event_details", "type": "json", "description": "STRUCT payload (varies by event_type)."},
            {"name": "data_origin", "type": "string"},
            {"name": "deleted_at", "type": "timestamp"},
        ],
    },
    {
        "name": "instance_pools",
        "description": (
            "Instance pool catalog (system.compute.instance_pools). Reference "
            "table of pooled-VM definitions used to amortize VM acquisition. "
            "Join to `billing_usage.instance_pool_id` for cost attribution and "
            "to `instance_events.instance_pool_id` for capacity / lifecycle "
            "diagnostics."
        ),
        "columns": [
            {"name": "account_id", "type": "string"},
            {"name": "workspace_id", "type": "string"},
            {"name": "instance_pool_id", "type": "string"},
            {"name": "instance_pool_name", "type": "string"},
            {"name": "node_type", "type": "string"},
            {"name": "min_idle_instances", "type": "integer"},
            {"name": "max_capacity", "type": "integer"},
            {"name": "idle_instance_autotermination_minutes", "type": "integer"},
            {"name": "enable_elastic_disk", "type": "boolean"},
            {"name": "preloaded_spark_versions", "type": "json", "description": "Array of DBR versions pre-warmed on pool VMs."},
            {"name": "create_time", "type": "timestamp"},
            {"name": "delete_time", "type": "timestamp"},
            {"name": "change_time", "type": "timestamp"},
            {"name": "data_origin", "type": "string"},
            {"name": "deleted_at", "type": "timestamp"},
        ],
    },
]


NODE_POOL_RELATIONSHIPS = [
    {"from_table": "node_timeline", "from_column": "cluster_id",
     "to_table": "clusters", "to_column": "cluster_id"},
    {"from_table": "node_timeline", "from_column": "node_type",
     "to_table": "node_types", "to_column": "node_type"},
    {"from_table": "warehouse_events", "from_column": "warehouse_id",
     "to_table": "warehouses", "to_column": "warehouse_id"},
    {"from_table": "instance_events", "from_column": "cluster_id",
     "to_table": "clusters", "to_column": "cluster_id"},
    {"from_table": "instance_events", "from_column": "instance_pool_id",
     "to_table": "instance_pools", "to_column": "instance_pool_id"},
    {"from_table": "instance_events", "from_column": "node_type",
     "to_table": "node_types", "to_column": "node_type"},
    {"from_table": "instance_pools", "from_column": "node_type",
     "to_table": "node_types", "to_column": "node_type"},
    {"from_table": "instance_pools", "from_column": "instance_pool_id",
     "to_table": "billing_usage", "to_column": "instance_pool_id"},
]
