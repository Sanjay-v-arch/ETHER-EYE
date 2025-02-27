# Main application structure with core modules
import os
import json
import pandas as pd
from datetime import datetime
import requests
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import networkx as nx
import matplotlib.pyplot as plt
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database setup
Base = declarative_base()
engine = create_engine('sqlite:///crypto_intelligence.db')
Session = sessionmaker(bind=engine)
session = Session()

# Database models
class Wallet(Base):
    __tablename__ = 'wallets'
    
    id = Column(Integer, primary_key=True)
    address = Column(String, unique=True)
    blockchain = Column(String)
    first_seen = Column(DateTime)
    last_seen = Column(DateTime)
    total_received = Column(Float, default=0)
    total_sent = Column(Float, default=0)
    current_balance = Column(Float, default=0)
    risk_score = Column(Float, default=0)
    transactions = relationship("Transaction", back_populates="wallet")
    
    def update_balance(self):
        self.current_balance = self.total_received - self.total_sent
        
class Transaction(Base):
    __tablename__ = 'transactions'
    
    id = Column(Integer, primary_key=True)
    tx_hash = Column(String, unique=True)
    blockchain = Column(String)
    timestamp = Column(DateTime)
    value = Column(Float)
    wallet_id = Column(Integer, ForeignKey('wallets.id'))
    from_address = Column(String)
    to_address = Column(String)
    fee = Column(Float)
    status = Column(String)
    ip_address = Column(String, nullable=True)
    suspicious_score = Column(Float, default=0)
    wallet = relationship("Wallet", back_populates="transactions")

# Create tables
Base.metadata.create_all(engine)

# API connectors for different blockchains
class BlockchainConnector:
    def __init__(self):
        self.api_keys = {
            'etherscan': os.getenv('ETHERSCAN_API_KEY'),
            'blockchair': os.getenv('BLOCKCHAIR_API_KEY'),
            'blockcypher': os.getenv('BLOCKCYPHER_API_KEY')
        }
        
    def get_transaction_data(self, tx_hash, blockchain):
        if blockchain == 'ethereum':
            return self._get_ethereum_transaction(tx_hash)
        elif blockchain == 'bitcoin':
            return self._get_bitcoin_transaction(tx_hash)
        else:
            raise ValueError(f"Unsupported blockchain: {blockchain}")
    
    def _get_ethereum_transaction(self, tx_hash):
        url = f"https://api.etherscan.io/api?module=proxy&action=eth_getTransactionByHash&txhash={tx_hash}&apikey={self.api_keys['etherscan']}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and data['result']:
                # Process and format the Ethereum transaction data
                return {
                    'tx_hash': tx_hash,
                    'blockchain': 'ethereum',
                    'timestamp': datetime.now(),  # Would parse from block timestamp in a real implementation
                    'value': int(data['result']['value'], 16) / 10**18,
                    'from_address': data['result']['from'],
                    'to_address': data['result']['to'],
                    'fee': int(data['result']['gas'], 16) * int(data['result']['gasPrice'], 16) / 10**18,
                    'status': 'confirmed'
                }
        return None
    
    def _get_bitcoin_transaction(self, tx_hash):
        url = f"https://api.blockchair.com/bitcoin/transactions?q=hash({tx_hash})&key={self.api_keys['blockchair']}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and data['data']:
                # Process and format the Bitcoin transaction data
                tx = data['data'][0]
                return {
                    'tx_hash': tx_hash,
                    'blockchain': 'bitcoin',
                    'timestamp': datetime.fromtimestamp(tx['time']),
                    'value': tx['output_total'] / 10**8,
                    'from_address': ','.join([input['recipient'] for input in tx['inputs']]),
                    'to_address': ','.join([output['recipient'] for output in tx['outputs']]),
                    'fee': tx['fee'] / 10**8,
                    'status': 'confirmed'
                }
        return None

    def get_wallet_history(self, address, blockchain, limit=100):
        if blockchain == 'ethereum':
            return self._get_ethereum_wallet_history(address, limit)
        elif blockchain == 'bitcoin':
            return self._get_bitcoin_wallet_history(address, limit)
        else:
            raise ValueError(f"Unsupported blockchain: {blockchain}")
    
    def _get_ethereum_wallet_history(self, address, limit):
        url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&startblock=0&endblock=99999999&sort=desc&apikey={self.api_keys['etherscan']}"
        response = requests.get(url)
        transactions = []
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and isinstance(data['result'], list):
                for tx in data['result'][:limit]:
                    transactions.append({
                        'tx_hash': tx['hash'],
                        'blockchain': 'ethereum',
                        'timestamp': datetime.fromtimestamp(int(tx['timeStamp'])),
                        'value': float(tx['value']) / 10**18,
                        'from_address': tx['from'],
                        'to_address': tx['to'],
                        'fee': float(tx['gasPrice']) * float(tx['gasUsed']) / 10**18,
                        'status': 'confirmed' if tx['txreceipt_status'] == '1' else 'failed'
                    })
        return transactions
    
    def _get_bitcoin_wallet_history(self, address, limit):
        url = f"https://api.blockchair.com/bitcoin/dashboards/address/{address}?key={self.api_keys['blockchair']}"
        response = requests.get(url)
        transactions = []
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and address in data['data']:
                txs = data['data'][address]['transactions']
                for tx_hash in txs[:limit]:
                    tx_data = self.get_transaction_data(tx_hash, 'bitcoin')
                    if tx_data:
                        transactions.append(tx_data)
        return transactions

