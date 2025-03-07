# backend/patterns.py
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from sklearn.ensemble import IsolationForest
import numpy as np
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class PatternDetector:
    """Advanced pattern detection and risk scoring for blockchain transactions."""
    def __init__(self):
        self.pattern_thresholds = {
            "layering_tx_count": 20,          # From your friend's code
            "layering_avg_value": 10**17,     # <0.1 ETH
            "smurfing_time_window": timedelta(hours=1),
            "smurfing_tx_count": 10,
            "mixer_tx_count": 50,
            "high_value": 10**20,             # 100 ETH
            "timing_window": timedelta(minutes=5),
            "timing_tx_count": 10
        }
        self.anomaly_model = IsolationForest(contamination=0.05, random_state=42)
        self.risk_weights = {
            "patterns": 20,                   # Per pattern detected
            "tx_count": 0.5,                  # Base score per transaction
            "ai_anomaly": 30                  # AI-detected anomaly weight
        }

    def validate_transactions(self, transactions: List[Dict]) -> bool:
        """Validate transaction data structure."""
        if not isinstance(transactions, list):
            logger.error("Transactions must be a list")
            return False
        for tx in transactions:
            required_keys = ["amount", "timestamp"]
            if not all(key in tx for key in required_keys) or not isinstance(tx["amount"], (int, float)):
                logger.error(f"Invalid transaction format: {tx}")
                return False
        return True

    def detect_patterns(self, transactions: List[Dict]) -> List[str]:
        """Detect suspicious activity patterns with AI enhancement."""
        if not self.validate_transactions(transactions):
            return []

        patterns = []
        tx_count = len(transactions)
        total_value = sum(tx["amount"] for tx in transactions)
        timestamps = [datetime.fromisoformat(tx["timestamp"].replace("Z", "")) for tx in transactions]
        avg_value = total_value / tx_count if tx_count > 0 else 0

        # Layering: Many small transactions
        if tx_count > self.pattern_thresholds["layering_tx_count"] and avg_value < self.pattern_thresholds["layering_avg_value"]:
            patterns.append("Possible layering")

        # Smurfing: High frequency in short time
        if timestamps and (max(timestamps) - min(timestamps)) < self.pattern_thresholds["smurfing_time_window"] and tx_count > self.pattern_thresholds["smurfing_tx_count"]:
            patterns.append("Possible smurfing")

        # Round-number transactions
        if any(tx["amount"] % 10**18 == 0 for tx in transactions):
            patterns.append("Round-number transactions detected")

        # Mixing service usage: High transaction volume
        if tx_count > self.pattern_thresholds["mixer_tx_count"]:
            patterns.append("Possible mixing service usage")

        # Ransomware-like: High-value single transaction with low tx count
        if any(tx["amount"] > self.pattern_thresholds["high_value"] and tx_count < 5 for tx in transactions):
            patterns.append("Possible ransomware payment")

        # Unusual timing: High frequency in very short window
        if timestamps and (max(timestamps) - min(timestamps)) < self.pattern_thresholds["timing_window"] and tx_count > self.pattern_thresholds["timing_tx_count"]:
            patterns.append("Unusual transaction timing")

        # AI-based anomaly detection
        features = np.array([[tx["amount"], (datetime.fromisoformat(tx["timestamp"].replace("Z", "")) - datetime(1970, 1, 1)).total_seconds()] for tx in transactions])
        if len(features) > 1:  # Need at least 2 samples for IsolationForest
            anomalies = self.anomaly_model.fit_predict(features)
            if -1 in anomalies:  # -1 indicates anomaly
                patterns.append("AI-detected anomaly")

        return patterns

    def calculate_risk_score(self, transactions: List[Dict]) -> Dict:
        """Calculate risk score with AI and pattern-based weighting."""
        if not self.validate_transactions(transactions):
            return {"score": 0, "level": "low", "justification": ["Invalid transaction data"]}

        patterns = self.detect_patterns(transactions)
        tx_count = len(transactions)

        # Base score: Transaction count contribution
        base_score = min(tx_count * self.risk_weights["tx_count"], 50)  # Cap at 50
        # Pattern weight: 20 points per detected pattern
        pattern_weight = len(patterns) * self.risk_weights["patterns"]
        # AI anomaly weight: Extra boost if AI flags anomalies
        ai_weight = self.risk_weights["ai_anomaly"] if "AI-detected anomaly" in patterns else 0

        # Total score capped at 100
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
        """Train the AI model with historical data."""
        if not self.validate_transactions(historical_transactions) or len(historical_transactions) < 2:
            logger.error("Insufficient or invalid historical data for training")
            return

        features = np.array([[tx["amount"], (datetime.fromisoformat(tx["timestamp"].replace("Z", "")) - datetime(1970, 1, 1)).total_seconds()] for tx in historical_transactions])
        self.anomaly_model.fit(features)
        logger.info("Anomaly model trained with historical data")

if __name__ == "__main__":
    detector = PatternDetector()
    # Example transactions
    sample_txs = [
        {"amount": 10**18, "timestamp": "2025-03-07T12:00:00Z", "tx_hash": "0x1"},
        {"amount": 10**16, "timestamp": "2025-03-07T12:01:00Z", "tx_hash": "0x2"},
        {"amount": 10**20, "timestamp": "2025-03-07T12:02:00Z", "tx_hash": "0x3"}
    ]
    patterns = detector.detect_patterns(sample_txs)
    print(f"Detected patterns: {patterns}")
    risk = detector.calculate_risk_score(sample_txs)
    print(f"Risk score: {risk}")
    adjusted = detector.adjust_risk_score(risk, 10, "Investigator suspicion")
    print(f"Adjusted risk: {adjusted}")