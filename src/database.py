# src/database.py
"""
Production-ready database connection pooling using psycopg2.
Supports TWO connection pools:
- DBPool: Local database (chat/search)
- AnalyticsPool: AWS database (email_offers, companies tables)
"""
import logging
import threading
from contextlib import contextmanager
from typing import Optional, Generator, Tuple, Any

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extensions import cursor as Cursor, connection as Connection

from src.config import settings

log = logging.getLogger("emaillens.database")

# Thread locks for safe pool initialization
_db_pool_lock = threading.Lock()
_analytics_pool_lock = threading.Lock()


class DBPool:
    """
    Singleton database connection pool for LOCAL database (chat/search).
    Uses DATABASE_URL environment variable.
    """
    
    _pool: Optional[SimpleConnectionPool] = None
    _initialized: bool = False
    
    @classmethod
    def initialize(cls, minconn: int = 1, maxconn: int = 20) -> None:
        """Initialize the local database connection pool (thread-safe)."""
        with _db_pool_lock:
            if cls._pool is not None:
                return  # Already initialized
            
            try:
                database_url = settings.get_database_url()
                cls._pool = SimpleConnectionPool(
                    minconn=minconn,
                    maxconn=maxconn,
                    dsn=database_url,
                )
                cls._initialized = True
                log.info(f"✅ DBPool (local) initialized (min={minconn}, max={maxconn})")
            except Exception as e:
                log.error(f"❌ Failed to initialize DBPool: {e}")
                raise
    
    @classmethod
    def close(cls) -> None:
        """Close all connections in the pool."""
        if cls._pool is not None:
            cls._pool.closeall()
            cls._pool = None
            cls._initialized = False
            log.info("🔌 DBPool (local) closed.")
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if the pool has been initialized."""
        return cls._initialized and cls._pool is not None
    
    @classmethod
    @contextmanager
    def get_cursor(cls, commit: bool = False) -> Generator[Cursor, None, None]:
        """Context manager that yields a database cursor."""
        if not cls._initialized:
            cls.initialize()
        
        conn: Optional[Connection] = None
        cur: Optional[Cursor] = None
        try:
            conn = cls._pool.getconn()
            cur = conn.cursor()
            yield cur
            if commit:
                conn.commit()
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            log.error(f"Database error: {e}")
            raise
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn is not None and cls._pool is not None:
                try:
                    cls._pool.putconn(conn)
                except Exception as e:
                    log.error(f"Failed to return connection to pool: {e}")
    
    @classmethod
    @contextmanager
    def get_connection(cls) -> Generator[Tuple[Connection, Cursor], None, None]:
        """Context manager that yields both connection and cursor."""
        if not cls._initialized:
            cls.initialize()
        
        conn: Optional[Connection] = None
        cur: Optional[Cursor] = None
        try:
            conn = cls._pool.getconn()
            cur = conn.cursor()
            yield conn, cur
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn is not None and cls._pool is not None:
                try:
                    cls._pool.putconn(conn)
                except Exception:
                    pass


class AnalyticsPool:
    """
    Singleton database connection pool for ANALYTICS database (AWS).
    Uses DB_* environment variables.
    This database has: email_offers, companies tables.
    """
    
    _pool: Optional[SimpleConnectionPool] = None
    _initialized: bool = False
    
    @classmethod
    def initialize(cls, minconn: int = 1, maxconn: int = 20) -> None:
        """Initialize the analytics database connection pool (thread-safe)."""
        with _analytics_pool_lock:
            if cls._pool is not None:
                return  # Already initialized
            
            try:
                database_url = settings.get_analytics_database_url()
                cls._pool = SimpleConnectionPool(
                    minconn=minconn,
                    maxconn=maxconn,
                    dsn=database_url,
                )
                cls._initialized = True
                log.info(f"✅ AnalyticsPool (AWS) initialized (min={minconn}, max={maxconn})")
            except Exception as e:
                log.error(f"❌ Failed to initialize AnalyticsPool: {e}")
                raise
    
    @classmethod
    def close(cls) -> None:
        """Close all connections in the pool."""
        if cls._pool is not None:
            cls._pool.closeall()
            cls._pool = None
            cls._initialized = False
            log.info("🔌 AnalyticsPool (AWS) closed.")
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if the pool has been initialized."""
        return cls._initialized and cls._pool is not None
    
    @classmethod
    @contextmanager
    def get_cursor(cls, commit: bool = False) -> Generator[Cursor, None, None]:
        """
        Context manager that yields a database cursor to AWS analytics database.
        
        Use this for queries involving email_offers, companies tables.
        """
        if not cls._initialized:
            cls.initialize()
        
        conn: Optional[Connection] = None
        cur: Optional[Cursor] = None
        try:
            conn = cls._pool.getconn()
            cur = conn.cursor()
            yield cur
            if commit:
                conn.commit()
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            log.error(f"Analytics database error: {e}")
            raise
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn is not None and cls._pool is not None:
                try:
                    cls._pool.putconn(conn)
                except Exception as e:
                    log.error(f"Failed to return analytics connection to pool: {e}")
    
    @classmethod
    @contextmanager
    def get_connection(cls) -> Generator[Tuple[Connection, Cursor], None, None]:
        """Context manager that yields both connection and cursor."""
        if not cls._initialized:
            cls.initialize()
        
        conn: Optional[Connection] = None
        cur: Optional[Cursor] = None
        try:
            conn = cls._pool.getconn()
            cur = conn.cursor()
            yield conn, cur
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn is not None and cls._pool is not None:
                try:
                    cls._pool.putconn(conn)
                except Exception:
                    pass
    
    @classmethod
    def execute_one(cls, sql: str, params: tuple = ()) -> Optional[Tuple[Any, ...]]:
        """Convenience method for single-row SELECT queries."""
        with cls.get_cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    
    @classmethod
    def execute_many(cls, sql: str, params: tuple = ()) -> list:
        """Convenience method for multi-row SELECT queries."""
        with cls.get_cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# --- Backwards Compatibility Context Manager ---

@contextmanager
def db_session() -> Generator[Tuple[Connection, Cursor], None, None]:
    """
    Legacy-compatible context manager for LOCAL database.
    Yields (conn, cur) tuple for backwards compatibility.
    """
    with DBPool.get_connection() as (conn, cur):
        yield conn, cur