# Transaction tracing module
class TransactionTracer:
    def __init__(self, blockchain_connector):
        self.blockchain_connector = blockchain_connector
        self.graph = nx.DiGraph()
        
    def trace_transaction(self, tx_hash, blockchain, depth=3):
        """Trace a transaction and its connected transactions up to a certain depth."""
        visited = set()
        self._trace_transaction_recursive(tx_hash, blockchain, depth, visited)
        return self.graph
    
    def _trace_transaction_recursive(self, tx_hash, blockchain, depth, visited):
        if depth == 0 or tx_hash in visited:
            return
        
        visited.add(tx_hash)
        tx_data = self.blockchain_connector.get_transaction_data(tx_hash, blockchain)
        
        if not tx_data:
            return
        
        # Add nodes and edges to the graph
        from_addr = tx_data['from_address']
        to_addr = tx_data['to_address']
        
        if from_addr not in self.graph:
            self.graph.add_node(from_addr, type='wallet', blockchain=blockchain)
        
        if to_addr not in self.graph:
            self.graph.add_node(to_addr, type='wallet', blockchain=blockchain)
            
        self.graph.add_edge(from_addr, to_addr, 
                           tx_hash=tx_hash, 
                           value=tx_data['value'],
                           timestamp=tx_data['timestamp'])
        
        # Continue tracing for both addresses
        if depth > 1:
            # Get related transactions for source address
            from_txs = self.blockchain_connector.get_wallet_history(from_addr, blockchain, limit=5)
            for tx in from_txs:
                if tx['tx_hash'] != tx_hash:  # Avoid re-tracing the same transaction
                    self._trace_transaction_recursive(tx['tx_hash'], blockchain, depth-1, visited)
            
            # Get related transactions for destination address
            to_txs = self.blockchain_connector.get_wallet_history(to_addr, blockchain, limit=5)
            for tx in to_txs:
                if tx['tx_hash'] != tx_hash:  # Avoid re-tracing the same transaction
                    self._trace_transaction_recursive(tx['tx_hash'], blockchain, depth-1, visited)
    
    def get_transaction_trail(self, tx_hash, blockchain, depth=3):
        """Get a complete trail of transactions starting from a specific transaction."""
        self.graph.clear()  # Reset the graph
        self.trace_transaction(tx_hash, blockchain, depth)
        return self.graph
    
    def visualize_transaction_trail(self, filename='transaction_trail.png'):
        """Create a visualization of the transaction trail."""
        plt.figure(figsize=(12, 10))
        
        # Create positions for nodes
        pos = nx.spring_layout(self.graph)
        
        # Draw the graph
        nx.draw_networkx_nodes(self.graph, pos, node_size=300, node_color='skyblue')
        nx.draw_networkx_edges(self.graph, pos, width=1, arrowsize=15)
        nx.draw_networkx_labels(self.graph, pos, font_size=10)
        
        # Add edge labels (transaction values)
        edge_labels = {(u, v): f"{d['value']:.4f}" for u, v, d in self.graph.edges(data=True)}
        nx.draw_networkx_edge_labels(self.graph, pos, edge_labels=edge_labels, font_size=8)
        
        plt.axis('off')
        plt.tight_layout()
        plt.savefig(filename, format='PNG', dpi=300)
        plt.close()
        
        return filename

