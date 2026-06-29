"""
Pluggable parquet storage layer.

Selected by the ``DATA_STORE`` env var:

  - ``local`` (default): files in a local directory (``DATA_DIR``).
  - ``s3``:    files in an S3 bucket (``DATA_S3_BUCKET`` + optional ``DATA_S3_PREFIX``).
  - ``azure``: files in an Azure Blob container (``DATA_AZURE_ACCOUNT`` +
               ``DATA_AZURE_CONTAINER`` + optional ``DATA_AZURE_PREFIX``).
  - ``gcs``:   files in a Google Cloud Storage bucket (``DATA_GCS_BUCKET`` +
               optional ``DATA_GCS_PREFIX``).

The module exposes:

  - :func:`backing_store`   — returns the active store name
  - :func:`data_uri`        — full path / URI for a filename
  - :func:`list_parquet`    — list parquet URIs matching ``<prefix>_*.parquet``
  - :func:`latest_parquet`  — most-recent file matching that prefix (sort lex)
  - :func:`read_parquet`    — pandas DataFrame from a URI
  - :func:`write_parquet`   — write a DataFrame
  - :func:`duckdb_setup`    — install + load DuckDB extensions and creds for
                              the active store, so DuckDB can ``read_parquet``
                              the URIs directly

For S3 / Azure / GCS we use ``fsspec``-aware pandas (``s3fs``, ``adlfs``,
``gcsfs``) on the Python side, and DuckDB's native ``httpfs`` / ``azure``
extensions on the SQL side. Both reach the same blobs.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import pandas as pd
    import duckdb


# ---------------------------------------------------------------------------
# Config (reread each call so tests can monkey-patch env)
# ---------------------------------------------------------------------------

def backing_store() -> str:
    """Return the active store: 'local' | 's3' | 'azure' | 'gcs'."""
    return os.getenv("DATA_STORE", "local").strip().lower()


def _local_root() -> str:
    return os.getenv("DATA_DIR", "data")


def _s3_root() -> str:
    bucket = os.getenv("DATA_S3_BUCKET")
    if not bucket:
        raise RuntimeError("DATA_STORE=s3 but DATA_S3_BUCKET is unset")
    prefix = os.getenv("DATA_S3_PREFIX", "").strip("/")
    return f"s3://{bucket}/{prefix}".rstrip("/")


def _azure_root() -> str:
    account = os.getenv("DATA_AZURE_ACCOUNT")
    container = os.getenv("DATA_AZURE_CONTAINER")
    if not account or not container:
        raise RuntimeError("DATA_STORE=azure requires DATA_AZURE_ACCOUNT and DATA_AZURE_CONTAINER")
    prefix = os.getenv("DATA_AZURE_PREFIX", "").strip("/")
    # adlfs / fsspec scheme: az://<container>/<key>
    # (it picks up the account from AZURE_STORAGE_ACCOUNT or the connection string)
    return f"az://{container}/{prefix}".rstrip("/")


def _gcs_root() -> str:
    bucket = os.getenv("DATA_GCS_BUCKET")
    if not bucket:
        raise RuntimeError("DATA_STORE=gcs but DATA_GCS_BUCKET is unset")
    prefix = os.getenv("DATA_GCS_PREFIX", "").strip("/")
    return f"gs://{bucket}/{prefix}".rstrip("/")


def _root() -> str:
    store = backing_store()
    if store == "local":
        return _local_root()
    if store == "s3":
        return _s3_root()
    if store == "azure":
        return _azure_root()
    if store == "gcs":
        return _gcs_root()
    raise RuntimeError(f"Unknown DATA_STORE: {store!r}")


# ---------------------------------------------------------------------------
# fsspec storage_options for pandas read/write
# ---------------------------------------------------------------------------

def _storage_options() -> Optional[dict[str, Any]]:
    """Per-cloud storage options passed to pandas / fsspec."""
    store = backing_store()
    if store == "s3":
        opts: dict[str, Any] = {}
        # AWS_REGION is honored by s3fs/boto3 from env automatically;
        # explicit endpoint is needed for non-AWS S3-compatible stores.
        endpoint = os.getenv("AWS_S3_ENDPOINT_URL")
        if endpoint:
            opts["client_kwargs"] = {"endpoint_url": endpoint}
        return opts or None
    if store == "azure":
        cs = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if cs:
            return {"connection_string": cs}
        # Or use account_name + account_key
        account = os.getenv("DATA_AZURE_ACCOUNT")
        key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
        if account and key:
            return {"account_name": account, "account_key": key}
        # Else rely on adlfs default chain (CLI / managed identity)
        return None
    if store == "gcs":
        # gcsfs uses GOOGLE_APPLICATION_CREDENTIALS or compute-engine creds.
        return None
    return None


# ---------------------------------------------------------------------------
# Public API: paths / URIs
# ---------------------------------------------------------------------------

def data_uri(filename: str) -> str:
    """Build the full path/URI for ``filename`` under the active store."""
    root = _root()
    sep = "" if root.endswith("/") else "/"
    return f"{root}{sep}{filename}"


# ---------------------------------------------------------------------------
# List / find
# ---------------------------------------------------------------------------

def list_parquet(prefix: str) -> list[str]:
    """All parquet files matching ``<prefix>_*.parquet`` under the store, sorted asc."""
    store = backing_store()
    pattern = f"{prefix}_*.parquet"

    if store == "local":
        from pathlib import Path
        path = Path(_local_root())
        if not path.exists():
            return []
        return sorted(str(p) for p in path.glob(pattern))

    # Cloud: use fsspec
    import fsspec  # imported lazily so local-only deployments don't need it
    root = _root()
    fs, _ = fsspec.url_to_fs(root, **(_storage_options() or {}))
    glob_pattern = f"{root}/{pattern}".replace("//", "/").replace(":/", "://")
    try:
        matches = fs.glob(glob_pattern)
    except Exception as e:
        logger.warning("[storage] glob failed for %s: %s", glob_pattern, e)
        return []
    # fsspec returns plain paths without the scheme; rebuild full URIs
    scheme = root.split("://", 1)[0]
    return sorted(
        m if "://" in m else f"{scheme}://{m.lstrip('/')}"
        for m in matches
    )


def latest_parquet(prefix: str) -> Optional[str]:
    """Most-recent file matching ``<prefix>_*.parquet`` (lexicographic, our names use ISO dates)."""
    matches = list_parquet(prefix)
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def read_parquet(uri: str) -> "pd.DataFrame":
    """Read a parquet URI / path into a pandas DataFrame."""
    import pandas as pd
    return pd.read_parquet(uri, storage_options=_storage_options())


def write_parquet(df: "pd.DataFrame", uri: str) -> str:
    """Write a DataFrame as parquet. Returns the URI written."""
    # Make sure parent dir exists for local writes
    if backing_store() == "local":
        from pathlib import Path
        Path(uri).parent.mkdir(parents=True, exist_ok=True)
    df.attrs = {}  # PySpark plan metadata isn't JSON-serializable
    df.to_parquet(uri, index=False, storage_options=_storage_options())
    return uri


# ---------------------------------------------------------------------------
# DuckDB integration
# ---------------------------------------------------------------------------

def duckdb_setup(con: "duckdb.DuckDBPyConnection") -> None:
    """Install + load the DuckDB extensions needed for the active store and
    push credentials in. Safe to call multiple times — extensions are cached."""

    store = backing_store()
    if store == "local":
        return

    if store == "s3":
        con.execute("INSTALL httpfs; LOAD httpfs;")
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
        con.execute(f"SET s3_region='{region}';")
        # Explicit creds only if env-pair is present; otherwise let DuckDB
        # use the AWS default credential chain (IAM role / IMDS).
        ak = os.getenv("AWS_ACCESS_KEY_ID")
        sk = os.getenv("AWS_SECRET_ACCESS_KEY")
        if ak and sk:
            con.execute(f"SET s3_access_key_id='{ak}';")
            con.execute(f"SET s3_secret_access_key='{sk}';")
        token = os.getenv("AWS_SESSION_TOKEN")
        if token:
            con.execute(f"SET s3_session_token='{token}';")
        endpoint = os.getenv("AWS_S3_ENDPOINT_URL")
        if endpoint:
            # endpoint URL → DuckDB wants host only, no scheme
            host = endpoint.replace("https://", "").replace("http://", "").rstrip("/")
            con.execute(f"SET s3_endpoint='{host}';")

    elif store == "azure":
        con.execute("INSTALL azure; LOAD azure;")
        cs = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if cs:
            # DuckDB's azure ext consumes a connection string directly
            con.execute(f"SET azure_storage_connection_string='{cs}';")
        else:
            account = os.getenv("DATA_AZURE_ACCOUNT")
            if account:
                con.execute(f"SET azure_account_name='{account}';")

    elif store == "gcs":
        # GCS via the S3-compatible XML API (HMAC keys). Native
        # `gs://` URIs are accepted by DuckDB ≥1.1 with httpfs.
        con.execute("INSTALL httpfs; LOAD httpfs;")
        ak = os.getenv("GCS_HMAC_ACCESS_KEY")
        sk = os.getenv("GCS_HMAC_SECRET_KEY")
        if ak and sk:
            con.execute("SET s3_endpoint='storage.googleapis.com';")
            con.execute("SET s3_url_style='path';")
            con.execute(f"SET s3_access_key_id='{ak}';")
            con.execute(f"SET s3_secret_access_key='{sk}';")
            con.execute("SET s3_region='auto';")


def duckdb_uri(filename_or_glob: str) -> str:
    """Translate a stored filename to a URI DuckDB's read_parquet can consume."""
    return data_uri(filename_or_glob)
