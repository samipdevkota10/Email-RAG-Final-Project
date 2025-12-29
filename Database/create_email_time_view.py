#!/usr/bin/env python3
"""
Migration script to create email_time view.
This view enables ISO week-based analytics with company filtering.
"""

import sys
import os

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Database.dbconnection import DBConnection

def run_migration(use_db_prefix=False):
    """
    Create email_time view.
    
    Args:
        use_db_prefix: If True, use DB_* environment variables. If False, use LOCAL_DB_*
    """
    db = DBConnection(use_db_prefix=use_db_prefix)
    try:
        conn, cursor = db.connect()
        
        print("🔧 Creating email_time view...")
        cursor.execute("""
            CREATE OR REPLACE VIEW email_time AS
            SELECT 
              e.email_id,
              e.company_id,
              e.received_datetime,
              EXTRACT(ISOYEAR FROM e.received_datetime)::INT AS iso_year,
              EXTRACT(WEEK FROM e.received_datetime)::INT AS iso_week,
              DATE_TRUNC('week', e.received_datetime) AS week_start_date
            FROM emails e
            WHERE e.received_datetime IS NOT NULL
        """)
        
        cursor.execute("""
            COMMENT ON VIEW email_time IS 'Maps emails to ISO weeks for time-based analytics. Includes company_id for industry filtering.'
        """)
        
        conn.commit()
        print("✅ Migration completed successfully!")
        print("\nView created:")
        print("  - email_time (with iso_year, iso_week, company_id)")
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        if 'conn' in locals():
            conn.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Create email_time view")
    parser.add_argument("--use-db-prefix", action="store_true", 
                       help="Use DB_* environment variables instead of LOCAL_DB_*")
    
    args = parser.parse_args()
    
    print("🚀 Running migration to create email_time view...")
    run_migration(use_db_prefix=args.use_db_prefix)