# Pattern detection for suspicious transactions
class PatternDetector:
    def __init__(self, blockchain_connector, session):
        self.blockchain_connector = blockchain_connector
        self.session = session
        self.suspicious_patterns = [
            self._check_large_transaction,
            self._check_peeling_chain,
            self._check_known_suspicious_addresses,
            self._check_mixer_usage,
            self._check_rapid_transfers
        ]
    
    def analyze_wallet(self, address, blockchain):
        """Analyze a wallet for suspicious patterns."""
        transactions = self.blockchain_connector.get_wallet_history(address, blockchain)
        scores = []
        
        for tx in transactions:
            score = self._calculate_suspicion_score(tx, transactions)
            scores.append((tx['tx_hash'], score))
            
            # Update the transaction in the database with the suspicion score
            db_tx = self.session.query(Transaction).filter_by(tx_hash=tx['tx_hash']).first()
            if db_tx:
                db_tx.suspicious_score = score
            else:
                # Create a new transaction record
                wallet = self.session.query(Wallet).filter_by(address=address).first()
                if not wallet:
                    wallet = Wallet(address=address, blockchain=blockchain, 
                                   first_seen=datetime.now(), last_seen=datetime.now())
                    self.session.add(wallet)
                    self.session.commit()
                
                new_tx = Transaction(
                    tx_hash=tx['tx_hash'],
                    blockchain=tx['blockchain'],
                    timestamp=tx['timestamp'],
                    value=tx['value'],
                    from_address=tx['from_address'],
                    to_address=tx['to_address'],
                    fee=tx['fee'],
                    status=tx['status'],
                    suspicious_score=score,
                    wallet_id=wallet.id
                )
                self.session.add(new_tx)
        
        self.session.commit()
        
        # Update the wallet's risk score based on transaction scores
        wallet = self.session.query(Wallet).filter_by(address=address).first()
        if wallet:
            if scores:
                wallet.risk_score = sum(score for _, score in scores) / len(scores)
            wallet.last_seen = datetime.now()
            self.session.commit()
        
        return scores
    
    def _calculate_suspicion_score(self, transaction, all_transactions):
        """Calculate a suspicion score for a transaction."""
        score = 0
        for pattern_check in self.suspicious_patterns:
            score += pattern_check(transaction, all_transactions)
        
        # Normalize score to be between 0 and 1
        return min(score / len(self.suspicious_patterns), 1.0)
    
    def _check_large_transaction(self, transaction, all_transactions):
        """Check if this is an unusually large transaction."""
        # Calculate average transaction value
        if not all_transactions:
            return 0
            
        avg_value = sum(tx['value'] for tx in all_transactions) / len(all_transactions)
        
        # If this transaction is significantly larger than average
        if transaction['value'] > avg_value * 5:
            return 0.8
        elif transaction['value'] > avg_value * 3:
            return 0.5
        elif transaction['value'] > avg_value * 2:
            return 0.3
        return 0
    
    def _check_peeling_chain(self, transaction, all_transactions):
        """Check for peeling chain pattern (money laundering technique)."""
        # Look for a pattern of one large input followed by many small outputs
        sender = transaction['from_address']
        sender_txs = [tx for tx in all_transactions if tx['from_address'] == sender]
        
        if len(sender_txs) < 5:
            return 0
            
        # Sort by timestamp
        sender_txs.sort(key=lambda x: x['timestamp'])
        
        # Check if there's a large transaction followed by many small ones
        for i in range(len(sender_txs) - 4):
            large_tx = sender_txs[i]
            following_txs = sender_txs[i+1:i+5]
            
            # Check if the first transaction is large and the following are small
            if large_tx['value'] > sum(tx['value'] for tx in following_txs):
                return 0.7
                
        return 0
    
    def _check_known_suspicious_addresses(self, transaction, all_transactions):
        """Check if transaction involves known suspicious addresses."""
        # In a real implementation, this would check against a database of suspicious addresses
        suspicious_addresses = [
            '0x123456789abcdef123456789abcdef123456789a',  # Example address
            '1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'  # Example address
        ]
        
        if transaction['from_address'] in suspicious_addresses or transaction['to_address'] in suspicious_addresses:
            return 1.0
        return 0
    
    def _check_mixer_usage(self, transaction, all_transactions):
        """Check if transaction involves known mixing services."""
        # Known mixer services (in a real implementation, this would be more comprehensive)
        mixer_addresses = [
            '0x722122df12d4e14e13ac3b6895a86e84145b6967',  # Example Ethereum mixer
            '3P3QsMVK89JBNqZQv5zMAKG8FK3kJM4rjt'  # Example Bitcoin mixer
        ]
        
        if transaction['from_address'] in mixer_addresses or transaction['to_address'] in mixer_addresses:
            return 0.9
        return 0
    
    def _check_rapid_transfers(self, transaction, all_transactions):
        """Check for rapid succession of transfers (potential layering)."""
        address = transaction['to_address']
        address_txs = [tx for tx in all_transactions if tx['from_address'] == address or tx['to_address'] == address]
        
        # Sort by timestamp
        address_txs.sort(key=lambda x: x['timestamp'])
        
        # Check for rapid succession of transactions (within 10 minutes)
        for i in range(len(address_txs) - 1):
            time_diff = (address_txs[i+1]['timestamp'] - address_txs[i]['timestamp']).total_seconds()
            if time_diff < 600 and address_txs[i]['to_address'] == address and address_txs[i+1]['from_address'] == address:
                return 0.6
                
        return 0

