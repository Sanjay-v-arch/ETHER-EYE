# backend/tracing.py
import asyncio
import aiohttp
import websockets
import networkx as nx
from neo4j import GraphDatabase
import smtplib
from email.mime.text import MIMEText
import discord
from discord import Webhook, AsyncWebhookAdapter
import telegram
from typing import Dict, Set, List, Optional
import logging
import os
from dotenv import load_dotenv
from aiohttp_socks import ProxyConnector
from .blockchain import BlockchainConnector

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TransactionTracer:
    """Advanced multi-hop transaction tracing with real-time streaming and cross-chain detection."""
    def __init__(self, blockchain_connector: BlockchainConnector, neo4j_driver):
        self.connector = blockchain_connector
        self.driver = neo4j_driver
        self.graph = nx.DiGraph()
        self.alert_email = os.getenv("ALERT_EMAIL", "ethereye@example.com")
        self.discord_webhook = os.getenv("DISCORD_WEBHOOK_URL")
        self.telegram_bot = telegram.Bot(os.getenv("TELEGRAM_BOT_TOKEN"))
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.api_keys = {
            "etherscan": os.getenv("ETHERSCAN_API_KEY"),
            "alchemy": os.getenv("ALCHEMY_API_KEY"),
            "moralis": os.getenv("MORALIS_API_KEY"),
            "bitquery": os.getenv("BITQUERY_API_KEY")
        }
        self.websocket_urls = {
            "ethereum": f"wss://eth-mainnet.g.alchemy.com/v2/{self.api_keys['alchemy']}",
            "bitcoin": "wss://api.amberdata.io/v2/websocket",  # Mocked if no key
            "solana": "wss://api.mainnet-beta.solana.com"
        }
        self.known_bridges = ["0xbridge...", "0xwormhole..."]  # Simulated bridge addresses

    async def trace_transaction(self, tx_hash: str, blockchain: str, direction: str = "forward", max_depth: int = 5, min_value: float = 0.001) -> nx.DiGraph:
        """Trace multi-hop transactions with directionality and cross-chain detection."""
        self.graph.clear()
        visited = set()
        total_value = 0
        async with aiohttp.ClientSession(connector=ProxyConnector.from_url("socks5://127.0.0.1:9050")) as session:
            total_value = await self._trace_recursive(session, tx_hash, blockchain, direction, max_depth, min_value, visited, total_value)
            cross_chain_txs = await self._detect_cross_chain(session, list(self.graph.nodes())[0])
            for tx in cross_chain_txs:
                self.graph.add_edge(tx["from"], tx["to"], tx_hash=tx.get("id", "cross_chain"), value=float(tx["value"]), token=tx.get("token", {}).get("symbol", "unknown"))
                total_value += float(tx["value"])
            logger.info(f"Traced {len(self.graph.nodes())} nodes, {len(self.graph.edges())} edges, total value: {total_value}")
        return self.graph

    async def _trace_recursive(self, session, tx_hash: str, blockchain: str, direction: str, depth: int, min_value: float, visited: Set[str], total_value: float) -> float:
        if depth <= 0 or tx_hash in visited:
            return total_value
        visited.add(tx_hash)
        tx_data = await self.connector.get_transaction_data(session, tx_hash, blockchain)
        if not tx_data or tx_data["value"] < min_value:
            return total_value

        from_addr, to_addr = tx_data["from_address"], tx_data["to_address"]
        self.graph.add_node(from_addr, type="wallet", blockchain=blockchain)
        self.graph.add_node(to_addr, type="wallet", blockchain=blockchain)
        self.graph.add_edge(from_addr, to_addr, tx_hash=tx_hash, value=tx_data["value"], timestamp=tx_data["timestamp"])
        total_value += tx_data["value"]

        with self.driver.session() as neo_session:
            neo_session.write_transaction(self._store_in_neo4j, tx_data)

        # Direction-based tracing
        if direction == "forward":
            to_txs = await self.connector.get_wallet_history(session, to_addr, blockchain, limit=5)
            for tx in to_txs:
                if tx["tx_hash"] not in visited and tx["value"] >= min_value and tx["from_address"] == to_addr:
                    total_value = await self._trace_recursive(session, tx["tx_hash"], blockchain, direction, depth - 1, min_value, visited, total_value)
        elif direction == "backward":
            from_txs = await self.connector.get_wallet_history(session, from_addr, blockchain, limit=5)
            for tx in from_txs:
                if tx["tx_hash"] not in visited and tx["value"] >= min_value and tx["to_address"] == from_addr:
                    total_value = await self._trace_recursive(session, tx["tx_hash"], blockchain, direction, depth - 1, min_value, visited, total_value)
        return total_value

    async def stream_and_trace(self, address: str, blockchain: str, direction: str = "forward", max_depth: int = 5):
        """Stream real-time transactions and trace them."""
        async def callback(tx: dict):
            await self.trace_transaction(tx["tx_hash"], blockchain, direction, max_depth)
            logger.info(f"Real-time traced tx {tx['tx_hash']} for {address}")
            await asyncio.sleep(1)
        await self.connector.stream_transactions(address, blockchain, callback)

    async def _detect_cross_chain(self, session, address: str) -> List[Dict]:
        """Detect cross-chain transfers with bridge checking."""
        transfers = []
        async with session.post("https://graphql.bitquery.io/", json={"query": f"{{ blockchain {{ transactions(address: \"{address}\") {{ hash from to amount currency {{ symbol }} }} }} }}"}, headers={"X-API-KEY": self.api_keys["bitquery"]}) as resp:
            bitquery_data = await resp.json()
            for tx in bitquery_data.get("data", {}).get("blockchain", {}).get("transactions", []):
                cross_chain = any(bridge in tx["to"].lower() for bridge in self.known_bridges) or "bridge" in tx["to"].lower()
                transfers.append({
                    "from": tx["from"],
                    "to": tx["to"],
                    "value": tx["amount"],
                    "id": tx["hash"],
                    "token": {"symbol": tx["currency"]["symbol"]},
                    "cross_chain": cross_chain
                })
        if transfers and any(t["cross_chain"] for t in transfers):
            await self._send_alert(f"Cross-chain activity detected for {address}: {len(transfers)} transfers", "telegram")
        return transfers

    @staticmethod
    def _store_in_neo4j(tx, tx_data: Dict):
        """Store transaction data in Neo4j with optimized indexing."""
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
        """Optimized Neo4j query for high-value transaction flows."""
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
                await self._send_alert(f"Found {len(suspicious)} suspicious flows above {min_value}", "email")
            return suspicious

    async def _send_alert(self, message: str, channel: str = "email"):
        """Send real-time alerts via email, Discord, or Telegram."""
        if channel == "email":
            msg = MIMEText(message)
            msg["Subject"] = "⚠️ ETHER-EYE Investigation Alert"
            msg["From"] = os.getenv("SMTP_USER")
            msg["To"] = self.alert_email
            try:
                with smtplib.SMTP("smtp.gmail.com", 587) as server:
                    server.starttls()
                    server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
                    server.sendmail(msg["From"], [msg["To"]], msg.as_string())
                    logger.info(f"Email alert sent: {message}")
            except Exception as e:
                logger.error(f"Email alert failed: {e}")
        elif channel == "discord":
            async with aiohttp.ClientSession() as session:
                webhook = Webhook.from_url(self.discord_webhook, adapter=AsyncWebhookAdapter(session))
                await webhook.send(content=message)
                logger.info(f"Discord alert sent: {message}")
        elif channel == "telegram":
            await self.telegram_bot.send_message(chat_id=self.telegram_chat_id, text=message)
            logger.info(f"Telegram alert sent: {message}")

if __name__ == "__main__":
    from .blockchain import BlockchainConnector
    NEO4J_URL = os.getenv("NEO4J_URL", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "password")
    neo4j_driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASS))
    connector = BlockchainConnector()
    tracer = TransactionTracer(connector, neo4j_driver)
    loop = asyncio.get_event_loop()
    graph = loop.run_until_complete(tracer.trace_transaction("0x4e3a3754410177e6937ef1d0084000883f919978", "ethereum", "forward"))
    print(f"Traced {len(graph.nodes())} nodes, {len(graph.edges())} edges")