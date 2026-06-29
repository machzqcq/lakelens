"""
Query Execution Logging Module
Supports dual-write to SQLite and JSON for long-term memory tracking.
Captures user_query, context, prompt, response, and results for LLM fine-tuning and analysis.
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import hashlib

logger = logging.getLogger(__name__)


class QueryExecutionLogger:
    """
    Logs query executions to both SQLite and JSON for persistence and analysis.
    Supports SQL and PySpark code generation with multi-provider tracking.
    """
    
    def __init__(self, db_path: str = "./logs/query_executions.db", json_path: str = "./logs/query_executions.jsonl"):
        """
        Initialize the logger with database and JSON file paths.
        
        Args:
            db_path (str): Path to SQLite database file
            json_path (str): Path to JSON Lines log file
        """
        self.db_path = db_path
        self.json_path = json_path
        
        # Create logs directory if it doesn't exist
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize SQLite database
        self._init_database()
        print(f"✓ QueryExecutionLogger initialized")
        print(f"  SQLite: {Path(self.db_path).absolute()}")
        print(f"  JSON:   {Path(self.json_path).absolute()}")
    
    def _init_database(self):
        """Create SQLite database schema if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS query_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                execution_type TEXT NOT NULL,
                user_query TEXT NOT NULL,
                system_prompt_hash TEXT,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                context TEXT,
                generated_code TEXT NOT NULL,
                llm_explanation TEXT,
                execution_status TEXT,
                result_summary TEXT,
                result_row_count INTEGER,
                execution_time_seconds REAL,
                error_message TEXT,
                api_tokens_used INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(timestamp, user_query, provider, model)
            )
        """)
        
        # Migration: Add llm_explanation column if it doesn't exist
        try:
            cursor.execute("SELECT llm_explanation FROM query_executions LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            cursor.execute("ALTER TABLE query_executions ADD COLUMN llm_explanation TEXT")
            print("  ✓ Added llm_explanation column to existing database")
        
        conn.commit()
        conn.close()
    
    def log_execution(
        self,
        user_query: str,
        system_prompt: str,
        provider: str,
        model: str,
        generated_code: str,
        execution_type: str = "sql",
        context: Optional[str] = None,
        llm_explanation: Optional[str] = None,
        execution_status: str = "success",
        result_summary: Optional[str] = None,
        result_row_count: Optional[int] = None,
        execution_time_seconds: Optional[float] = None,
        error_message: Optional[str] = None,
        api_tokens_used: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Log a query execution to both SQLite and JSON.
        
        Args:
            user_query (str): The original natural language query
            system_prompt (str): The system prompt used for generation
            provider (str): LLM provider (google, anthropic, openai, deepseek)
            model (str): Model name used
            generated_code (str): The generated SQL or PySpark code
            execution_type (str): 'sql' or 'pyspark'
            context (str): Additional context/metadata
            llm_explanation (str): LLM's explanation text (separate from code)
            execution_status (str): 'success' or 'error'
            result_summary (str): Brief summary of results
            result_row_count (int): Number of rows in result
            execution_time_seconds (float): Time taken to execute
            error_message (str): Error message if execution failed
            api_tokens_used (int): Approximate tokens used for API call
            
        Returns:
            dict: Log entry details
        """
        timestamp = datetime.utcnow().isoformat()
        system_prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]
        
        log_entry = {
            "timestamp": timestamp,
            "execution_type": execution_type,
            "user_query": user_query,
            "system_prompt_hash": system_prompt_hash,
            "provider": provider,
            "model": model,
            "context": context,
            "generated_code": generated_code,
            "llm_explanation": llm_explanation,
            "execution_status": execution_status,
            "result_summary": result_summary,
            "result_row_count": result_row_count,
            "execution_time_seconds": execution_time_seconds,
            "error_message": error_message,
            "api_tokens_used": api_tokens_used
        }
        
        # Write to SQLite
        self._write_to_sqlite(log_entry)
        
        # Write to JSON
        self._write_to_json(log_entry)
        
        return log_entry
    
    def _write_to_sqlite(self, log_entry: Dict[str, Any]):
        """Write log entry to SQLite database."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR IGNORE INTO query_executions (
                    timestamp, execution_type, user_query, system_prompt_hash,
                    provider, model, context, generated_code, llm_explanation,
                    execution_status, result_summary, result_row_count,
                    execution_time_seconds, error_message, api_tokens_used
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_entry["timestamp"],
                log_entry["execution_type"],
                log_entry["user_query"],
                log_entry["system_prompt_hash"],
                log_entry["provider"],
                log_entry["model"],
                log_entry["context"],
                log_entry["generated_code"],
                log_entry["llm_explanation"],
                log_entry["execution_status"],
                log_entry["result_summary"],
                log_entry["result_row_count"],
                log_entry["execution_time_seconds"],
                log_entry["error_message"],
                log_entry["api_tokens_used"]
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to write to SQLite: {str(e)}")
    
    def _write_to_json(self, log_entry: Dict[str, Any]):
        """Append log entry to JSON Lines file."""
        try:
            Path(self.json_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.json_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write to JSON: {str(e)}")
    
    def query_logs(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        execution_type: Optional[str] = None,
        days: int = 30,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Query logs from SQLite database.
        
        Args:
            provider (str): Filter by provider
            model (str): Filter by model
            execution_type (str): Filter by 'sql' or 'pyspark'
            days (int): Only return logs from last N days
            limit (int): Maximum number of results
            
        Returns:
            list: List of log entries matching criteria
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = "SELECT * FROM query_executions WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')"
            params = [days]
            
            if provider:
                query += " AND provider = ?"
                params.append(provider)
            if model:
                query += " AND model = ?"
                params.append(model)
            if execution_type:
                query += " AND execution_type = ?"
                params.append(execution_type)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return results
        except Exception as e:
            logger.error(f"Failed to query logs: {str(e)}")
            return []
    
    def get_success_rate(self, provider: Optional[str] = None, days: int = 30) -> float:
        """Get success rate of executions."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            query = "SELECT COUNT(*) as total, SUM(CASE WHEN execution_status='success' THEN 1 ELSE 0 END) as successes FROM query_executions WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')"
            params = [days]
            
            if provider:
                query += " AND provider = ?"
                params.append(provider)
            
            cursor.execute(query, params)
            row = cursor.fetchone()
            conn.close()
            
            total, successes = row
            return (successes / total * 100) if total > 0 else 0
        except Exception as e:
            logger.error(f"Failed to calculate success rate: {str(e)}")
            return 0
    
    def get_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get execution statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Total executions
            cursor.execute("""
                SELECT COUNT(*) FROM query_executions 
                WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')
            """, (days,))
            total = cursor.fetchone()[0]
            
            # By provider
            cursor.execute("""
                SELECT provider, COUNT(*) as count FROM query_executions 
                WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')
                GROUP BY provider
            """, (days,))
            by_provider = {row[0]: row[1] for row in cursor.fetchall()}
            
            # By type
            cursor.execute("""
                SELECT execution_type, COUNT(*) as count FROM query_executions 
                WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')
                GROUP BY execution_type
            """, (days,))
            by_type = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Success rate
            cursor.execute("""
                SELECT COUNT(*) as total, SUM(CASE WHEN execution_status='success' THEN 1 ELSE 0 END) as successes 
                FROM query_executions WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')
            """, (days,))
            total_row, success_row = cursor.fetchone()
            success_rate = (success_row / total_row * 100) if total_row > 0 else 0
            
            conn.close()
            
            return {
                "total_executions": total,
                "by_provider": by_provider,
                "by_type": by_type,
                "success_rate": success_rate,
                "days": days
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {str(e)}")
            return {}


# Global logger instance
_query_logger = None

def get_query_logger() -> QueryExecutionLogger:
    """Get or create the global query logger instance."""
    global _query_logger
    if _query_logger is None:
        _query_logger = QueryExecutionLogger()
    return _query_logger