# IP Address Tracker (integration with SpiderFoot)
class IPTracker:
    def __init__(self, spiderfoot_url=None, spiderfoot_api_key=None):
        self.spiderfoot_url = spiderfoot_url or os.getenv('SPIDERFOOT_URL', 'http://localhost:5001')
        self.spiderfoot_api_key = spiderfoot_api_key or os.getenv('SPIDERFOOT_API_KEY', '')
        
    def track_ip_for_transaction(self, tx_hash, blockchain):
        """Try to find IP addresses associated with a transaction."""
        # This is a simplified implementation
        # In a real system, this would integrate with SpiderFoot API or other OSINT tools
        
        # For demonstration purposes, we'll return a dummy IP
        # In a real implementation, this would:
        # 1. Query blockchain nodes that might have seen this transaction
        # 2. Use SpiderFoot to gather additional intelligence on the IPs
        # 3. Cross-reference with other known data
        
        return {
            'ip': '192.168.1.1',
            'geolocation': {
                'country': 'United States',
                'city': 'New York',
                'coordinates': [40.7128, -74.0060]
            },
            'confidence': 0.4,
            'source': 'simulated_data'
        }
        
    def start_spiderfoot_scan(self, target, scan_name, scan_type='WALLET_OSINT'):
        """Start a SpiderFoot scan for a target."""
        if not self.spiderfoot_url or not self.spiderfoot_api_key:
            return None
            
        url = f"{self.spiderfoot_url}/scanSettings"
        headers = {
            'Content-Type': 'application/json',
            'X-API-Key': self.spiderfoot_api_key
        }
        data = {
            'scanName': scan_name,
            'scanTarget': target,
            'usecase': scan_type,
            'modulelist': ['sfp_blockchain', 'sfp_bitcoin', 'sfp_ethereum', 'sfp_binance'],
            'maxRuntime': 3600
        }
        
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            scan_id = response.json().get('id')
            return scan_id
        return None
        
    def get_scan_results(self, scan_id):
        """Get the results of a SpiderFoot scan."""
        if not self.spiderfoot_url or not self.spiderfoot_api_key:
            return []
            
        url = f"{self.spiderfoot_url}/scanResults?id={scan_id}"
        headers = {
            'X-API-Key': self.spiderfoot_api_key
        }
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        return []

