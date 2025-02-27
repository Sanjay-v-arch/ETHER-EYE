from fastapi import FastAPI
import requests

app = FastAPI()

# Welcome endpoint
@app.get("/")
def home():
    return {"message": "Crypto Analysis & Intelligence Mapping Tool"}

# Trace a transaction
@app.get("/trace/{tx_id}")
def trace_transaction(tx_id: str):
    url = f"https://api.blockcypher.com/v1/btc/main/txs/{tx_id}"
    response = requests.get(url).json()
    return {
        "tx_id": tx_id,
        "sender": response.get("inputs", [{}])[0].get("addresses", ["unknown"])[0],
        "recipient": response.get("outputs", [{}])[0].get("addresses", ["unknown"])[0],
        "amount": response.get("total", 0) / 100000000,  # Convert satoshis to BTC
        "timestamp": response.get("received", "unknown")
    }