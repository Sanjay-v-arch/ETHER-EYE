import asyncio
import logging
import os
import aiohttp
from typing import Dict, List
from contextlib import asynccontextmanager
from fastapi import FastAPI
from neo4j import AsyncGraphDatabase
from dotenv import load_dotenv
from backend.blockchain import BlockchainConnector
import networkx as nx

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

NEO4J_URL = os.getenv("NEO4J_URL", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "mypassword")

neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASS))
connector = BlockchainConnector()
watched_addresses = set()

async def init_neo4j_schema():
    async with neo4j_driver.session() as session:
        await session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (w:Wallet) REQUIRE w.address IS UNIQUE")
        await session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (t:Transaction) REQUIRE t.tx_hash IS UNIQUE")
        await session.run("MERGE (w:Wallet {address: '0x28c6c06298d514db089934071355e5743bf21d60'}) SET w.monitored = true")
        logger.info("Neo4j schema initialized")

async def load_config():
    try:
        async with neo4j_driver.session() as session:
            result = await session.run("MATCH (w:Wallet {monitored: true}) RETURN w.address")
            async for record in result:
                watched_addresses.add(record["w.address"])
            logger.info(f"Loaded {len(watched_addresses)} monitored addresses")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")

async def analyze_wallet_auto(address: str, blockchain: str = "ethereum") -> Dict:
    async with aiohttp.ClientSession() as session:
        try:
            history = await connector.get_wallet_history(session, address, blockchain, limit=10)
            spider_map = nx.DiGraph()
            for tx in history:
                spider_map.add_node(tx["from_address"], chain=blockchain)
                spider_map.add_node(tx["to_address"], chain=blockchain)
                spider_map.add_edge(tx["from_address"], tx["to_address"], value=tx["value"])
            risk_score = {"score": len(history), "level": "low" if len(history) < 5 else "high"}
            patterns = ["multiple_txs"] if len(history) > 1 else []
            result = {
                "history": history,
                "spider_map": {"nodes": list(spider_map.nodes(data=True)), "edges": list(spider_map.edges(data=True))},
                "risk_score": risk_score,
                "patterns": patterns
            }
            logger.info(f"Analyzed {address} on {blockchain}: risk={risk_score['score']}")
            return result
        except Exception as e:
            logger.error(f"Analysis failed for {address}: {e}")
            return {"history": [], "spider_map": {"nodes": [], "edges": []}, "risk_score": {"score": 0, "level": "error"}, "patterns": []}

async def monitor_wallets():
    while True:
        async with aiohttp.ClientSession() as session:
            for address in watched_addresses.copy():
                try:
                    history = await connector.get_wallet_history(session, address, "ethereum", limit=10)
                    if history:
                        logger.info(f"New tx for {address}: {history[0]['tx_hash']}")
                except Exception as e:
                    logger.error(f"Monitor error for {address}: {e}")
        await asyncio.sleep(60)

async def fetch_new_addresses():
    chains = ["ethereum", "bitcoin", "solana"]
    while True:
        for chain in chains:
            try:
                async with aiohttp.ClientSession() as session:
                    base_addr = {"ethereum": "0x28c6c06298d514db089934071355e5743bf21d60", "bitcoin": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "solana": "So11111111111111111111111111111111111111112"}[chain]
                    history = await connector.get_wallet_history(session, base_addr, chain, limit=1)
                    if history:
                        new_addresses = {history[0]["from_address"], history[0]["to_address"]} - watched_addresses
                        for address in new_addresses:
                            await analyze_wallet_auto(address, chain)
                            watched_addresses.add(address)
                        logger.info(f"Fetched {len(new_addresses)} addresses from {chain}")
            except Exception as e:
                logger.error(f"Fetch error on {chain}: {e}")
        await asyncio.sleep(300)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_neo4j_schema()
    await load_config()
    monitor_task = asyncio.create_task(monitor_wallets())
    fetch_task = asyncio.create_task(fetch_new_addresses())
    yield
    monitor_task.cancel()
    fetch_task.cancel()
    await neo4j_driver.close()

app = FastAPI(lifespan=lifespan, title="ETHER-EYE", description="Crypto Investigation Tool")

@app.get("/wallet/{address}")
async def analyze_wallet(address: str, blockchain: str = "ethereum"):
    return await analyze_wallet_auto(address, blockchain)