import sys 
import os 

# Add the parent directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from Database.dbconnection import DBConnection

def main():
    """Main function to fetch email snippets"""
    db = DBConnection()
    
    try:
        conn, cursor = db.connect()
        print("✅ Connected to the database")
        
        # Query to get snippet text of 5 emails
        cursor.execute("SELECT snippet_text FROM emails ORDER BY received_datetime DESC LIMIT 5")
        
        emails = cursor.fetchall()
        
        print(f"\n📧 Found {len(emails)} email snippets:")
        print("=" * 50)
        
        for i, email in enumerate(emails, 1):
            snippet = email[0]  # Get the snippet_text from the tuple
            print(f"\n{i}. {snippet[:200]}{'...' if len(snippet) > 200 else ''}")
            print("-" * 30)
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()
        print("🔌 Database connection closed")

if __name__ == "__main__":
    main()
    


