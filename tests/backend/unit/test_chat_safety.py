"""Unit tests for the chat router's SQL-safety gating.

We import the private helpers directly so we don't need a running app.
"""

from __future__ import annotations

import pytest

from routers.chat import _extract_sql, _is_safe_select


class TestExtractSql:
    def test_fenced_sql_block(self):
        raw = "```sql\nSELECT 1\n```"
        assert _extract_sql(raw) == "SELECT 1"

    def test_unfenced_returns_raw(self):
        assert _extract_sql("SELECT 1") == "SELECT 1"

    def test_fenced_without_language_tag(self):
        assert _extract_sql("```\nSELECT 1\n```") == "SELECT 1"

    def test_trailing_semicolon_stripped(self):
        assert _extract_sql("SELECT 1;") == "SELECT 1"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _extract_sql("")

    def test_with_explanatory_text_before_fence(self):
        raw = "Sure, here's the query:\n```sql\nSELECT *\nFROM t\n```\nLet me know!"
        assert _extract_sql(raw) == "SELECT *\nFROM t"


class TestIsSafeSelect:
    @pytest.mark.parametrize("sql", [
        "SELECT 1",
        "SELECT * FROM billing_usage",
        "  SELECT * FROM t WHERE x = 1  ",
        "WITH c AS (SELECT 1) SELECT * FROM c",
        # Single trailing semicolon is OK (we strip it before checking)
        "SELECT 1;",
    ])
    def test_safe_selects_pass(self, sql):
        assert _is_safe_select(sql) is True

    @pytest.mark.parametrize("sql,reason", [
        ("INSERT INTO t VALUES (1)",                 "INSERT blocked"),
        ("UPDATE t SET x = 1",                       "UPDATE blocked"),
        ("DELETE FROM t",                            "DELETE blocked"),
        ("DROP TABLE t",                             "DROP blocked"),
        ("ALTER TABLE t ADD COLUMN x INT",           "ALTER blocked"),
        ("CREATE TABLE t (x INT)",                   "CREATE blocked"),
        ("TRUNCATE t",                               "TRUNCATE blocked"),
        ("ATTACH 'foo.db'",                          "ATTACH blocked"),
        ("COPY t TO 'foo.csv'",                      "COPY blocked"),
        ("PRAGMA table_info(t)",                     "PRAGMA blocked"),
        # Multi-statement should be rejected even if both are SELECT
        ("SELECT 1; SELECT 2",                       "second statement blocked"),
        # Mixing SELECT with mutation should be rejected
        ("SELECT 1; DROP TABLE t",                   "DROP after select blocked"),
    ])
    def test_unsafe_sql_blocked(self, sql, reason):
        assert _is_safe_select(sql) is False, reason

    def test_comments_dont_create_false_positives(self):
        # Forbidden keywords *inside comments* should be ignored — the comment
        # stripping happens before the keyword scan, so a SELECT that mentions
        # 'DELETE' or 'DROP' in a comment is still safe.
        assert _is_safe_select("SELECT * FROM t -- TODO: cleanup DELETE later") is True
        assert _is_safe_select("/* note: don't DROP this */ SELECT 1") is True

    def test_real_mutations_blocked_even_with_comment_wrapping(self):
        # A real mutation outside the comment is still blocked
        assert _is_safe_select("/* harmless */ DROP TABLE t") is False
        # Trailing comment + mutation: multi-statement → rejected
        assert _is_safe_select("SELECT 1; /* hide */ DROP TABLE t") is False

    def test_case_insensitivity(self):
        assert _is_safe_select("select 1 from t") is True
        assert _is_safe_select("DeLeTe from t") is False
