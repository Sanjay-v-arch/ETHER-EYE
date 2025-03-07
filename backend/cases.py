# backend/cases.py
import logging
from datetime import datetime
from typing import Dict, List, Optional
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class CaseManager:
    """Advanced case management for blockchain investigations with Neo4j integration."""
    def __init__(self, neo4j_driver):
        self.driver = neo4j_driver
        self.valid_statuses = ["open", "in_progress", "closed"]

    def validate_case_data(self, name: str, status: str, investigator: str) -> bool:
        """Validate case creation parameters."""
        if not isinstance(name, str) or not name.strip():
            logger.error("Case name must be a non-empty string")
            return False
        if status not in self.valid_statuses:
            logger.error(f"Invalid status: {status}. Must be one of {self.valid_statuses}")
            return False
        if not isinstance(investigator, str) or not investigator.strip():
            logger.error("Investigator must be a non-empty string")
            return False
        return True

    def validate_tx_hash(self, tx_hash: str) -> bool:
        """Validate transaction hash (simplified, chain-agnostic)."""
        return isinstance(tx_hash, str) and len(tx_hash) > 10 and tx_hash.strip()

    async def create_case(self, name: str, investigator: str, status: str = "open") -> Optional[int]:
        """Create a new investigation case in Neo4j."""
        if not self.validate_case_data(name, status, investigator):
            return None

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    CREATE (c:Case {name: $name, created_at: $created_at, status: $status, investigator: $investigator})
                    RETURN id(c) as case_id
                    """,
                    name=name,
                    created_at=datetime.utcnow().isoformat() + "Z",
                    status=status,
                    investigator=investigator
                )
                case_id = result.single()["case_id"]

                # Log audit trail
                await self.log_audit_trail(case_id, "Case created", investigator)
                logger.info(f"Case {case_id} created: {name} by {investigator}")
                return case_id
        except Exception as e:
            logger.error(f"Error creating case {name}: {e}")
            return None

    async def associate_transaction(self, case_id: int, tx_hash: str, user: str) -> bool:
        """Associate a transaction with a case in Neo4j."""
        if not isinstance(case_id, int) or case_id < 0 or not self.validate_tx_hash(tx_hash) or not user.strip():
            logger.error(f"Invalid parameters: case_id={case_id}, tx_hash={tx_hash}, user={user}")
            return False

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (c:Case) WHERE id(c) = $case_id
                    MATCH (t:Transaction {tx_hash: $tx_hash})
                    MERGE (c)-[:INCLUDES]->(t)
                    RETURN c
                    """,
                    case_id=case_id,
                    tx_hash=tx_hash
                )
                if not result.single():
                    logger.error(f"Case {case_id} or transaction {tx_hash} not found")
                    return False

                # Log audit trail
                await self.log_audit_trail(case_id, f"Transaction {tx_hash} associated", user)
                logger.info(f"Transaction {tx_hash} associated with case {case_id} by {user}")
                return True
        except Exception as e:
            logger.error(f"Error associating tx {tx_hash} with case {case_id}: {e}")
            return False

    async def update_case_status(self, case_id: int, new_status: str, user: str) -> bool:
        """Update the status of a case."""
        if not isinstance(case_id, int) or case_id < 0 or new_status not in self.valid_statuses or not user.strip():
            logger.error(f"Invalid parameters: case_id={case_id}, status={new_status}, user={user}")
            return False

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (c:Case) WHERE id(c) = $case_id
                    SET c.status = $new_status
                    RETURN c
                    """,
                    case_id=case_id,
                    new_status=new_status
                )
                if not result.single():
                    logger.error(f"Case {case_id} not found")
                    return False

                # Log audit trail
                await self.log_audit_trail(case_id, f"Status updated to {new_status}", user)
                logger.info(f"Case {case_id} status updated to {new_status} by {user}")
                return True
        except Exception as e:
            logger.error(f"Error updating case {case_id} status: {e}")
            return False

    async def log_audit_trail(self, case_id: int, action: str, user: str):
        """Log an action in the audit trail."""
        if not isinstance(case_id, int) or case_id < 0 or not action.strip() or not user.strip():
            logger.error(f"Invalid audit parameters: case_id={case_id}, action={action}, user={user}")
            return

        try:
            with self.driver.session() as session:
                session.run(
                    """
                    CREATE (a:Audit {case_id: $case_id, action: $action, timestamp: $timestamp, user: $user})
                    MATCH (c:Case) WHERE id(c) = $case_id
                    MERGE (c)-[:HAS_AUDIT]->(a)
                    """,
                    case_id=case_id,
                    action=action,
                    timestamp=datetime.utcnow().isoformat() + "Z",
                    user=user
                )
                logger.info(f"Audit logged for case {case_id}: {action} by {user}")
        except Exception as e:
            logger.error(f"Error logging audit for case {case_id}: {e}")

    async def get_case_details(self, case_id: int) -> Optional[Dict]:
        """Retrieve case details including associated transactions and audit trail."""
        if not isinstance(case_id, int) or case_id < 0:
            logger.error(f"Invalid case_id: {case_id}")
            return None

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (c:Case) WHERE id(c) = $case_id
                    OPTIONAL MATCH (c)-[:INCLUDES]->(t:Transaction)
                    OPTIONAL MATCH (c)-[:HAS_AUDIT]->(a:Audit)
                    RETURN c, collect(t.tx_hash) as transactions, collect(a) as audits
                    """,
                    case_id=case_id
                )
                record = result.single()
                if not record:
                    logger.error(f"Case {case_id} not found")
                    return None

                case_node = record["c"]
                return {
                    "case_id": case_id,
                    "name": case_node["name"],
                    "created_at": case_node["created_at"],
                    "status": case_node["status"],
                    "investigator": case_node["investigator"],
                    "transactions": record["transactions"],
                    "audit_trail": [{"action": a["action"], "timestamp": a["timestamp"], "user": a["user"]} for a in record["audits"]]
                }
        except Exception as e:
            logger.error(f"Error retrieving case {case_id}: {e}")
            return None

if __name__ == "__main__":
    neo4j_driver = GraphDatabase.driver(os.getenv("NEO4J_URL", "bolt://localhost:7687"),
                                        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password")))
    manager = CaseManager(neo4j_driver)
    async def test():
        case_id = await manager.create_case("Test Case", "Alice")
        if case_id:
            await manager.associate_transaction(case_id, "0x4e3a3754410177e6937ef1d0084000883f919978", "Alice")
            await manager.update_case_status(case_id, "in_progress", "Alice")
            details = await manager.get_case_details(case_id)
            print(f"Case details: {details}")
    asyncio.run(test())