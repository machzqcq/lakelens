"""
Static lookup of Databricks SQL warehouse t-shirt size -> capacity specs.

Databricks SQL warehouses are sized using t-shirt sizes (2X-Small ... 4X-Large).
Each size implies a fixed DBU-per-hour rate (the SKU price is then applied per
DBU). Source: Databricks SQL warehouse pricing reference.

Keys match `warehouses.warehouse_size` (e.g. "SMALL", "2X_LARGE").
"""

from typing import Optional, TypedDict


class WarehouseSizeSpec(TypedDict):
    size: str
    label: str           # display label, e.g. "2X-Large"
    max_dbu_per_hour: int
    cluster_count: int   # number of underlying compute clusters at peak


_SPECS: dict[str, WarehouseSizeSpec] = {
    "2X_SMALL": {"size": "2X_SMALL", "label": "2X-Small", "max_dbu_per_hour": 4,   "cluster_count": 1},
    "X_SMALL":  {"size": "X_SMALL",  "label": "X-Small",  "max_dbu_per_hour": 6,   "cluster_count": 1},
    "SMALL":    {"size": "SMALL",    "label": "Small",    "max_dbu_per_hour": 12,  "cluster_count": 1},
    "MEDIUM":   {"size": "MEDIUM",   "label": "Medium",   "max_dbu_per_hour": 24,  "cluster_count": 2},
    "LARGE":    {"size": "LARGE",    "label": "Large",    "max_dbu_per_hour": 40,  "cluster_count": 4},
    "X_LARGE":  {"size": "X_LARGE",  "label": "X-Large",  "max_dbu_per_hour": 80,  "cluster_count": 8},
    "2X_LARGE": {"size": "2X_LARGE", "label": "2X-Large", "max_dbu_per_hour": 144, "cluster_count": 16},
    "3X_LARGE": {"size": "3X_LARGE", "label": "3X-Large", "max_dbu_per_hour": 272, "cluster_count": 32},
    "4X_LARGE": {"size": "4X_LARGE", "label": "4X-Large", "max_dbu_per_hour": 528, "cluster_count": 64},
}


def get_size_spec(warehouse_size: Optional[str]) -> Optional[WarehouseSizeSpec]:
    """Look up the spec for a t-shirt size. Returns None for unknown sizes."""
    if not warehouse_size:
        return None
    return _SPECS.get(warehouse_size.upper())
