import psycopg2
from db_connection import connect_db

def insert_sample_data():
    conn = connect_db()
    if not conn:
        return
    
    try:
        cur = conn.cursor()

        # Insert wallets first
        cur.execute("INSERT INTO wallets (address) VALUES ('wallet123') ON CONFLICT (address) DO NOTHING;")
        cur.execute("INSERT INTO wallets (address) VALUES ('wallet456') ON CONFLICT (address) DO NOTHING;")

        # Sample transactions
        cur.execute("INSERT INTO transactions (tx_id, ip_address) VALUES ('tx123', '192.168.1.10');")

        # Insert transaction details
        cur.execute("INSERT INTO transaction_inputs (tx_id, wallet_address, amount) VALUES ('tx123', 'wallet123', 0.5);")
        cur.execute("INSERT INTO transaction_outputs (tx_id, wallet_address, amount) VALUES ('tx123', 'wallet456', 0.5);")

        conn.commit()
        print("✅ Sample data inserted successfully!")
    
    except psycopg2.Error as e:
        print("❌ Error inserting sample data:", e)
    
    finally:
        cur.close()
        conn.close()

# Run script
if __name__ == "__main__":
    insert_sample_data()
