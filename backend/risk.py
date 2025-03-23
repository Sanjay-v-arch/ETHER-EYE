# backend/risk.py
import aiohttp
import asyncio
import logging
from typing import Dict, List
from sqlalchemy.orm import Session
from backend.blockchain import BlockchainConnector
from backend.patterns import PatternDetector

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RiskProfiler:
    """Risk profiling for blockchain wallets."""
    def __init__(self, blockchain_connector: BlockchainConnector, session_factory):
        self.connector = blockchain_connector
        self.session_factory = session_factory
        self.pattern_detector = PatternDetector(blockchain_connector)

    async def calculate_risk(self, address: str, chain: str = "ethereum") -> Dict:
        """Calculate risk score for a wallet."""
        async with aiohttp.ClientSession() as session:
            history = await self.connector.get_wallet_history(session, address, chain)
            if not history:
                return {"score": 0, "level": "low", "justification": ["No transaction history"]}

            risk_score = await self.pattern_detector.calculate_risk_score(history)
            with self.session_factory() as db_session:
                db_session.merge(Wallet(address=address, risk_score=risk_score["score"], risk_level=risk_score["level"]))
                db_session.commit()

            logger.info(f"Risk calculated for {address}: {risk_score}")
            return risk_score

if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from .blockchain import BlockchainConnector
    from .models import Base, Wallet
    engine = create_engine("postgresql://user:password@localhost:5432/crypto_db")
    SessionFactory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    connector = BlockchainConnector()
    profiler = RiskProfiler(connector, SessionFactory)
    async def test():
        risk = await profiler.calculate_risk("0x28c6c06298d514db089934071355e5743bf21d60")
        print(f"Risk: {risk}")
    asyncio.run(test())