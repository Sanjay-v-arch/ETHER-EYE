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
            "layering_avg_value": 10**17,  # <0.1 ETH
            "smurfing_time_window": timedelta(hours=1),
            "smurfing_tx_count": 10,
            "mixer_tx_count": 50,
            "high_value": 10**20,  # 100 ETH
            "timing_window": timedelta(minutes=5),
            "timing_tx_count": 10,
            "peeling_chain_steps": 5,  # Number of hops for peeling chain
            "peeling_chain_ratio": 0.9  # 90% of funds forwarded
        }
        self.anomaly_model = IsolationForest(contamination=0.05, random_state=42)
        self.risk_weights = {
            "patterns": 20,
            "tx_count": 0.5,
            "ai_anomaly": 30
        }
        self.model_path = "anomaly_model.pkl"

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
            # Chain-specific amount normalization check
            if chain in ["ethereum", "bsc", "polygon"] and tx["amount"] > 10**25:  # Unrealistic ETH value
                logger.warning(f"Amount {tx['amount']} seems unrealistic for {chain}")
                return False
            elif chain == "bitcoin" and tx["amount"] > 21 * 10**8:  # Bitcoin supply limit
                logger.warning(f"Amount {tx['amount']} exceeds Bitcoin supply")
                return False
        return True

    async def detect_patterns(self, transactions: List[Dict]) -> List[str]:
        """Detect suspicious activity patterns with async data fetching and AI enhancement."""
        chain = transactions[0]["chain"] if transactions else "ethereum"  # Default to Ethereum
        if not self.validate_transactions(transactions, chain):
            return []

        patterns = []
        tx_count = len(transactions)
        total_value = sum(tx["amount"] for tx in transactions)
        timestamps = [datetime.fromisoformat(tx["timestamp"].replace("Z", "")) for tx in transactions]
        avg_value = total_value / tx_count if tx_count > 0 else 0

        # Normalize amounts based on chain
        divisor = 10**18 if chain in ["ethereum", "bsc", "polygon"] else 10**8 if chain == "bitcoin" else 10**9  # Solana, TON
        total_value_normalized = total_value / divisor
        avg_value_normalized = avg_value / divisor

        # Layering: Many small transactions
        if tx_count > self.pattern_thresholds["layering_tx_count"] and avg_value_normalized < self.pattern_thresholds["layering_avg_value"] / 10**18:
            patterns.append("Possible layering")

        # Smurfing: High frequency in short time
        if timestamps and (max(timestamps) - min(timestamps)) < self.pattern_thresholds["smurfing_time_window"] and tx_count > self.pattern_thresholds["smurfing_tx_count"]:
            patterns.append("Possible smurfing")

        # Round-number transactions
        if any(tx["amount"] % divisor == 0 for tx in transactions):
            patterns.append("Round-number transactions detected")

        # Mixing service usage: High transaction volume
        if tx_count > self.pattern_thresholds["mixer_tx_count"]:
            patterns.append("Possible mixing service usage")

        # Ransomware-like: High-value single transaction with low tx count
        if any(tx["amount"] / divisor > self.pattern_thresholds["high_value"] / 10**18 and tx_count < 5 for tx in transactions):
            patterns.append("Possible ransomware payment")

        # Unusual timing: High frequency in very short window
        if timestamps and (max(timestamps) - min(timestamps)) < self.pattern_thresholds["timing_window"] and tx_count > self.pattern_thresholds["timing_tx_count"]:
            patterns.append("Unusual transaction timing")

        # Peeling chain detection
        async with aiohttp.ClientSession() as session:
            if await self._check_peeling_chain(session, transactions, chain):
                patterns.append("Possible peeling chain")

        # AI-based anomaly detection
        features = np.array([[tx["amount"] / divisor, (datetime.fromisoformat(tx["timestamp"].replace("Z", "")) - datetime(1970, 1, 1)).total_seconds()] for tx in transactions])
        if len(features) > 1:  # Need at least 2 samples
            anomalies = self.anomaly_model.predict(features)
            if -1 in anomalies:  # -1 indicates anomaly
                patterns.append("AI-detected anomaly")

        return patterns

    async def _check_peeling_chain(self, session: aiohttp.ClientSession, transactions: List[Dict], chain: str) -> bool:
        """Detect peeling chain pattern: one large input, multiple small outputs with forwarding."""
        if len(transactions) < self.pattern_thresholds["peeling_chain_steps"]:
            return False

        sorted_txs = sorted(transactions, key=lambda x: datetime.fromisoformat(x["timestamp"].replace("Z", "")), reverse=True)
        divisor = 10**18 if chain in ["ethereum", "bsc", "polygon"] else 10**8 if chain == "bitcoin" else 10**9
        for i, tx in enumerate(sorted_txs[:-1]):  # Check each tx except last
            if i + 1 >= len(sorted_txs):
                break
            next_tx = sorted_txs[i + 1]
            if tx["amount"] / divisor > self.pattern_thresholds["layering_avg_value"] / 10**18:  # Large input
                next_history = await self.connector.get_wallet_history(session, tx["to_address"], chain, limit=2)
                for nh in next_history:
                    if nh["from_address"] == tx["to_address"] and nh["amount"] / divisor < tx["amount"] / divisor * self.pattern_thresholds["peeling_chain_ratio"]:
                        return True  # Found a peel: large input, smaller output
        return False

    async def calculate_risk_score(self, transactions: List[Dict]) -> Dict:
        """Calculate risk score with async pattern detection."""
        if not transactions or not self.validate_transactions(transactions, transactions[0]["chain"]):
            return {"score": 0, "level": "low", "justification": ["Invalid transaction data"]}

        patterns = await self.detect_patterns(transactions)
        tx_count = len(transactions)

        base_score = min(tx_count * self.risk_weights["tx_count"], 50)
        pattern_weight = len(patterns) * self.risk_weights["patterns"]
        ai_weight = self.risk_weights["ai_anomaly"] if "AI-detected anomaly" in patterns else 0

        score = min(base_score + pattern_weight + ai_weight, 100)
        level = "high" if score > 75 else "medium" if score > 50 else "low"
        justification = patterns if patterns else ["No suspicious patterns detected"]

        logger.info(f"Risk score calculated: {score} ({level}) for {tx_count} transactions")
        return {
            "score": score,
            "level": level,
            "justification": justification
        }

    def adjust_risk_score(self, current_score: Dict, manual_adjustment: int, reason: str) -> Dict:
        """Manually adjust risk score with audit trail."""
        if not isinstance(manual_adjustment, int) or not isinstance(reason, str) or not reason.strip():
            logger.error("Invalid adjustment parameters")
            return current_score

        new_score = max(0, min(current_score["score"] + manual_adjustment, 100))
        new_level = "high" if new_score > 75 else "medium" if new_score > 50 else "low"
        new_justification = current_score["justification"] + [f"Manual adjustment: {manual_adjustment} ({reason})"]

        logger.info(f"Risk score adjusted from {current_score['score']} to {new_score} for reason: {reason}")
        return {
            "score": new_score,
            "level": new_level,
            "justification": new_justification
        }

    def update_thresholds(self, new_thresholds: Dict):
        """Dynamically update detection thresholds."""
        self.pattern_thresholds.update(new_thresholds)
        logger.info(f"Updated pattern thresholds: {self.pattern_thresholds}")

    def train_anomaly_model(self, historical_transactions: List[Dict]):
        """Train the AI model with historical data and save to disk."""
        chain = historical_transactions[0]["chain"] if historical_transactions else "ethereum"
        if not self.validate_transactions(historical_transactions, chain) or len(historical_transactions) < 2:
            logger.error("Insufficient or invalid historical data for training")
            return

        divisor = 10**18 if chain in ["ethereum", "bsc", "polygon"] else 10**8 if chain == "bitcoin" else 10**9
        features = np.array([[tx["amount"] / divisor, (datetime.fromisoformat(tx["timestamp"].replace("Z", "")) - datetime(1970, 1, 1)).total_seconds()] for tx in historical_transactions])
        self.anomaly_model.fit(features)
        joblib.dump(self.anomaly_model, self.model_path)
        logger.info(f"Anomaly model trained and saved to {self.model_path}")

    def load_anomaly_model(self):
        """Load a previously trained anomaly model from disk."""
        if os.path.exists(self.model_path):
            self.anomaly_model = joblib.load(self.model_path)
            logger.info(f"Anomaly model loaded from {self.model_path}")
        else:
            logger.warning(f"No model found at {self.model_path}; using default")

if __name__ == "__main__":
    async def main():
        detector = PatternDetector()
        # Example transactions (adjusted for compatibility with blockchain.py)
        sample_txs = [
            {"amount": 10**18, "timestamp": "2025-03-07T12:00:00Z", "tx_hash": "0x1", "chain": "ethereum"},
            {"amount": 10**16, "timestamp": "2025-03-07T12:01:00Z", "tx_hash": "0x2", "chain": "ethereum"},
            {"amount": 10**20, "timestamp": "2025-03-07T12:02:00Z", "tx_hash": "0x3", "chain": "ethereum"}
        ]
        patterns = await detector.detect_patterns(sample_txs)
        print(f"Detected patterns: {patterns}")
        risk = await detector.calculate_risk_score(sample_txs)
        print(f"Risk score: {risk}")
        adjusted = detector.adjust_risk_score(risk, 10, "Investigator suspicion")
        print(f"Adjusted risk: {adjusted}")
        detector.train_anomaly_model(sample_txs)
        detector.load_anomaly_model()

    asyncio.run(main())