# Main application class
class CryptoAnalysisTool:
    def __init__(self):
        self.blockchain_connector = BlockchainConnector()
        self.transaction_tracer = TransactionTracer(self.blockchain_connector)
        self.pattern_detector = PatternDetector(self.blockchain_connector, session)
        self.ip_tracker = IPTracker()
        
    def analyze_transaction(self, tx_hash, blockchain, depth=3):
        """Analyze a single transaction in depth."""
        # Get transaction data
        tx_data = self.blockchain_connector.get_transaction_data(tx_hash, blockchain)
        if not tx_data:
            return {
                'success': False,
                'message': f"Transaction {tx_hash} not found on {blockchain}"
            }
        
        # Trace transaction flow
        transaction_graph = self.transaction_tracer.get_transaction_trail(tx_hash, blockchain, depth)
        
        # Save visualization
        visualization_file = self.transaction_tracer.visualize_transaction_trail(f"{tx_hash[:8]}_trail.png")
        
        # Track IP if possible
        ip_data = self.ip_tracker.track_ip_for_transaction(tx_hash, blockchain)
        
        # Analyze patterns
        from_address = tx_data['from_address']
        to_address = tx_data['to_address']
        
        from_analysis = self.pattern_detector.analyze_wallet(from_address, blockchain)
        to_analysis = self.pattern_detector.analyze_wallet(to_address, blockchain)
        
        # Compile report
        report = {
            'success': True,
            'transaction': tx_data,
            'ip_data': ip_data,
            'from_wallet': {
                'address': from_address,
                'suspicious_score': max([score for _, score in from_analysis] if from_analysis else [0]),
                'transaction_count': len(from_analysis)
            },
            'to_wallet': {
                'address': to_address,
                'suspicious_score': max([score for _, score in to_analysis] if to_analysis else [0]),
                'transaction_count': len(to_analysis)
            },
            'visualization_file': visualization_file,
            'graph_data': {
                'nodes': len(transaction_graph.nodes()),
                'edges': len(transaction_graph.edges()),
                'total_value': sum(data['value'] for _, _, data in transaction_graph.edges(data=True))
            }
        }
        
        return report
    
    def generate_wallet_report(self, address, blockchain):
        """Generate a detailed report for a wallet."""
        # Get wallet history
        transactions = self.blockchain_connector.get_wallet_history(address, blockchain)
        
        if not transactions:
            return {
                'success': False,
                'message': f"No transactions found for wallet {address} on {blockchain}"
            }
        
        # Analyze patterns
        analysis_results = self.pattern_detector.analyze_wallet(address, blockchain)
        
        # Calculate some statistics
        total_received = sum(tx['value'] for tx in transactions if tx['to_address'] == address)
        total_sent = sum(tx['value'] for tx in transactions if tx['from_address'] == address)
        current_balance = total_received - total_sent
        
        # Get most frequent counterparties
        counterparties = {}
        for tx in transactions:
            if tx['from_address'] == address:
                counterparty = tx['to_address']
            else:
                counterparty = tx['from_address']
                
            if counterparty in counterparties:
                counterparties[counterparty] += 1
            else:
                counterparties[counterparty] = 1
                
        top_counterparties = sorted(counterparties.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Compile report
        report = {
            'success': True,
            'wallet': {
                'address': address,
                'blockchain': blockchain,
                'total_received': total_received,
                'total_sent': total_sent,
                'current_balance': current_balance,
                'transaction_count': len(transactions)
            },
            'suspicious_score': max([score for _, score in analysis_results] if analysis_results else [0]),
            'high_risk_transactions': [tx_hash for tx_hash, score in analysis_results if score > 0.7],
            'top_counterparties': top_counterparties,
            'transaction_volume_over_time': self._get_transaction_volume_by_time(transactions)
        }
        
        return report
    
    def _get_transaction_volume_by_time(self, transactions):
        """Group transaction volumes by time periods."""
        # Sort transactions by timestamp
        sorted_txs = sorted(transactions, key=lambda x: x['timestamp'])
        
        # Group by month
        monthly_volumes = {}
        for tx in sorted_txs:
            month_key = tx['timestamp'].strftime('%Y-%m')
            if month_key in monthly_volumes:
                monthly_volumes[month_key] += tx['value']
            else:
                monthly_volumes[month_key] = tx['value']
                
        return [{'month': month, 'volume': volume} for month, volume in monthly_volumes.items()]

# Example usage
if __name__ == "__main__":
    # Create the tool
    tool = CryptoAnalysisTool()
    
    # Example: Analyze a Bitcoin transaction
    tx_hash = "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"  # Example hash
    result = tool.analyze_transaction(tx_hash, "bitcoin")
    
    # Print the result
    print(json.dumps(result, default=str, indent=2))
    
    # Example: Generate a wallet report
    address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"  # Example address
    wallet_report = tool.generate_wallet_report(address, "bitcoin")
    
    # Print the wallet report
    print(json.dumps(wallet_report, default=str, indent=2))