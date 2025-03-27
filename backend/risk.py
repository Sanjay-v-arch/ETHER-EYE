# backend/risk.py
import aiohttp
import logging
from typing import Dict
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from backend.blockchain import BlockchainConnector
from backend.patterns import PatternDetector
from backend.models import Wallet  # Assuming this exists

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RiskProfiler:
    """Risk profiling for blockchain wallets."""
    def __init__(self, blockchain_connector: BlockchainConnector, session_factory: async_sessionmaker):
        self.connector = blockchain_connector
        self.session_factory = session_factory
        self.pattern_detector = PatternDetector(blockchain_connector)

    async def calculate_risk(self, address: str, chain: str = "ethereum") -> float:  # Changed to return float
        """Calculate risk score for a wallet."""
        async with aiohttp.ClientSession() as session:
            history = await self.connector.get_wallet_history(session, address, chain)
            if not history:
                logger.info(f"No transaction history for {address}")
                async with self.session_factory() as db_session:
                    await db_session.merge(Wallet(address=address, risk_score=0.0, risk_level="low"))
                    await db_session.commit()
                return 0.0

            risk_score = await self.pattern_detector.calculate_risk_score(history)
            async with self.session_factory() as db_session:
                wallet = Wallet(address=address, risk_score=risk_score["score"], risk_level=risk_score["level"])
                await db_session.merge(wallet)
                await db_session.commit()

            logger.info(f"Risk calculated for {address}: {risk_score}")
            return risk_score["score"]  # Return just the score as float

if __name__ == "__main__":
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from backend.blockchain import BlockchainConnector
    from backend.models import Base, Wallet

    engine = create_async_engine("postgresql+asyncpg://user:password@localhost:5432/crypto_db", echo=True)
    SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def init_db():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    connector = BlockchainConnector()
    profiler = RiskProfiler(connector, SessionFactory)
    async def test():
        await init_db()
        risk = await profiler.calculate_risk("0x28c6c06298d514db089934071355e5743bf21d60")
        print(f"Risk score: {risk}")
    import asyncio
    asyncio.run(test())