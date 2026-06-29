"""Unit tests for backend/storage.py (local mode only — cloud mode is integration territory)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

import storage


@pytest.fixture
def temp_data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a temp folder and DATA_STORE at 'local'."""
    monkeypatch.setenv("DATA_STORE", "local")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path


def _make_df():
    return pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]})


class TestBackingStore:
    def test_default_is_local(self, monkeypatch):
        monkeypatch.delenv("DATA_STORE", raising=False)
        assert storage.backing_store() == "local"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("DATA_STORE", "S3")
        assert storage.backing_store() == "s3"

    def test_whitespace_trimmed(self, monkeypatch):
        monkeypatch.setenv("DATA_STORE", "  azure  ")
        assert storage.backing_store() == "azure"


class TestDataUri:
    def test_local_path_joining(self, temp_data_dir):
        uri = storage.data_uri("foo.parquet")
        assert uri.endswith("foo.parquet")
        assert str(temp_data_dir) in uri


class TestListParquet:
    def test_returns_empty_when_dir_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATA_STORE", "local")
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "nope"))
        assert storage.list_parquet("billing_usage") == []

    def test_lists_matching_prefix_sorted(self, temp_data_dir):
        df = _make_df()
        # Create files in non-sorted order
        for d in ["2026-05-09", "2026-04-19", "2026-04-24"]:
            df.to_parquet(temp_data_dir / f"billing_usage_{d}.parquet", index=False)
        # And a non-matching file
        df.to_parquet(temp_data_dir / "clusters_2026-05-09.parquet", index=False)

        files = storage.list_parquet("billing_usage")
        assert len(files) == 3
        # Should be lex-sorted (== chronological for YYYY-MM-DD)
        assert all("billing_usage" in f for f in files)
        assert files == sorted(files)

    def test_latest_picks_most_recent(self, temp_data_dir):
        df = _make_df()
        for d in ["2026-04-09", "2026-05-09", "2026-04-24"]:
            df.to_parquet(temp_data_dir / f"billing_usage_{d}.parquet", index=False)
        latest = storage.latest_parquet("billing_usage")
        assert latest is not None
        assert "2026-05-09" in latest

    def test_latest_returns_none_when_missing(self, temp_data_dir):
        assert storage.latest_parquet("nothing_here") is None


class TestReadWrite:
    def test_roundtrip_local(self, temp_data_dir):
        df = _make_df()
        uri = storage.data_uri("test.parquet")
        storage.write_parquet(df, uri)
        assert Path(uri).exists()

        df2 = storage.read_parquet(uri)
        pd.testing.assert_frame_equal(df.reset_index(drop=True), df2.reset_index(drop=True))


class TestRootValidation:
    def test_s3_without_bucket_raises(self, monkeypatch):
        monkeypatch.setenv("DATA_STORE", "s3")
        monkeypatch.delenv("DATA_S3_BUCKET", raising=False)
        with pytest.raises(RuntimeError, match="DATA_S3_BUCKET"):
            storage.data_uri("x.parquet")

    def test_azure_without_account_raises(self, monkeypatch):
        monkeypatch.setenv("DATA_STORE", "azure")
        monkeypatch.delenv("DATA_AZURE_ACCOUNT", raising=False)
        monkeypatch.delenv("DATA_AZURE_CONTAINER", raising=False)
        with pytest.raises(RuntimeError):
            storage.data_uri("x.parquet")

    def test_gcs_without_bucket_raises(self, monkeypatch):
        monkeypatch.setenv("DATA_STORE", "gcs")
        monkeypatch.delenv("DATA_GCS_BUCKET", raising=False)
        with pytest.raises(RuntimeError, match="DATA_GCS_BUCKET"):
            storage.data_uri("x.parquet")

    def test_unknown_store_raises(self, monkeypatch):
        monkeypatch.setenv("DATA_STORE", "etcd")
        with pytest.raises(RuntimeError, match="Unknown DATA_STORE"):
            storage.data_uri("x.parquet")
