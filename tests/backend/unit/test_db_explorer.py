"""Unit tests for the admin Database Explorer's read-only SQL guard.

`routers.db_explorer._is_safe_select` returns (ok, reason). It is stricter
than the chatbot guard: it must *start* with SELECT/WITH and rejects a
broader Postgres keyword blocklist (SET/COPY/GRANT/DO/...).
"""

from __future__ import annotations

import pytest

from routers.db_explorer import _is_safe_select


class TestSafe:
    @pytest.mark.parametrize("sql", [
        "SELECT 1",
        "select * from billing_usage limit 10",
        "  SELECT a, b FROM t WHERE x = 1  ",
        "WITH c AS (SELECT 1 AS n) SELECT * FROM c",
        "SELECT 1 -- trailing comment with the word DELETE in it",
        "/* DROP note */ SELECT 1",
    ])
    def test_allowed(self, sql):
        ok, reason = _is_safe_select(sql)
        assert ok is True, f"{sql!r} should be allowed, got: {reason}"


class TestBlocked:
    @pytest.mark.parametrize("sql", [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET x = 1",
        "DELETE FROM t",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN x int",
        "CREATE TABLE t (x int)",
        "TRUNCATE t",
        "GRANT SELECT ON t TO public",
        "REVOKE ALL ON t FROM public",
        "COPY t TO '/tmp/x.csv'",
        "DO $$ BEGIN END $$",
        "SET statement_timeout = 0",
        "CALL some_proc()",
        "VACUUM FULL t",
    ])
    def test_mutations_and_ddl_blocked(self, sql):
        ok, _ = _is_safe_select(sql)
        assert ok is False, f"{sql!r} must be blocked"

    def test_multi_statement_blocked(self):
        ok, reason = _is_safe_select("SELECT 1; SELECT 2")
        assert ok is False
        assert "Multiple statements" in reason

    def test_must_start_with_select_or_with(self):
        ok, reason = _is_safe_select("EXPLAIN SELECT 1")
        assert ok is False
        assert "SELECT" in reason

    def test_empty_blocked(self):
        ok, _ = _is_safe_select("   -- only a comment\n  ")
        assert ok is False

    def test_real_mutation_hidden_after_comment_blocked(self):
        ok, _ = _is_safe_select("/* harmless */ DROP TABLE t")
        assert ok is False
