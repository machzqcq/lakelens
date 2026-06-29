"""
Static lookup of cloud VM node-type specs (vCPU / memory / storage).

Databricks' system.compute.clusters table only stores the node type *name*
(e.g. "Standard_DS3_v2", "i3.xlarge"). To surface CPU / memory in the UI we
maintain this curated map of the most common Azure, AWS, and GCP instance
types used by Databricks. Unknown types simply return None so the UI can
display "N/A" instead of breaking.
"""

from typing import Optional, TypedDict


class NodeSpec(TypedDict):
    node_type: str
    cloud: str  # "azure" | "aws" | "gcp"
    family: str  # e.g. "general-purpose", "memory-optimized", "compute-optimized", "storage-optimized"
    vcpus: int
    memory_gb: float
    local_disk_gb: Optional[float]  # None if EBS/managed-disk only
    gpu_count: Optional[int]
    gpu_type: Optional[str]


# ---------------------------------------------------------------------------
# Azure (Standard_*)
# ---------------------------------------------------------------------------
_AZURE: dict[str, NodeSpec] = {
    # D-series v2 / v3 / v4 / v5 -- general purpose
    "Standard_DS3_v2":   {"node_type": "Standard_DS3_v2",   "cloud": "azure", "family": "general-purpose",  "vcpus": 4,   "memory_gb": 14.0,  "local_disk_gb": 28.0,   "gpu_count": None, "gpu_type": None},
    "Standard_DS4_v2":   {"node_type": "Standard_DS4_v2",   "cloud": "azure", "family": "general-purpose",  "vcpus": 8,   "memory_gb": 28.0,  "local_disk_gb": 56.0,   "gpu_count": None, "gpu_type": None},
    "Standard_DS5_v2":   {"node_type": "Standard_DS5_v2",   "cloud": "azure", "family": "general-purpose",  "vcpus": 16,  "memory_gb": 56.0,  "local_disk_gb": 112.0,  "gpu_count": None, "gpu_type": None},
    "Standard_D4s_v3":   {"node_type": "Standard_D4s_v3",   "cloud": "azure", "family": "general-purpose",  "vcpus": 4,   "memory_gb": 16.0,  "local_disk_gb": 32.0,   "gpu_count": None, "gpu_type": None},
    "Standard_D8s_v3":   {"node_type": "Standard_D8s_v3",   "cloud": "azure", "family": "general-purpose",  "vcpus": 8,   "memory_gb": 32.0,  "local_disk_gb": 64.0,   "gpu_count": None, "gpu_type": None},
    "Standard_D16s_v3":  {"node_type": "Standard_D16s_v3",  "cloud": "azure", "family": "general-purpose",  "vcpus": 16,  "memory_gb": 64.0,  "local_disk_gb": 128.0,  "gpu_count": None, "gpu_type": None},
    "Standard_D32s_v3":  {"node_type": "Standard_D32s_v3",  "cloud": "azure", "family": "general-purpose",  "vcpus": 32,  "memory_gb": 128.0, "local_disk_gb": 256.0,  "gpu_count": None, "gpu_type": None},
    "Standard_D4ds_v4":  {"node_type": "Standard_D4ds_v4",  "cloud": "azure", "family": "general-purpose",  "vcpus": 4,   "memory_gb": 16.0,  "local_disk_gb": 150.0,  "gpu_count": None, "gpu_type": None},
    "Standard_D8ds_v4":  {"node_type": "Standard_D8ds_v4",  "cloud": "azure", "family": "general-purpose",  "vcpus": 8,   "memory_gb": 32.0,  "local_disk_gb": 300.0,  "gpu_count": None, "gpu_type": None},
    "Standard_D16ds_v4": {"node_type": "Standard_D16ds_v4", "cloud": "azure", "family": "general-purpose",  "vcpus": 16,  "memory_gb": 64.0,  "local_disk_gb": 600.0,  "gpu_count": None, "gpu_type": None},
    "Standard_D4ds_v5":  {"node_type": "Standard_D4ds_v5",  "cloud": "azure", "family": "general-purpose",  "vcpus": 4,   "memory_gb": 16.0,  "local_disk_gb": 150.0,  "gpu_count": None, "gpu_type": None},
    "Standard_D8ds_v5":  {"node_type": "Standard_D8ds_v5",  "cloud": "azure", "family": "general-purpose",  "vcpus": 8,   "memory_gb": 32.0,  "local_disk_gb": 300.0,  "gpu_count": None, "gpu_type": None},
    "Standard_D16ds_v5": {"node_type": "Standard_D16ds_v5", "cloud": "azure", "family": "general-purpose",  "vcpus": 16,  "memory_gb": 64.0,  "local_disk_gb": 600.0,  "gpu_count": None, "gpu_type": None},
    "Standard_D32ds_v5": {"node_type": "Standard_D32ds_v5", "cloud": "azure", "family": "general-purpose",  "vcpus": 32,  "memory_gb": 128.0, "local_disk_gb": 1200.0, "gpu_count": None, "gpu_type": None},

    # E-series -- memory optimized
    "Standard_E4s_v3":   {"node_type": "Standard_E4s_v3",   "cloud": "azure", "family": "memory-optimized", "vcpus": 4,   "memory_gb": 32.0,  "local_disk_gb": 64.0,   "gpu_count": None, "gpu_type": None},
    "Standard_E8s_v3":   {"node_type": "Standard_E8s_v3",   "cloud": "azure", "family": "memory-optimized", "vcpus": 8,   "memory_gb": 64.0,  "local_disk_gb": 128.0,  "gpu_count": None, "gpu_type": None},
    "Standard_E16s_v3":  {"node_type": "Standard_E16s_v3",  "cloud": "azure", "family": "memory-optimized", "vcpus": 16,  "memory_gb": 128.0, "local_disk_gb": 256.0,  "gpu_count": None, "gpu_type": None},
    "Standard_E32s_v3":  {"node_type": "Standard_E32s_v3",  "cloud": "azure", "family": "memory-optimized", "vcpus": 32,  "memory_gb": 256.0, "local_disk_gb": 512.0,  "gpu_count": None, "gpu_type": None},
    "Standard_E4ds_v4":  {"node_type": "Standard_E4ds_v4",  "cloud": "azure", "family": "memory-optimized", "vcpus": 4,   "memory_gb": 32.0,  "local_disk_gb": 150.0,  "gpu_count": None, "gpu_type": None},
    "Standard_E8ds_v4":  {"node_type": "Standard_E8ds_v4",  "cloud": "azure", "family": "memory-optimized", "vcpus": 8,   "memory_gb": 64.0,  "local_disk_gb": 300.0,  "gpu_count": None, "gpu_type": None},
    "Standard_E16ds_v4": {"node_type": "Standard_E16ds_v4", "cloud": "azure", "family": "memory-optimized", "vcpus": 16,  "memory_gb": 128.0, "local_disk_gb": 600.0,  "gpu_count": None, "gpu_type": None},
    "Standard_E4ds_v5":  {"node_type": "Standard_E4ds_v5",  "cloud": "azure", "family": "memory-optimized", "vcpus": 4,   "memory_gb": 32.0,  "local_disk_gb": 150.0,  "gpu_count": None, "gpu_type": None},
    "Standard_E8ds_v5":  {"node_type": "Standard_E8ds_v5",  "cloud": "azure", "family": "memory-optimized", "vcpus": 8,   "memory_gb": 64.0,  "local_disk_gb": 300.0,  "gpu_count": None, "gpu_type": None},
    "Standard_E16ds_v5": {"node_type": "Standard_E16ds_v5", "cloud": "azure", "family": "memory-optimized", "vcpus": 16,  "memory_gb": 128.0, "local_disk_gb": 600.0,  "gpu_count": None, "gpu_type": None},
    "Standard_E32ds_v5": {"node_type": "Standard_E32ds_v5", "cloud": "azure", "family": "memory-optimized", "vcpus": 32,  "memory_gb": 256.0, "local_disk_gb": 1200.0, "gpu_count": None, "gpu_type": None},

    # F-series -- compute optimized
    "Standard_F4s_v2":   {"node_type": "Standard_F4s_v2",   "cloud": "azure", "family": "compute-optimized", "vcpus": 4,  "memory_gb": 8.0,   "local_disk_gb": 32.0,   "gpu_count": None, "gpu_type": None},
    "Standard_F8s_v2":   {"node_type": "Standard_F8s_v2",   "cloud": "azure", "family": "compute-optimized", "vcpus": 8,  "memory_gb": 16.0,  "local_disk_gb": 64.0,   "gpu_count": None, "gpu_type": None},
    "Standard_F16s_v2":  {"node_type": "Standard_F16s_v2",  "cloud": "azure", "family": "compute-optimized", "vcpus": 16, "memory_gb": 32.0,  "local_disk_gb": 128.0,  "gpu_count": None, "gpu_type": None},
    "Standard_F32s_v2":  {"node_type": "Standard_F32s_v2",  "cloud": "azure", "family": "compute-optimized", "vcpus": 32, "memory_gb": 64.0,  "local_disk_gb": 256.0,  "gpu_count": None, "gpu_type": None},

    # L-series -- storage optimized
    "Standard_L4s":      {"node_type": "Standard_L4s",      "cloud": "azure", "family": "storage-optimized", "vcpus": 4,  "memory_gb": 32.0,  "local_disk_gb": 678.0,  "gpu_count": None, "gpu_type": None},
    "Standard_L8s":      {"node_type": "Standard_L8s",      "cloud": "azure", "family": "storage-optimized", "vcpus": 8,  "memory_gb": 64.0,  "local_disk_gb": 1388.0, "gpu_count": None, "gpu_type": None},
    "Standard_L16s":     {"node_type": "Standard_L16s",     "cloud": "azure", "family": "storage-optimized", "vcpus": 16, "memory_gb": 128.0, "local_disk_gb": 2807.0, "gpu_count": None, "gpu_type": None},

    # NC-series -- GPU
    "Standard_NC4as_T4_v3":  {"node_type": "Standard_NC4as_T4_v3",  "cloud": "azure", "family": "gpu", "vcpus": 4,  "memory_gb": 28.0,  "local_disk_gb": 180.0, "gpu_count": 1, "gpu_type": "NVIDIA T4"},
    "Standard_NC8as_T4_v3":  {"node_type": "Standard_NC8as_T4_v3",  "cloud": "azure", "family": "gpu", "vcpus": 8,  "memory_gb": 56.0,  "local_disk_gb": 360.0, "gpu_count": 1, "gpu_type": "NVIDIA T4"},
    "Standard_NC16as_T4_v3": {"node_type": "Standard_NC16as_T4_v3", "cloud": "azure", "family": "gpu", "vcpus": 16, "memory_gb": 110.0, "local_disk_gb": 360.0, "gpu_count": 1, "gpu_type": "NVIDIA T4"},
    "Standard_NC6s_v3":      {"node_type": "Standard_NC6s_v3",      "cloud": "azure", "family": "gpu", "vcpus": 6,  "memory_gb": 112.0, "local_disk_gb": 736.0, "gpu_count": 1, "gpu_type": "NVIDIA V100"},
    "Standard_NC12s_v3":     {"node_type": "Standard_NC12s_v3",     "cloud": "azure", "family": "gpu", "vcpus": 12, "memory_gb": 224.0, "local_disk_gb": 1474.0, "gpu_count": 2, "gpu_type": "NVIDIA V100"},
    "Standard_NC24s_v3":     {"node_type": "Standard_NC24s_v3",     "cloud": "azure", "family": "gpu", "vcpus": 24, "memory_gb": 448.0, "local_disk_gb": 2948.0, "gpu_count": 4, "gpu_type": "NVIDIA V100"},
}


# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------
_AWS: dict[str, NodeSpec] = {
    # M5 -- general purpose
    "m5.large":     {"node_type": "m5.large",    "cloud": "aws", "family": "general-purpose", "vcpus": 2,   "memory_gb": 8.0,   "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "m5.xlarge":    {"node_type": "m5.xlarge",   "cloud": "aws", "family": "general-purpose", "vcpus": 4,   "memory_gb": 16.0,  "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "m5.2xlarge":   {"node_type": "m5.2xlarge",  "cloud": "aws", "family": "general-purpose", "vcpus": 8,   "memory_gb": 32.0,  "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "m5.4xlarge":   {"node_type": "m5.4xlarge",  "cloud": "aws", "family": "general-purpose", "vcpus": 16,  "memory_gb": 64.0,  "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "m5.8xlarge":   {"node_type": "m5.8xlarge",  "cloud": "aws", "family": "general-purpose", "vcpus": 32,  "memory_gb": 128.0, "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "m5.12xlarge":  {"node_type": "m5.12xlarge", "cloud": "aws", "family": "general-purpose", "vcpus": 48,  "memory_gb": 192.0, "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "m5.16xlarge":  {"node_type": "m5.16xlarge", "cloud": "aws", "family": "general-purpose", "vcpus": 64,  "memory_gb": 256.0, "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "m5.24xlarge":  {"node_type": "m5.24xlarge", "cloud": "aws", "family": "general-purpose", "vcpus": 96,  "memory_gb": 384.0, "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},

    # M5d -- with NVMe
    "m5d.large":    {"node_type": "m5d.large",   "cloud": "aws", "family": "general-purpose", "vcpus": 2,   "memory_gb": 8.0,   "local_disk_gb": 75.0,    "gpu_count": None, "gpu_type": None},
    "m5d.xlarge":   {"node_type": "m5d.xlarge",  "cloud": "aws", "family": "general-purpose", "vcpus": 4,   "memory_gb": 16.0,  "local_disk_gb": 150.0,   "gpu_count": None, "gpu_type": None},
    "m5d.2xlarge":  {"node_type": "m5d.2xlarge", "cloud": "aws", "family": "general-purpose", "vcpus": 8,   "memory_gb": 32.0,  "local_disk_gb": 300.0,   "gpu_count": None, "gpu_type": None},
    "m5d.4xlarge":  {"node_type": "m5d.4xlarge", "cloud": "aws", "family": "general-purpose", "vcpus": 16,  "memory_gb": 64.0,  "local_disk_gb": 600.0,   "gpu_count": None, "gpu_type": None},
    "m5d.8xlarge":  {"node_type": "m5d.8xlarge", "cloud": "aws", "family": "general-purpose", "vcpus": 32,  "memory_gb": 128.0, "local_disk_gb": 1200.0,  "gpu_count": None, "gpu_type": None},

    # R5 -- memory optimized
    "r5.large":     {"node_type": "r5.large",    "cloud": "aws", "family": "memory-optimized", "vcpus": 2,  "memory_gb": 16.0,  "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "r5.xlarge":    {"node_type": "r5.xlarge",   "cloud": "aws", "family": "memory-optimized", "vcpus": 4,  "memory_gb": 32.0,  "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "r5.2xlarge":   {"node_type": "r5.2xlarge",  "cloud": "aws", "family": "memory-optimized", "vcpus": 8,  "memory_gb": 64.0,  "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "r5.4xlarge":   {"node_type": "r5.4xlarge",  "cloud": "aws", "family": "memory-optimized", "vcpus": 16, "memory_gb": 128.0, "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "r5.8xlarge":   {"node_type": "r5.8xlarge",  "cloud": "aws", "family": "memory-optimized", "vcpus": 32, "memory_gb": 256.0, "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "r5.12xlarge":  {"node_type": "r5.12xlarge", "cloud": "aws", "family": "memory-optimized", "vcpus": 48, "memory_gb": 384.0, "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "r5.16xlarge":  {"node_type": "r5.16xlarge", "cloud": "aws", "family": "memory-optimized", "vcpus": 64, "memory_gb": 512.0, "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},
    "r5.24xlarge":  {"node_type": "r5.24xlarge", "cloud": "aws", "family": "memory-optimized", "vcpus": 96, "memory_gb": 768.0, "local_disk_gb": None,    "gpu_count": None, "gpu_type": None},

    # C5 -- compute optimized
    "c5.xlarge":    {"node_type": "c5.xlarge",   "cloud": "aws", "family": "compute-optimized", "vcpus": 4,  "memory_gb": 8.0,  "local_disk_gb": None,   "gpu_count": None, "gpu_type": None},
    "c5.2xlarge":   {"node_type": "c5.2xlarge",  "cloud": "aws", "family": "compute-optimized", "vcpus": 8,  "memory_gb": 16.0, "local_disk_gb": None,   "gpu_count": None, "gpu_type": None},
    "c5.4xlarge":   {"node_type": "c5.4xlarge",  "cloud": "aws", "family": "compute-optimized", "vcpus": 16, "memory_gb": 32.0, "local_disk_gb": None,   "gpu_count": None, "gpu_type": None},
    "c5.9xlarge":   {"node_type": "c5.9xlarge",  "cloud": "aws", "family": "compute-optimized", "vcpus": 36, "memory_gb": 72.0, "local_disk_gb": None,   "gpu_count": None, "gpu_type": None},

    # i3 -- storage optimized (NVMe)
    "i3.large":     {"node_type": "i3.large",    "cloud": "aws", "family": "storage-optimized", "vcpus": 2,  "memory_gb": 15.25,  "local_disk_gb": 475.0,   "gpu_count": None, "gpu_type": None},
    "i3.xlarge":    {"node_type": "i3.xlarge",   "cloud": "aws", "family": "storage-optimized", "vcpus": 4,  "memory_gb": 30.5,   "local_disk_gb": 950.0,   "gpu_count": None, "gpu_type": None},
    "i3.2xlarge":   {"node_type": "i3.2xlarge",  "cloud": "aws", "family": "storage-optimized", "vcpus": 8,  "memory_gb": 61.0,   "local_disk_gb": 1900.0,  "gpu_count": None, "gpu_type": None},
    "i3.4xlarge":   {"node_type": "i3.4xlarge",  "cloud": "aws", "family": "storage-optimized", "vcpus": 16, "memory_gb": 122.0,  "local_disk_gb": 3800.0,  "gpu_count": None, "gpu_type": None},
    "i3.8xlarge":   {"node_type": "i3.8xlarge",  "cloud": "aws", "family": "storage-optimized", "vcpus": 32, "memory_gb": 244.0,  "local_disk_gb": 7600.0,  "gpu_count": None, "gpu_type": None},

    # GPU
    "g4dn.xlarge":  {"node_type": "g4dn.xlarge",  "cloud": "aws", "family": "gpu", "vcpus": 4,   "memory_gb": 16.0,  "local_disk_gb": 125.0,  "gpu_count": 1, "gpu_type": "NVIDIA T4"},
    "g4dn.2xlarge": {"node_type": "g4dn.2xlarge", "cloud": "aws", "family": "gpu", "vcpus": 8,   "memory_gb": 32.0,  "local_disk_gb": 225.0,  "gpu_count": 1, "gpu_type": "NVIDIA T4"},
    "g4dn.4xlarge": {"node_type": "g4dn.4xlarge", "cloud": "aws", "family": "gpu", "vcpus": 16,  "memory_gb": 64.0,  "local_disk_gb": 225.0,  "gpu_count": 1, "gpu_type": "NVIDIA T4"},
    "p3.2xlarge":   {"node_type": "p3.2xlarge",   "cloud": "aws", "family": "gpu", "vcpus": 8,   "memory_gb": 61.0,  "local_disk_gb": None,   "gpu_count": 1, "gpu_type": "NVIDIA V100"},
    "p3.8xlarge":   {"node_type": "p3.8xlarge",   "cloud": "aws", "family": "gpu", "vcpus": 32,  "memory_gb": 244.0, "local_disk_gb": None,   "gpu_count": 4, "gpu_type": "NVIDIA V100"},
}


# ---------------------------------------------------------------------------
# GCP
# ---------------------------------------------------------------------------
_GCP: dict[str, NodeSpec] = {
    "n1-standard-4":   {"node_type": "n1-standard-4",   "cloud": "gcp", "family": "general-purpose", "vcpus": 4,  "memory_gb": 15.0,  "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n1-standard-8":   {"node_type": "n1-standard-8",   "cloud": "gcp", "family": "general-purpose", "vcpus": 8,  "memory_gb": 30.0,  "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n1-standard-16":  {"node_type": "n1-standard-16",  "cloud": "gcp", "family": "general-purpose", "vcpus": 16, "memory_gb": 60.0,  "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n1-standard-32":  {"node_type": "n1-standard-32",  "cloud": "gcp", "family": "general-purpose", "vcpus": 32, "memory_gb": 120.0, "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n2-standard-4":   {"node_type": "n2-standard-4",   "cloud": "gcp", "family": "general-purpose", "vcpus": 4,  "memory_gb": 16.0,  "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n2-standard-8":   {"node_type": "n2-standard-8",   "cloud": "gcp", "family": "general-purpose", "vcpus": 8,  "memory_gb": 32.0,  "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n2-standard-16":  {"node_type": "n2-standard-16",  "cloud": "gcp", "family": "general-purpose", "vcpus": 16, "memory_gb": 64.0,  "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n2-highmem-4":    {"node_type": "n2-highmem-4",    "cloud": "gcp", "family": "memory-optimized", "vcpus": 4,  "memory_gb": 32.0,  "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n2-highmem-8":    {"node_type": "n2-highmem-8",    "cloud": "gcp", "family": "memory-optimized", "vcpus": 8,  "memory_gb": 64.0,  "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n2-highmem-16":   {"node_type": "n2-highmem-16",   "cloud": "gcp", "family": "memory-optimized", "vcpus": 16, "memory_gb": 128.0, "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n2-highcpu-8":    {"node_type": "n2-highcpu-8",    "cloud": "gcp", "family": "compute-optimized", "vcpus": 8,  "memory_gb": 8.0,   "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
    "n2-highcpu-16":   {"node_type": "n2-highcpu-16",   "cloud": "gcp", "family": "compute-optimized", "vcpus": 16, "memory_gb": 16.0,  "local_disk_gb": None, "gpu_count": None, "gpu_type": None},
}


_ALL: dict[str, NodeSpec] = {**_AZURE, **_AWS, **_GCP}


def get_spec(node_type: Optional[str]) -> Optional[NodeSpec]:
    """Look up specs for a node type. Returns None if unknown."""
    if not node_type:
        return None
    return _ALL.get(node_type)


def all_specs() -> list[NodeSpec]:
    """Return every known node spec."""
    return list(_ALL.values())


# Plain dicts of node_type -> attribute, suitable for use as SQLAlchemy
# `case({...}, value=col, else_=None)` lookup tables. Fixed at import time.
def vcpus_map() -> dict[str, int]:
    return {nt: s["vcpus"] for nt, s in _ALL.items()}


def memory_map() -> dict[str, float]:
    return {nt: s["memory_gb"] for nt, s in _ALL.items()}


def family_map() -> dict[str, str]:
    return {nt: s["family"] for nt, s in _ALL.items()}


def gpu_node_types() -> list[str]:
    """Node types that have at least one GPU."""
    return [nt for nt, s in _ALL.items() if (s["gpu_count"] or 0) > 0]


KNOWN_FAMILIES = ("general-purpose", "memory-optimized", "compute-optimized", "storage-optimized", "gpu")
