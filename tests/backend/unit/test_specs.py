"""Unit tests for the node_specs / warehouse_specs lookups."""

from __future__ import annotations

import pytest

from node_specs import KNOWN_FAMILIES, all_specs, family_map, get_spec, gpu_node_types, memory_map, vcpus_map
from warehouse_specs import get_size_spec


class TestNodeSpecs:
    def test_known_azure_node(self):
        spec = get_spec("Standard_DS3_v2")
        assert spec is not None
        assert spec["vcpus"] == 4
        assert spec["memory_gb"] == 14.0
        assert spec["cloud"] == "azure"

    def test_known_aws_node(self):
        spec = get_spec("m5.xlarge")
        assert spec is not None
        assert spec["vcpus"] == 4
        assert spec["memory_gb"] == 16.0
        assert spec["cloud"] == "aws"

    def test_known_gcp_node(self):
        spec = get_spec("n1-standard-4")
        assert spec is not None
        assert spec["vcpus"] == 4
        assert spec["cloud"] == "gcp"

    def test_unknown_node_returns_none(self):
        assert get_spec("Standard_NOT_A_THING") is None
        assert get_spec(None) is None
        assert get_spec("") is None

    def test_all_specs_nonempty_and_typed(self):
        specs = all_specs()
        assert len(specs) > 10
        for s in specs:
            assert isinstance(s["vcpus"], int) and s["vcpus"] > 0
            assert isinstance(s["memory_gb"], (int, float)) and s["memory_gb"] > 0
            assert s["family"] in KNOWN_FAMILIES

    def test_lookup_maps_consistent(self):
        v = vcpus_map()
        m = memory_map()
        f = family_map()
        assert set(v) == set(m) == set(f)

    def test_gpu_node_types_have_gpu(self):
        for nt in gpu_node_types():
            spec = get_spec(nt)
            assert spec is not None
            assert (spec["gpu_count"] or 0) > 0


class TestWarehouseSpecs:
    @pytest.mark.parametrize("size,expected_dbu", [
        ("2X_SMALL", 4),
        ("X_SMALL", 6),
        ("SMALL", 12),
        ("MEDIUM", 24),
        ("LARGE", 40),
        ("X_LARGE", 80),
        ("2X_LARGE", 144),
        ("3X_LARGE", 272),
        ("4X_LARGE", 528),
    ])
    def test_known_sizes(self, size, expected_dbu):
        spec = get_size_spec(size)
        assert spec is not None
        assert spec["max_dbu_per_hour"] == expected_dbu

    def test_case_insensitive(self):
        assert get_size_spec("small") == get_size_spec("SMALL")
        assert get_size_spec("MEDIUM") == get_size_spec("medium")

    def test_unknown_size_returns_none(self):
        assert get_size_spec("HUGE") is None
        assert get_size_spec(None) is None
        assert get_size_spec("") is None

    def test_dbu_monotonically_increases_with_size(self):
        # 2X-Small < X-Small < Small < Medium < Large < X-Large < 2X-Large < 3X-Large < 4X-Large
        order = ["2X_SMALL", "X_SMALL", "SMALL", "MEDIUM", "LARGE",
                 "X_LARGE", "2X_LARGE", "3X_LARGE", "4X_LARGE"]
        dbus = [get_size_spec(s)["max_dbu_per_hour"] for s in order]
        assert dbus == sorted(dbus), "DBU/hr should monotonically increase"
