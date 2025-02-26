from fastapi import FastAPI, HTTPException

app = FastAPI()

# In-memory storage for wallets and blockchain
wallets = {}  # Example: {"user1": 100, "user2": 50}
blockchain = []  # List of blocks, where each block is a list of transactions

# Helper function to create a wallet
def create_wallet(user: str, initial_balance: float):
    if user in wallets:
        raise HTTPException(status_code=400, detail="Wallet already exists")
    wallets[user] = initial_balance

# Helper function to validate and process a transaction
def transfer_tokens(sender: str, recipient: str, amount: float):
    if sender not in wallets or recipient not in wallets:
        raise HTTPException(status_code=404, detail="Sender or recipient not found")
    if wallets[sender] < amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    
    # Perform the transfer
    wallets[sender] -= amount
    wallets[recipient] += amount
    
    # Record the transaction
    transaction = {
        "sender": sender,
        "recipient": recipient,
        "amount": amount
    }
    return transaction

# API Endpoint: Root
@app.get("/")
def read_root():
    return {"message": "Welcome to the Blockchain Project API!"}

# API Endpoint: Create a wallet
@app.post("/create_wallet")
def api_create_wallet(user: str, initial_balance: float = 0):
    create_wallet(user, initial_balance)
    return {"message": f"Wallet created for {user} with initial balance {initial_balance}"}

# API Endpoint: Check balance
@app.get("/balance/{user}")
def get_balance(user: str):
    if user not in wallets:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": user, "balance": wallets[user]}

# API Endpoint: Transfer tokens
@app.post("/transfer")
def api_transfer_tokens(sender: str, recipient: str, amount: float):
    transaction = transfer_tokens(sender, recipient, amount)
    blockchain.append([transaction])  # Add transaction to the blockchain
    return {"message": "Transaction successful", "transaction": transaction}

# API Endpoint: View blockchain
@app.get("/blockchain")
def view_blockchain():
    return {"blockchain": blockchain}