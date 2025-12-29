#!/usr/bin/env python3
"""
Migration script to create email_offers and etl_runs tables.
This script sets up the infrastructure for the offer extraction pipeline.
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
    Create email_offers and etl_runs tables.
    
    Args:
        use_db_prefix: If True, use DB_* environment variables. If False, use LOCAL_DB_*
    """
    db = DBConnection(use_db_prefix=use_db_prefix)
    try:
        conn, cursor = db.connect()
        
        # First, check the data type and constraints of emails.email_id
        print("🔍 Checking emails table structure...")
        cursor.execute("""
            SELECT data_type 
            FROM information_schema.columns 
            WHERE table_name = 'emails' AND column_name = 'email_id'
        """)
        result = cursor.fetchone()
        
        if not result:
            print("❌ Error: emails.email_id column not found!")
            sys.exit(1)
        
        email_id_type = result[0]
        print(f"   Found emails.email_id type: {email_id_type}")
        
        # Check if email_id has a primary key or unique constraint
        cursor.execute("""
            SELECT constraint_type
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'emails' 
                AND kcu.column_name = 'email_id'
                AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
        """)
        constraint_result = cursor.fetchone()
        
        if not constraint_result:
            print("   ⚠️  Warning: emails.email_id does not have a PRIMARY KEY or UNIQUE constraint")
            print("   Foreign key constraint will be skipped")
            has_pk = False
        else:
            print(f"   Found constraint: {constraint_result[0]}")
            has_pk = True
        
        # Map PostgreSQL types to appropriate types for foreign key
        # Use INTEGER for INT/SERIAL, BIGINT for BIGSERIAL
        if 'int' in email_id_type.lower() or 'serial' in email_id_type.lower():
            if 'big' in email_id_type.lower():
                fk_type = "BIGINT"
            else:
                fk_type = "INTEGER"
        else:
            # Default to INTEGER if type is unexpected
            fk_type = "INTEGER"
        
        print(f"   Using {fk_type} for email_offers.email_id")
        
        print("🔧 Creating email_offers table...")
        # Create table without foreign key constraint first
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS email_offers (
              offer_id        BIGSERIAL PRIMARY KEY,
              email_id        {fk_type} NOT NULL,

              discount_type   TEXT,
              percent_off     NUMERIC(6,2),
              amount_off      NUMERIC(10,2),
              currency        TEXT,
              is_up_to        BOOLEAN DEFAULT FALSE,
              min_spend       NUMERIC(10,2),
              promo_code      TEXT,

              offer_text      TEXT,
              confidence      NUMERIC(4,3) DEFAULT 1.0,

              created_at      TIMESTAMPTZ DEFAULT now()
            )
        """)
        
        # Commit table creation before trying FK constraint
        conn.commit()
        print("   ✓ Table created successfully")
        
        # Add foreign key constraint separately (only if PK exists)
        if has_pk:
            print("🔧 Adding foreign key constraint...")
            try:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint 
                            WHERE conname = 'email_offers_email_id_fkey'
                        ) THEN
                            ALTER TABLE email_offers
                            ADD CONSTRAINT email_offers_email_id_fkey
                            FOREIGN KEY (email_id) 
                            REFERENCES emails(email_id) 
                            ON DELETE CASCADE;
                        END IF;
                    END $$;
                """)
                conn.commit()
                print("   ✓ Foreign key constraint added")
            except Exception as fk_error:
                conn.rollback()
                print(f"   ⚠️  Could not add foreign key constraint: {fk_error}")
                print("   Continuing without foreign key constraint...")
        else:
            print("   ⚠️  Skipping foreign key constraint (no PK/UNIQUE on emails.email_id)")
        
        print("🔧 Creating indexes on email_offers...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_email_offers_email_id ON email_offers(email_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_email_offers_discount_type ON email_offers(discount_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_email_offers_created_at ON email_offers(created_at)
        """)
        
        print("🔧 Creating etl_runs table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS etl_runs (
              pipeline        TEXT PRIMARY KEY,
              last_email_id   INT,
              updated_at      TIMESTAMPTZ DEFAULT now()
            )
        """)
        
        conn.commit()
        print("✅ Migration completed successfully!")
        print("\nTables created:")
        print("  - email_offers (with indexes)")
        print("  - etl_runs")
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        if 'conn' in locals():
            conn.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Create offer extraction tables")
    parser.add_argument("--use-db-prefix", action="store_true", 
                       help="Use DB_* environment variables instead of LOCAL_DB_*")
    
    args = parser.parse_args()
    
    print("🚀 Running migration to create offer extraction tables...")
    run_migration(use_db_prefix=args.use_db_prefix)

