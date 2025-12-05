import os 
import psycopg2
from dotenv import load_dotenv
import sys

load_dotenv()

class DBConnection:
    def __init__(self, use_local=True):
        """
        Initialize database connection
        
        Args:
            use_local (bool): If True, connect to local database. If False, connect to AWS.
        """
        # Choose prefix based on which database to connect to
        prefix = "LOCAL_DB_" if use_local else "AWS_DB_"
        
        self.host = os.getenv(f"{prefix}HOST")
        self.port = os.getenv(f"{prefix}PORT")
        self.database = os.getenv(f"{prefix}NAME")
        self.user = os.getenv(f"{prefix}USER")
        self.password = os.getenv(f"{prefix}PASSWORD")
        self.conn = None
        self.cursor = None
        
        # Store which database we're connecting to for logging
        self.db_type = "LOCAL" if use_local else "AWS"

    def connect(self):
        try:
            # Check if all required credentials are present
            if not all([self.host, self.port, self.database, self.user, self.password]):
                print(f"❌ Missing {self.db_type} database credentials. Check your .env file.")
                print(f"Host: {self.host}, Port: {self.port}, DB: {self.database}, User: {self.user}")
                sys.exit(1)
            
            self.conn = psycopg2.connect(
                host=self.host, 
                port=self.port, 
                database=self.database, 
                user=self.user, 
                password=self.password
            )
            self.cursor = self.conn.cursor()
            print(f"✅ Connected to {self.db_type} database: {self.database} on {self.host}:{self.port}")
            return self.conn, self.cursor
        except Exception as e:
            print(f"❌ Error connecting to {self.db_type} database: {e}")
            sys.exit(1)

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
            print(f"🔌 {self.db_type} database connection closed")