import psycopg2
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database connection details from environment variables
DB_NAME = os.getenv("DB_NAME", "ether_eye")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "yourpassword")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

def connect_db():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        print("✅ Database connection successful!")
        return conn
    except psycopg2.Error as e:
        print("❌ Error connecting to the database:", e)
        return None

# Test connection
if __name__ == "__main__":
    conn = connect_db()
    if conn:
        conn.close()
