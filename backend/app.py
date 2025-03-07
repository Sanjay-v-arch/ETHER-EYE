# backend/app.py
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import threading
import queue
import logging
from blockchain import BlockchainConnector
from tracer import TransactionTracer
from patterns import PatternDetector
from contracts import ContractAnalyzer
from backend.tracing import SessionFactory, get_neo4j_driver
import schedule
import time
import json

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

state = {
    "graph": {},
    "history": [],
    "suspicious": {},
    "queue": queue.Queue()
}

class CryptoAnalysisTool:
    def __init__(self):
        self.connector = BlockchainConnector()
        self.tracer = TransactionTracer(self.connector, get_neo4j_driver())
        self.detector = PatternDetector(self.connector)
        self.analyzer = ContractAnalyzer()
        self.watched_addresses = set()
        self.load_config()

    def load_config(self):
        with open("config.json", "r") as f:
            config = json.load(f)
            self.watched_addresses.update(config.get("watched_addresses", []))

    def monitor(self):
        for address in self.watched_addresses:
            blockchain = self.detect_blockchain(address)
            self.stream_transactions(address, blockchain)

    def detect_blockchain(self, address: str) -> str:
        if address.startswith("0x"): return "ethereum"
        elif address.startswith(("1", "3", "bc1")): return "bitcoin"
        elif address.startswith("addr1"): return "cardano"
        else: return "solana"  # Simplified detection

    def stream_transactions(self, address: str, blockchain: str):
        if blockchain == "ethereum":
            self.connector.stream_ethereum_transactions(address)

    def process_queue(self):
        while True:
            try:
                tx = state["queue"].get(timeout=1)
                self.process_transaction(tx)
                socketio.emit("update", {
                    "graph": state["graph"],
                    "history": state["history"],
                    "suspicious": state["suspicious"]
                })
                state["queue"].task_done()
            except queue.Empty:
                time.sleep(1)

    def process_transaction(self, tx: dict):
        graph = self.tracer.trace_transaction(tx["hash"], tx["blockchain"])
        scores = self.detector.analyze_wallet(tx["from"], tx["blockchain"])
        state["graph"] = {"nodes": list(graph.nodes()), "edges": list(graph.edges(data=True))}
        state["history"].append(tx)
        if max([s for _, s in scores] or [0]) > 0.7:
            state["suspicious"][tx["hash"]] = "High risk detected"

    def run(self):
        schedule.every(10).minutes.do(self.monitor)
        threading.Thread(target=self.process_queue, daemon=True).start()
        threading.Thread(target=lambda: schedule.run_pending() or time.sleep(60), daemon=True).start()

@app.route("/")
def dashboard():
    return render_template("index.html")

if __name__ == "__main__":
    tool = CryptoAnalysisTool()
    tool.run()
    socketio.run(app, port=5001, debug=True)