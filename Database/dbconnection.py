import os
import sys
from dotenv import load_dotenv

# Backwards-compatible shim that delegates to the new pooled connections
# in src/database.py. This keeps legacy scripts working while we consolidate
# on AnalyticsPool/DBPool.

load_dotenv()

try:
    # Add project root so imports work when run from Database/ directory
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if PROJECT_ROOT not in sys.path:
        sys.path.append(PROJECT_ROOT)
    from src.database import DBPool, AnalyticsPool
except Exception as e:  # pragma: no cover - only for legacy scripts
    print(f"❌ Failed to import pooled database classes: {e}")
    raise


class DBConnection:
    """
    Legacy interface used by older scripts. Internally delegates to the new
    connection pools:
      - DBPool (local/chat)
      - AnalyticsPool (AWS with companies/email_offers)
    """

    def __init__(self, use_local: bool = True, use_db_prefix: bool = False):
        # Legacy flags:
        # - use_db_prefix=True or use_local=False => use AnalyticsPool (AWS)
        # - use_local=True => use DBPool (local)
        self.use_analytics = use_db_prefix or (not use_local)
        self.pool = AnalyticsPool if self.use_analytics else DBPool
        self.conn = None
        self.cursor = None
        self.db_type = "ANALYTICS" if self.use_analytics else "LOCAL"

    def connect(self):
        try:
            # Initialize pool on-demand
            self.pool.initialize()
            # Borrow a connection from the pool
            self.conn = self.pool._pool.getconn()  # type: ignore[attr-defined]
            self.cursor = self.conn.cursor()
            print(f"✅ Connected via pool: {self.db_type}")
            return self.conn, self.cursor
        except Exception as e:
            print(f"❌ Error connecting to {self.db_type} database: {e}")
            sys.exit(1)

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn and self.pool and getattr(self.pool, "_pool", None):
            self.pool._pool.putconn(self.conn)  # type: ignore[attr-defined]
            print(f"🔌 {self.db_type} pooled connection returned")