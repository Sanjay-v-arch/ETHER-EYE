# backend/reporting.py
import aiohttp
from neo4j import AsyncGraphDatabase
import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from ipfshttpclient import connect
from dotenv import load_dotenv
from .blockchain import BlockchainConnector
from .tracing import TransactionTracer
from .patterns import PatternDetector
from .ip_tracing import IPTracer
from .cases import CaseManager

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ReportGenerator:
    """Advanced report generation and storage for blockchain investigations."""
    def __init__(self, blockchain_connector: BlockchainConnector, tracer: TransactionTracer,
                 pattern_detector: PatternDetector, ip_tracer: IPTracer, case_manager: CaseManager):
        self.ipfs = connect()
        self.styles = getSampleStyleSheet()
        self.connector = blockchain_connector
        self.tracer = tracer
        self.pattern_detector = pattern_detector
        self.ip_tracer = ip_tracer
        self.case_manager = case_manager

    def validate_data(self, data: Dict) -> bool:
        """Validate report data structure with nested checks."""
        required_keys = ["address", "transactions"]
        if not isinstance(data, dict) or not all(key in data for key in required_keys):
            logger.error(f"Invalid report data: {data}")
            return False
        for tx in data["transactions"]:
            if not all(k in tx for k in ["tx_hash", "from_address", "to_address", "amount", "timestamp", "chain"]):
                logger.error(f"Invalid transaction in report data: {tx}")
                return False
        return True

    async def generate_pdf_report(self, report_data: Dict, filename: Optional[str] = None) -> Optional[str]:
        """Generate a PDF report with wallet, transaction, case, pattern, and IP data."""
        if not self.validate_data(report_data):
            return None

        filename = filename or f"report_{report_data['address'][:6]}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        try:
            doc = SimpleDocTemplate(filename, pagesize=letter)
            story = []

            # Header
            story.append(Paragraph("Blockchain Investigation Report", self.styles["Title"]))
            story.append(Spacer(1, 12))
            story.append(Paragraph(f"Generated: {datetime.utcnow().isoformat()}Z", self.styles["Normal"]))
            story.append(Spacer(1, 12))

            # Wallet Summary
            story.append(Paragraph(f"Wallet: {report_data['address']}", self.styles["Heading2"]))
            if "type" in report_data:
                story.append(Paragraph(f"Type: {report_data['type']} | Risk: {report_data.get('risk_level', 'N/A')}", self.styles["Normal"]))
            if "balance_change" in report_data:
                story.append(Paragraph(f"Balance Change: {report_data['balance_change']:.6f} {report_data.get('chain', 'ETH')}", self.styles["Normal"]))
            story.append(Spacer(1, 12))

            # Transactions
            story.append(Paragraph("Recent Transactions", self.styles["Heading2"]))
            tx_data = [["Tx Hash", "From", "To", "Amount", "Timestamp"]]
            for tx in report_data["transactions"][:10]:
                tx_data.append([
                    tx["tx_hash"][:10] + "...",
                    tx["from_address"][:10] + "...",
                    tx["to_address"][:10] + "..." if tx["to_address"] else "None",
                    f"{tx['amount']:.2f} {tx.get('token', {}).get('symbol', tx.get('chain', 'ETH'))}",
                    tx["timestamp"]
                ])
            tx_table = Table(tx_data, colWidths=[100, 100, 100, 80, 120])
            tx_table.setStyle([
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke)
            ])
            story.append(tx_table)
            story.append(Spacer(1, 12))

            # Case Details
            if "case" in report_data:
                story.append(Paragraph(f"Case: {report_data['case']['name']}", self.styles["Heading2"]))
                story.append(Paragraph(f"ID: {report_data['case']['case_id']} | Status: {report_data['case']['status']}", self.styles["Normal"]))
                story.append(Paragraph(f"Investigator: {report_data['case']['investigator']}", self.styles["Normal"]))
                story.append(Spacer(1, 12))

            # Patterns
            if "patterns" in report_data:
                story.append(Paragraph("Detected Patterns", self.styles["Heading2"]))
                for pattern in report_data["patterns"]:
                    story.append(Paragraph(f"- {pattern}", self.styles["Normal"]))
                story.append(Spacer(1, 12))

            # IP Data
            if "ip_data" in report_data:
                story.append(Paragraph("IP Tracing", self.styles["Heading2"]))
                ip_data = [["Tx Hash", "Location", "High Risk"]]
                for ip in report_data["ip_data"][:5]:
                    ip_data.append([ip["tx_hash"][:10] + "...", ip["location"], "Yes" if ip["high_risk"] else "No"])
                ip_table = Table(ip_data, colWidths=[100, 200, 80])
                ip_table.setStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)])
                story.append(ip_table)

            # Build PDF
            doc.build(story)

            # Store on IPFS with error handling
            try:
                ipfs_hash = self.ipfs.add(filename)["Hash"]
                os.remove(filename)
                logger.info(f"Report generated and stored on IPFS: {ipfs_hash}")
                return ipfs_hash
            except Exception as e:
                logger.error(f"IPFS storage failed: {e}")
                return filename  # Return local file path if IPFS fails
        except Exception as e:
            logger.error(f"Error generating report for {report_data['address']}: {e}")
            return None

    async def aggregate_report_data(self, address: str, chain: str, case_id: Optional[int] = None) -> Dict:
        """Fetch and aggregate data dynamically from other modules."""
        async with aiohttp.ClientSession() as session:
            wallet_history = await self.connector.get_wallet_history(session, address, chain)
            balance_change = sum(tx["value"] for tx in wallet_history) if wallet_history else 0
            patterns = await self.pattern_detector.detect_patterns(wallet_history)
            ip_data = await self.ip_tracer.get_geographical_distribution([tx["tx_hash"] for tx in wallet_history], chain)
            case_data = await self.case_manager.get_case_details(case_id) if case_id else None

        report_data = {
            "address": address,
            "transactions": wallet_history,
            "type": "personal",  # Placeholder; could be enhanced with wallet type detection
            "risk_level": (await self.pattern_detector.calculate_risk_score(wallet_history)).get("level", "N/A"),
            "balance_change": balance_change,
            "chain": chain
        }
        if case_data:
            report_data["case"] = case_data
        if patterns:
            report_data["patterns"] = patterns
        if ip_data:
            report_data["ip_data"] = [{"tx_hash": tx["tx_hash"], "location": d["location"], "high_risk": False} for tx in wallet_history for d in ip_data if d["location"]]

        return report_data

if __name__ == "__main__":
    neo4j_driver = AsyncGraphDatabase.driver(os.getenv("NEO4J_URL", "bolt://localhost:7687"),
                                        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password")))
    connector = BlockchainConnector()
    tracer = TransactionTracer(connector, neo4j_driver)
    pattern_detector = PatternDetector(connector)
    ip_tracer = IPTracer(neo4j_driver)
    case_manager = CaseManager(neo4j_driver, connector)
    generator = ReportGenerator(connector, tracer, pattern_detector, ip_tracer, case_manager)
    
    async def test():
        report_data = await generator.aggregate_report_data("0x28c6c06298d514db089934071355e5743bf21d60", "ethereum", 1)
        ipfs_hash = await generator.generate_pdf_report(report_data)
        print(f"Report stored at IPFS hash: {ipfs_hash}")
    asyncio.run(test())