# backend/reporting.py
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

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ReportGenerator:
    """Advanced report generation and storage for blockchain investigations."""
    def __init__(self):
        self.ipfs = connect()  # IPFS client for decentralized storage
        self.styles = getSampleStyleSheet()

    def validate_data(self, data: Dict) -> bool:
        """Validate report data structure."""
        required_keys = ["address", "transactions"]
        if not isinstance(data, dict) or not all(key in data for key in required_keys):
            logger.error(f"Invalid report data: {data}")
            return False
        return True

    def generate_pdf_report(self, report_data: Dict, filename: Optional[str] = None) -> Optional[str]:
        """Generate a PDF report with wallet, transaction, case, pattern, and IP data."""
        if not self.validate_data(report_data):
            return None

        # Default filename if not provided
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
            for tx in report_data["transactions"][:10]:  # Limit to 10 for brevity
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

            # Case Details (if provided)
            if "case" in report_data:
                story.append(Paragraph(f"Case: {report_data['case']['name']}", self.styles["Heading2"]))
                story.append(Paragraph(f"ID: {report_data['case']['case_id']} | Status: {report_data['case']['status']}", self.styles["Normal"]))
                story.append(Paragraph(f"Investigator: {report_data['case']['investigator']}", self.styles["Normal"]))
                story.append(Spacer(1, 12))

            # Patterns (if provided)
            if "patterns" in report_data:
                story.append(Paragraph("Detected Patterns", self.styles["Heading2"]))
                for pattern in report_data["patterns"]:
                    story.append(Paragraph(f"- {pattern}", self.styles["Normal"]))
                story.append(Spacer(1, 12))

            # IP Data (if provided)
            if "ip_data" in report_data:
                story.append(Paragraph("IP Tracing", self.styles["Heading2"]))
                ip_data = [["Tx Hash", "Location", "High Risk"]]
                for ip in report_data["ip_data"][:5]:  # Limit to 5
                    ip_data.append([ip["tx_hash"][:10] + "...", ip["location"], "Yes" if ip["high_risk"] else "No"])
                ip_table = Table(ip_data, colWidths=[100, 200, 80])
                ip_table.setStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)])
                story.append(ip_table)

            # Build PDF
            doc.build(story)

            # Store on IPFS
            ipfs_hash = self.ipfs.add(filename)["Hash"]
            os.remove(filename)  # Clean up local file
            logger.info(f"Report generated and stored on IPFS: {ipfs_hash}")
            return ipfs_hash
        except Exception as e:
            logger.error(f"Error generating report for {report_data['address']}: {e}")
            return None

    def aggregate_report_data(self, wallet_data: Dict, case_data: Optional[Dict] = None, 
                            pattern_data: Optional[List[str]] = None, ip_data: Optional[List[Dict]] = None) -> Dict:
        """Aggregate data from various sources into a unified report structure."""
        report_data = {
            "address": wallet_data["address"],
            "transactions": wallet_data["transactions"],
            "type": wallet_data.get("type", "Unknown"),
            "risk_level": wallet_data.get("risk_level", "N/A"),
            "balance_change": wallet_data.get("balance_change", 0),
            "chain": wallet_data["transactions"][0]["chain"] if wallet_data["transactions"] else "Unknown"
        }

        if case_data:
            report_data["case"] = case_data
        if pattern_data:
            report_data["patterns"] = pattern_data
        if ip_data:
            report_data["ip_data"] = ip_data

        return report_data

if __name__ == "__main__":
    generator = ReportGenerator()
    # Sample data
    wallet_data = {
        "address": "0x28c6c06298d514db089934071355e5743bf21d60",
        "transactions": [
            {"tx_hash": "0x4e3a3754410177e6937ef1d0084000883f919978", "from_address": "0xabc", "to_address": "0xdef", "amount": 1.5, "timestamp": "2025-03-07T12:00:00Z", "chain": "ethereum"},
            {"tx_hash": "0xanotherhash", "from_address": "0xdef", "to_address": "0xghi", "amount": 0.8, "timestamp": "2025-03-07T12:01:00Z", "chain": "ethereum", "token": {"symbol": "USDT", "value": 0.8}}
        ],
        "type": "personal",
        "risk_level": "medium",
        "balance_change": 0.7
    }
    case_data = {"case_id": 1, "name": "Test Case", "status": "in_progress", "investigator": "Alice"}
    patterns = ["Possible layering", "Unusual timing"]
    ip_data = [{"tx_hash": "0x4e3a3754410177e6937ef1d0084000883f919978", "location": "New York, USA", "high_risk": False}]
    
    report_data = generator.aggregate_report_data(wallet_data, case_data, patterns, ip_data)
    ipfs_hash = generator.generate_pdf_report(report_data)
    print(f"Report stored at IPFS hash: {ipfs_hash}")