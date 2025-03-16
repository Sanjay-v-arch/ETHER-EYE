# backend/app.py
import asyncio
import logging
import os
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from neo4j import AsyncGraphDatabase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import schedule
from datetime import datetime
from .tracing import TransactionTracer
from .blockchain import BlockchainConnector
from .risk import RiskProfiler
from .patterns import PatternDetector
from .ip_tracing import IPTracer
from .cases import CaseManager
from .reporting import ReportGenerator
from .models import Base, Wallet, Transaction

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

PGSQL_URL = os.getenv("POSTGRES_URL", "postgresql://user:password@localhost:5432/crypto_db")
NEO4J_URL = os.getenv("NEO4J_URL", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "password")

engine = create_engine(PGSQL_URL, pool_size=10, max_overflow=20)
SessionFactory = sessionmaker(bind=engine)
neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASS))

app = FastAPI(title="ETHER-EYE", description="Crypto Investigation Tool for LEA")

connector = BlockchainConnector()
tracer = TransactionTracer(connector, neo4j_driver)
risk_profiler = RiskProfiler(connector, SessionFactory)
pattern_detector = PatternDetector(connector)
ip_tracer = IPTracer(neo4j_driver)
case_manager = CaseManager(neo4j_driver, connector)
report_generator = ReportGenerator(connector, pattern_detector, ip_tracer, case_manager)

watched_addresses = set()

async def load_config():
    """Load monitored addresses from Neo4j."""
    try:
        async with neo4j_driver.session() as session:
            result = await session.run("MATCH (w:Wallet) WHERE w.monitored = true RETURN w.address")
            async for record in result:
                watched_addresses.add(record["w.address"])
            logger.info(f"Loaded {len(watched_addresses)} addresses from Neo4j")
    except Exception as e:
        logger.error(f"Failed to load config from Neo4j: {e}")

@app.get("/trace/{tx_hash}", response_model=Dict)
async def trace_transaction(tx_hash: str, blockchain: str = "ethereum", max_depth: int = 5):
    """Trace a transaction across multiple hops."""
    graph = await tracer.trace_transaction(tx_hash, blockchain, direction="forward", max_depth=max_depth)
    return {"nodes": list(graph.nodes(data=True)), "edges": list(graph.edges(data=True))}

@app.get("/wallet/{address}", response_model=Dict)
async def analyze_wallet(address: str, blockchain: str = "ethereum"):
    """Analyze a wallet's history and risk profile."""
    async with SessionFactory() as session:
        history = await connector.get_wallet_history(session, address, blockchain)
        risk_score = await risk_profiler.calculate_risk(address, blockchain)
        patterns = await pattern_detector.detect_patterns(history)
        ip_data = await ip_tracer.get_geographical_distribution([tx["tx_hash"] for tx in history], blockchain)
        return {
            "address": address,
            "history": history,
            "risk_score": risk_score,
            "patterns": patterns,
            "ip_data": ip_data
        }

@app.get("/suspicious_flows", response_model=List[Dict])
async def get_suspicious_flows(min_value: float = 10000):
    """Retrieve high-value suspicious transaction flows."""
    flows = await tracer.find_suspicious_flows(min_value)
    return flows

@app.post("/cases/create", response_model=Dict)
async def create_case(name: str, investigator: str, status: str = "open"):
    """Create a new investigation case."""
    case_id = await case_manager.create_case(name, investigator, status)
    if case_id is None:
        return {"error": "Failed to create case"}
    return {"case_id": case_id, "name": name, "investigator": investigator, "status": status}

@app.post("/cases/{case_id}/tx", response_model=Dict)
async def associate_transaction(case_id: int, tx_hash: str, user: str, chain: str = "ethereum"):
    """Associate a transaction with a case."""
    success = await case_manager.associate_transaction(case_id, tx_hash, user, chain)
    return {"success": success, "case_id": case_id, "tx_hash": tx_hash}

@app.get("/cases/{case_id}", response_model=Dict)
async def get_case_details(case_id: int):
    """Get case details."""
    details = await case_manager.get_case_details(case_id)
    return details if details else {"error": "Case not found"}

@app.post("/report/{address}", response_model=Dict)
async def generate_report(address: str, chain: str = "ethereum", case_id: Optional[int] = None):
    """Generate and store a report for a wallet."""
    report_data = await report_generator.aggregate_report_data(address, chain, case_id)
    ipfs_hash = await report_generator.generate_pdf_report(report_data)
    return {"address": address, "ipfs_hash": ipfs_hash} if ipfs_hash else {"error": "Report generation failed"}

@app.websocket("/ws/trace")
async def trace_websocket(websocket: WebSocket):
    """Stream real-time transaction tracing for an address."""
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        address = data.get("address")
        blockchain = data.get("blockchain", "ethereum")
        max_depth = data.get("max_depth", 5)
        async def send_graph(tx: dict):
            graph = await tracer.trace_transaction(tx["tx_hash"], blockchain, max_depth=max_depth)
            await websocket.send_json({
                "tx_hash": tx["tx_hash"],
                "nodes": list(graph.nodes(data=True)),
                "edges": list(graph.edges(data=True))
            })
        await tracer.stream_and_trace(address, blockchain, max_depth=max_depth, callback=send_graph)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {address}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close(code=1011)

async def monitor_wallets():
    """Monitor watched addresses for new transactions."""
    async with SessionFactory() as session:
        for address in watched_addresses:
            blockchain = 'bitcoin' if address.startswith(('1', '3', 'bc1')) else 'ethereum'
            history = await connector.get_wallet_history(session, address, blockchain, limit=10)
            for tx in history:
                existing = session.query(Transaction).filter_by(tx_hash=tx['tx_hash']).first()
                if not existing:
                    graph = await tracer.trace_transaction(tx['tx_hash'], blockchain)
                    logger.info(f"New tx detected for {address}: {tx['tx_hash']}, traced {len(graph.nodes())} nodes")
                    session.add(Transaction(tx_hash=tx['tx_hash'], wallet_address=address, amount=tx['value'], timestamp=datetime.fromtimestamp(tx['timestamp']), chain=blockchain))
                    session.commit()

async def run_automation():
    """Run scheduled monitoring in the background."""
    schedule.every(10).minutes.do(lambda: asyncio.create_task(monitor_wallets()))
    logger.info("Started automated monitoring. Checking every 10 minutes.")
    while True:
        schedule.run_pending()
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    """Initialize app and start automation."""
    try:
        Base.metadata.create_all(engine)
        await load_config()
        asyncio.create_task(run_automation())
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")