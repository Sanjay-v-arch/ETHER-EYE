# backend/patterns.py
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
import aiohttp
from sklearn.ensemble import IsolationForest
import numpy as np
import joblib
import os
import networkx as nx
from dotenv import load_dotenv
from backend.blockchain import BlockchainConnector

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class PatternDetector:
    """Advanced pattern detection and risk scoring for blockchain transactions."""
    def __init__(self, blockchain_connector: Optional[BlockchainConnector] = None):
        self.connector = blockchain_connector or BlockchainConnector()
        self.pattern_thresholds = {
            "layering_tx_count": 20,
            "layering_avg_value": {"ethereum": 10**17, "bsc": 10**17, "polygon": 10**17, "bitcoin": 10**7, "solana": 10**8},  # Chain-specific
            "smurfing_time_window": timedelta(hours=1),
            "smurfing_tx_count": 10,
            "mixer_tx_count": 50,
            "high_value": {"ethereum": 10**20, "bsc": 10**20, "polygon": 10**20, "bitcoin": 10**8, "solana": 10**9},  # Chain-specific
            "timing_window": timedelta(minutes=5),
            "timing_tx_count": 10,
            "peeling_chain_steps": 5,
            "peeling_chain_ratio": 0.9
        }
        self.anomaly_model = IsolationForest(contamination=0.05, random_state=42)
        self.risk_weights = {
            "patterns": 20,
            "tx_count": 0.5,
            "ai_anomaly": 30
        }
        self.model_path = "anomaly_model.pkl"
        self.divisors = {"ethereum": 10**18, "bsc": 10**18, "polygon": 10**18, "bitcoin": 10**8, "solana": 10**9}  # Chain-specific divisors

    def validate_transactions(self, transactions: List[Dict], chain: str) -> bool:
        """Validate transaction data structure with chain-specific checks."""
        if not isinstance(transactions, list):
            logger.error("Transactions must be a list")
            return False
        for tx in transactions:
            required_keys = ["amount", "timestamp", "chain"]
            if not all(key in tx for key in required_keys) or not isinstance(tx["amount"], (int, float)):
                logger.error(f"Invalid transaction format: {tx}")
                return False
            max_value = 10**25 if chain in ["ethereum", "bsc", "polygon"] else 21 * 10**8 if chain == "bitcoin" else 10**10
            if tx["amount"] > max_value:
                logger.warning(f"Amount {tx['amount']} seems unrealistic for {chain}")
                return False
        return True

    async def detect_patterns(self, spider_map: nx.DiGraph, blockchain: str = "ethereum") -> List[str]:
        """Detect suspicious activity patterns across all supported blockchains."""
        if not spider_map.edges:
            logger.info("No edges in spider_map, no patterns detected")
            return []

        patterns = []
        # Extract transactions from graph edges
        transactions = [
            {
                "amount": data.get("value", 0),
                "timestamp": data.get("timestamp", datetime.utcnow().isoformat() + "Z"),
                "chain": blockchain,
                "tx_hash": data.get("tx_hash", ""),
                "from_address": u,
                "to_address": v
            }
            for u, v, data in spider_map.edges(data=True)
        ]
        tx_count = len(transactions)
        if not tx_count:
            return []

        total_value = sum(tx["amount"] for tx in transactions)
        timestamps = [datetime.fromisoformat(tx["timestamp"].replace("Z", "")) for tx in transactions]
        avg_value = total_value / tx_count if tx_count > 0 else 0

        # Chain-specific normalization
        divisor = self.divisors.get(blockchain, 10**18)  # Default to Ethereum if unknown
        total_value_normalized = total_value / divisor
        avg_value_normalized = avg_value / divisor
        layering_avg_value = self.pattern_thresholds["layering_avg_value"].get(blockchain, 10**17) / divisor
        high_value_threshold = self.pattern_thresholds["high_value"].get(blockchain, 10**20) / divisor

        # Layering
        if tx_count > self.pattern_thresholds["layering_tx_count"] and avg_value_normalized < layering_avg_value:
            patterns.append(f"Possible layering on {blockchain}")

        # Smurfing
        if timestamps and (max(timestamps) - min(timestamps)) < self.pattern_thresholds["smurfing_time_window"] and tx_count > self.pattern_thresholds["smurfing_tx_count"]:
            patterns.append(f"Possible smurfing on {blockchain}")

        # Round-number transactions
        if any(tx["amount"] % divisor == 0 for tx in transactions):
            patterns.append(f"Round-number transactions detected on {blockchain}")

        # Mixing service usage
        if tx_count > self.pattern_thresholds["mixer_tx_count"]:
            patterns.append(f"Possible mixing service usage on {blockchain}")

        # Ransomware-like
        if any(tx["amount"] / divisor > high_value_threshold and tx_count < 5 for tx in transactions):
            patterns.append(f"Possible ransomware payment on {blockchain}")

        # Unusual timing
        if timestamps and (max(timestamps) - min(timestamps)) < self.pattern_thresholds["timing_window"] and tx_count > self.pattern_thresholds["timing_tx_count"]:
            patterns.append(f"Unusual transaction timing on {blockchain}")

        # Peeling chain detection (chain-agnostic)
        async with aiohttp.ClientSession() as session:
            if await self._check_peeling_chain(session, transactions, blockchain):
                patterns.append(f"Possible peeling chain on {blockchain}")

        # AI-based anomaly detection
        features = np.array([[tx["amount"] / divisor, (datetime.fromisoformat(tx["timestamp"].replace("Z", "")) - datetime(1970, 1, 1)).total_seconds()] for tx in transactions])
        if len(features) > 1:
            anomalies = self.anomaly_model.predict(features)
            if -1 in anomalies:
                patterns.append(f"AI-detected anomaly on {blockchain}")

        logger.info(f"Detected {len(patterns)} patterns in spider_map with {tx_count} transactions on {blockchain}")
        return patterns

    async def _check_peeling_chain(self, session: aiohttp.ClientSession, transactions: List[Dict], chain: str) -> bool:
        """Detect peeling chain pattern across any blockchain."""
        if len(transactions) < self.pattern_thresholds["peeling_chain_steps"]:
            return False
        sorted_txs = sorted(transactions, key=lambda x: datetime.fromisoformat(x["timestamp"].replace("Z", "")), reverse=True)
        divisor = self.divisors.get(chain, 10**18)
        layering_avg_value = self.pattern_thresholds["layering_avg_value"].get(chain, 10**17) / divisor
        for i, tx in enumerate(sorted_txs[:-1]):
            if i + 1 >= len(sorted_txs):
                break
            next_tx = sorted_txs[i + 1]
            if tx["amount"] / divisor > layering_avg_value:
                next_history = await self.connector.get_wallet_history(session, tx["to_address"], chain, limit=2)
                for nh in next_history:
                    if nh["from_address"] == tx["to_address"] and nh["amount"] / divisor < tx["amount"] / divisor * self.pattern_thresholds["peeling_chain_ratio"]:
                        return True
        return False

    async def calculate_risk_score(self, transactions: List[Dict]) -> Dict:
        """Calculate risk score with async pattern detection."""
        if not transactions or not self.validate_transactions(transactions, transactions[0]["chain"]):
            return {"score": 0, "level": "low", "justification": ["Invalid transaction data"]}
        chain = transactions[0]["chain"]
        patterns = await self.detect_patterns(nx.DiGraph(), chain)  # Placeholder graph for compatibility
        tx_count = len(transactions)
        base_score = min(tx_count * self.risk_weights["tx_count"], 50)
        pattern_weight = len(patterns) * self.risk_weights["patterns"]
        ai_weight = self.risk_weights["ai_anomaly"] if "AI-detected anomaly" in patterns else 0
        score = min(base_score + pattern_weight + ai_weight, 100)
        level = "high" if score > 75 else "medium" if score > 50 else "low"
        justification = patterns if patterns else ["No suspicious patterns detected"]
        logger.info(f"Risk score calculated: {score} ({level}) for {tx_count} transactions on {chain}")
        return {"score": score, "level": level, "justification": justification}

    def adjust_risk_score(self, current_score: Dict, manual_adjustment: int, reason: str) -> Dict:
        if not isinstance(manual_adjustment, int) or not isinstance(reason, str) or not reason.strip():
            logger.error("Invalid adjustment parameters")
            return current_score
        new_score = max(0, min(current_score["score"] + manual_adjustment, 100))
        new_level = "high" if new_score > 75 else "medium" if new_score > 50 else "low"
        new_justification = current_score["justification"] + [f"Manual adjustment: {manual_adjustment} ({reason})"]
        logger.info(f"Risk score adjusted from {current_score['score']} to {new_score} for reason: {reason}")
        return {"score": new_score, "level": new_level, "justification": new_justification}

    def update_thresholds(self, new_thresholds: Dict):
        self.pattern_thresholds.update(new_thresholds)
        logger.info(f"Updated pattern thresholds: {self.pattern_thresholds}")

    def train_anomaly_model(self, historical_transactions: List[Dict]):
        chain = historical_transactions[0]["chain"] if historical_transactions else "ethereum"
        if not self.validate_transactions(historical_transactions, chain) or len(historical_transactions) < 2:
            logger.error("Insufficient or invalid historical data for training")
            return
        divisor = self.divisors.get(chain, 10**18)
        features = np.array([[tx["amount"] / divisor, (datetime.fromisoformat(tx["timestamp"].replace("Z", "")) - datetime(1970, 1, 1)).total_seconds()] for tx in historical_transactions])
        self.anomaly_model.fit(features)
        joblib.dump(self.anomaly_model, self.model_path)
        logger.info(f"Anomaly model trained and saved to {self.model_path}")

    def load_anomaly_model(self):
        if os.path.exists(self.model_path):
            self.anomaly_model = joblib.load(self.model_path)
            logger.info(f"Anomaly model loaded from {self.model_path}")
        else:
            logger.warning(f"No model found at {self.model_path}; using default")

if __name__ == "__main__":
    async def main():
        detector = PatternDetector()
        graph = nx.DiGraph()
        graph.add_edge("0x1", "0x2", value=10**18, timestamp="2025-03-07T12:00:00Z", tx_hash="0x1")
        patterns = await detector.detect_patterns(graph, "ethereum")
        print(f"Detected patterns: {patterns}")
        sample_txs = [
            {"amount": 10**18, "timestamp": "2025-03-07T12:00:00Z", "tx_hash": "0x1", "chain": "ethereum"},
            {"amount": 10**16, "timestamp": "2025-03-07T12:01:00Z", "tx_hash": "0x2", "chain": "ethereum"}
        ]
        risk = await detector.calculate_risk_score(sample_txs)
        print(f"Risk score: {risk}")

    asyncio.run(main())