#!/usr/bin/env python3
"""
Migration script to add hero image columns to the emails table.
This script adds:
  - hero_image_url: URL of extracted hero image
  - img_embedding: Raw image embedding vector (768-dim)
  - img_embedding_unit: Normalized unit vector for similarity search (768-dim)
"""

import sys
import os

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Database.dbconnection import DBConnection

def run_migration():
    """Add hero image columns to emails table."""
    db = DBConnection()
    try:
        conn, cursor = db.connect()
        
        print("🔧 Adding hero_image_url column...")
        cursor.execute("""
            ALTER TABLE emails 
            ADD COLUMN IF NOT EXISTS hero_image_url TEXT
        """)
        
        print("🔧 Adding img_embedding column (768-dim vector)...")
        cursor.execute("""
            ALTER TABLE emails 
            ADD COLUMN IF NOT EXISTS img_embedding vector(768)
        """)
        
        print("🔧 Adding img_embedding_unit column (768-dim vector)...")
        cursor.execute("""
            ALTER TABLE emails 
            ADD COLUMN IF NOT EXISTS img_embedding_unit vector(768)
        """)
        
        print("🔧 Creating index for image embedding similarity search...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_emails_img_embedding_unit 
            ON emails 
            USING ivfflat (img_embedding_unit vector_cosine_ops)
            WITH (lists = 100)
        """)
        
        conn.commit()
        print("✅ Migration completed successfully!")
        print("\nColumns added:")
        print("  - hero_image_url (TEXT)")
        print("  - img_embedding (vector(768))")
        print("  - img_embedding_unit (vector(768))")
        print("  - Index: idx_emails_img_embedding_unit")
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        if 'conn' in locals():
            conn.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    print("🚀 Running migration to add hero image columns...")
    run_migration()

