# backend/transactions.py
import asyncio
import aiohttp
import websockets
import networkx as nx
from neo4j import GraphDatabase
from sklearn.ensemble import IsolationForest
from sklearn.cluster import DBSCAN
from ipfshttpclient import connect
import smtplib
from email.mime.text import MIMEText
import discord
from discord import Webhook, AsyncWebhookAdapter
from telegram import Bot
from typing import Dict, Set, List
import logging
import os
from datetime import datetime
from dotenv import load_dotenv
from aiohttp_socks import ProxyConnector
from seal import EncryptionParameters, SEALContext, KeyGenerator, Encryptor, Evaluator, Decryptor, Plaintext, Ciphertext
from ..config.secrets import API_KEYS, SMTP_USER, SMTP_PASS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL
from .blockchain import BlockchainConnector

logger = logging.getLogger(__name__)

class TransactionTracer:
    """Ultimate multi-hop transaction tracing for LEA-grade blockchain investigations."""
    def __init__(self, blockchain_connector: BlockchainConnector, neo4j_driver):
        self.connector = blockchain_connector
        self.driver = neo4j_driver
        self.graph = nx.DiGraph()
        self.anomaly_model = IsolationForest(contamination=0.05)
        self.cluster_model = DBSCAN(eps=0.5, min_samples=5)
        self.ipfs = connect()
        self.alert_email = os.getenv("ALERT_EMAIL", "lea_investigator@example.com")
        # Homomorphic encryption setup
        self.params = EncryptionParameters(128)
        self.params.set_poly_modulus_degree(4096)
        self.params.set_coeff_modulus([40, 40, 40, 40])
        self.context = SEALContext(self.params)
        self.keygen = KeyGenerator(self.context)
        self.public_key = self.keygen.public_key()
        self.secret_key = self.keygen.secret_key()
        self.encryptor = Encryptor(self.context, self.public_key)
        self.evaluator = Evaluator(self.context)
        self.decryptor = Decryptor(self.context, self.secret_key)

    async def trace_transaction(self, tx_hash: str, blockchain: str, max_depth: int = 5, min_value: float = 0.001) -> nx.DiGraph:
        """Trace multi-hop transactions across blockchains with real-time and encrypted data."""
        self.graph.clear()
        visited = set()
        async with aiohttp.ClientSession(connector=ProxyConnector.from_url("socks5://127.0.0.1:9050")) as session:
            await self._trace_recursive(session, tx_hash, blockchain, max_depth, min_value, visited)
            cross_chain_txs = await self._detect_cross_chain(session, list(self.graph.nodes())[0])
            for tx in cross_chain_txs:
                self.graph.add_edge(tx["from"], tx["to"], tx_hash=tx.get("id", "cross_chain"), value=float(tx["value"]), token=tx.get("token", {}).get("symbol", "unknown"))
        return self.graph

    async def _trace_recursive(self, session, tx_hash: str, blockchain: str, depth: int, min_value: float, visited: Set[str]):
        if depth <= 0 or tx_hash in visited:
            return
        visited.add(tx_hash)
        tx_data = await self.connector.get_transaction_data(session, tx_hash, blockchain)
        if not tx_data or tx_data["value"] < min_value:
            return

        plain_value = Plaintext(str(int(tx_data["value"] * 10**18)))
        encrypted_value = Ciphertext()
        self.encryptor.encrypt(plain_value, encrypted_value)

        from_addr, to_addr = tx_data["from_address"], tx_data["to_address"]
        self.graph.add_node(from_addr, type="wallet", blockchain=blockchain)
        self.graph.add_node(to_addr, type="wallet", blockchain=blockchain)
        self.graph.add_edge(from_addr, to_addr, tx_hash=tx_hash, value=tx_data["value"], encrypted_value=encrypted_value, timestamp=tx_data["timestamp"])

        with self.driver.session() as neo_session:
            neo_session.write_transaction(self._store_in_neo4j, tx_data)
        ipfs_hash = self.ipfs.add_json(tx_data)
        logger.info(f"Traced tx {tx_hash} stored on IPFS: {ipfs_hash}")

        decrypted_value = Plaintext()
        self.decryptor.decrypt(encrypted_value, decrypted_value)
        value = float(decrypted_value.to_string()) / 10**18
        features = [[value]]
        self.anomaly_model.fit(features)
        if self.anomaly_model.predict(features)[0] == -1:
            await self._send_alert(f"Anomaly detected in tx {tx_hash}: High value {value}", "email")

        history = await self.connector.get_wallet_history(session, from_addr, blockchain, limit=10)
        if history:
            cluster_features = [[tx["value"]] for tx in history]
            self.cluster_model.fit(cluster_features)
            clusters = self.cluster_model.labels_
            if -1 in clusters:
                await self._send_alert(f"Potential clustering anomaly for {from_addr}", "telegram")

        from_txs = await self.connector.get_wallet_history(session, from_addr, blockchain, limit=5)
        to_txs = await self.connector.get_wallet_history(session, to_addr, blockchain, limit=5)
        for tx in from_txs + to_txs:
            if tx["tx_hash"] not in visited and tx["value"] >= min_value:
                await self._trace_recursive(session, tx["tx_hash"], blockchain, depth - 1, min_value, visited)

    async def stream_and_trace(self, address: str, blockchain: str, max_depth: int = 5):
        """Stream real-time transactions and trace them."""
        async def callback(tx: dict):
            await self.trace_transaction(tx["tx_hash"], blockchain, max_depth)
            logger.info(f"Real-time traced tx {tx['tx_hash']} for {address}")
            await asyncio.sleep(1)
        
        await self.connector.stream_transactions(address, blockchain, callback)

    async def _detect_cross_chain(self, session, address: str) -> List[Dict]:
        transfers = []
        query = "query { transfers(where: {from: \"$address\" OR to: \"$address\"}) { id from to value token { symbol } } }"
        async with session.post("https://api.thegraph.com/subgraphs/name/bridge-example", json={"query": query.replace("$address", address)}) as resp:
            thegraph_data = await resp.json()
            transfers.extend(thegraph_data.get("data", {}).get("transfers", []))

        url = f"https://api.graphsense.info/addresses/{address}"
        headers = {"Authorization": f"Bearer {API_KEYS['graphsense']}"}
        async with session.get(url, headers=headers) as resp:
            graphsense_data = await resp.json()
            linked = graphsense_data.get("linked_addresses", [])
            transfers.extend([{"from": address, "to": addr, "value": 0, "id": f"graphsense_{addr}", "token": {"symbol": "unknown"}} for addr in linked])

        bitquery_query = {"query": f"{{ blockchain {{ transactions(address: \"{address}\") {{ hash from to amount currency {{ symbol }} }} }} }}"}
        async with session.post("https://graphql.bitquery.io/", json=bitquery_query, headers={"X-API-KEY": API_KEYS["bitquery"]}) as resp:
            bitquery_data = await resp.json()
            transfers.extend([{"from": tx["from"], "to": tx["to"], "value": tx["amount"], "id": tx["hash"], "token": {"symbol": tx["currency"]["symbol"]}}
                              for tx in bitquery_data.get("data", {}).get("blockchain", {}).get("transactions", [])])

        transpose_url = f"https://api.transpose.io/v0/transactions?address={address}"
        async with session.get(transpose_url, headers={"X-API-KEY": API_KEYS["transpose"]}) as resp:
            transpose_data = await resp.json()
            transfers.extend([{"from": tx["from"], "to": tx["to"], "value": float(tx["value"]), "id": tx["hash"], "token": {"symbol": tx.get("token_symbol", "unknown")}}
                              for tx in transpose_data.get("results", [])])

        if transfers:
            await self._send_alert(f"Cross-chain activity detected for {address}: {len(transfers)} transfers", "discord")
        return transfers

    @staticmethod
    def _store_in_neo4j(tx, tx_data: Dict):
        query = """
        CREATE INDEX ON :Transaction(tx_hash) IF NOT EXISTS;
        CREATE INDEX ON :Address(address) IF NOT EXISTS;
        MERGE (t:Transaction {tx_hash: $tx_hash})
        SET t.timestamp = $timestamp, t.value = $value, t.blockchain = $blockchain
        MERGE (f:Address {address: $from_address})
        MERGE (t:Address {address: $to_address})
        MERGE (f)-[r:SENT {value: $value, timestamp: $timestamp}]->(t)
        """
        tx.run(query, **tx_data)

    async def find_suspicious_flows(self, min_value: float = 10000) -> List[Dict]:
        query = """
        MATCH (from:Address)-[t:SENT]->(to:Address)
        WHERE t.value > $min_value
        RETURN from.address AS sender, to.address AS receiver, t.value AS amount, t.timestamp AS time
        ORDER BY t.value DESC LIMIT 50
        """
        with self.driver.session() as session:
            results = session.run(query, min_value=min_value)
            suspicious = [dict(record) for record in results]
            if suspicious:
                await self._send_alert(f"Found {len(suspicious)} suspicious flows above {min_value}", "telegram")
            return suspicious

    async def _send_alert(self, message: str, channel: str = "email"):
        if channel == "email":
            msg = MIMEText(message)
            msg["Subject"] = "⚠️ Crypto Investigation Alert"
            msg["From"] = "crypto_anal_tool@lea.gov"
            msg["To"] = self.alert_email
            try:
                with smtplib.SMTP("smtp.gmail.com", 587) as server:
                    server.starttls()
                    server.login(SMTP_USER, SMTP_PASS)
                    server.sendmail(msg["From"], [msg["To"]], msg.as_string())
                    logger.info(f"Email alert sent: {message}")
            except Exception as e:
                logger.error(f"Email alert failed: {e}")
        elif channel == "discord":
            async with aiohttp.ClientSession() as session:
                webhook = Webhook.from_url(DISCORD_WEBHOOK_URL, adapter=AsyncWebhookAdapter(session))
                await webhook.send(content=message)
                logger.info(f"Discord alert sent: {message}")
        elif channel == "telegram":
            bot = Bot(TELEGRAM_BOT_TOKEN)
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
            logger.info(f"Telegram alert sent: {message}")

if __name__ == "__main__":
    from .blockchain import BlockchainConnector
    from ..backend.database import NEO4J_URL, NEO4J_USER, NEO4J_PASS
    neo4j_driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASS))
    connector = BlockchainConnector()
    tracer = TransactionTracer(connector, neo4j_driver)
    loop = asyncio.get_event_loop()
    graph = loop.run_until_complete(tracer.trace_transaction("0x123...", "ethereum"))
    print(f"Traced {len(graph.nodes())} nodes, {len(graph.edges())} edges")