#!/usr/bin/env python3
"""
Test script to verify database connection using DB_* environment variables.
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def test_connection():
    """Test connection to database using DB_* environment variables."""
    
    # Get credentials from environment
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    database = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    
    # Check if all credentials are present
    missing = []
    if not host:
        missing.append("DB_HOST")
    if not port:
        missing.append("DB_PORT")
    if not database:
        missing.append("DB_NAME")
    if not user:
        missing.append("DB_USER")
    if not password:
        missing.append("DB_PASSWORD")
    
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        print("\nPlease ensure your .env file contains:")
        print("  DB_HOST=your_host")
        print("  DB_PORT=5432")
        print("  DB_NAME=your_database")
        print("  DB_USER=your_user")
        print("  DB_PASSWORD=your_password")
        sys.exit(1)
    
    print("🔍 Testing database connection...")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Database: {database}")
    print(f"   User: {user}")
    
    try:
        # Attempt connection
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        
        cursor = conn.cursor()
        
        # Test basic query
        print("\n✅ Connection successful!")
        
        # Get database version
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"\n📊 Database version: {version.split(',')[0]}")
        
        # Check if emails table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'emails'
            );
        """)
        emails_exists = cursor.fetchone()[0]
        
        if emails_exists:
            print("✅ 'emails' table found")
            
            # Count emails
            cursor.execute("SELECT COUNT(*) FROM emails")
            email_count = cursor.fetchone()[0]
            print(f"   Total emails: {email_count:,}")
            
            # Count 2025 emails
            cursor.execute("""
                SELECT COUNT(*) 
                FROM emails 
                WHERE received_datetime >= '2025-01-01' 
                  AND received_datetime < '2026-01-01'
            """)
            emails_2025 = cursor.fetchone()[0]
            print(f"   Emails from 2025: {emails_2025:,}")
            
            # Check date range
            cursor.execute("""
                SELECT 
                    MIN(received_datetime) as min_date,
                    MAX(received_datetime) as max_date
                FROM emails
                WHERE received_datetime IS NOT NULL
            """)
            date_range = cursor.fetchone()
            if date_range[0]:
                print(f"   Date range: {date_range[0]} to {date_range[1]}")
        else:
            print("⚠️  'emails' table not found")
        
        # Check if email_offers table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'email_offers'
            );
        """)
        offers_exists = cursor.fetchone()[0]
        
        if offers_exists:
            print("✅ 'email_offers' table found")
            cursor.execute("SELECT COUNT(*) FROM email_offers")
            offers_count = cursor.fetchone()[0]
            print(f"   Total offers extracted: {offers_count:,}")
        else:
            print("⚠️  'email_offers' table not found (you may need to run the migration)")
        
        cursor.close()
        conn.close()
        
        print("\n✅ Connection test completed successfully!")
        return True
        
    except psycopg2.OperationalError as e:
        print(f"\n❌ Connection failed: {e}")
        print("\nCommon issues:")
        print("  - Check if the database server is running")
        print("  - Verify host, port, and database name are correct")
        print("  - Check if your IP is whitelisted (for AWS RDS)")
        print("  - Verify username and password are correct")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_connection()

