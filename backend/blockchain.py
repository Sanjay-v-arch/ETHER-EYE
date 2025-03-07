# backend/blockchain.py
import asyncio
import aiohttp
import websockets
import logging
import os
from typing import Dict, List, Optional, Callable
from web3 import Web3
from dotenv import load_dotenv
from aiohttp_socks import ProxyConnector

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class BlockchainConnector:
    """High-performance blockchain connectivity for transaction data and streaming."""
    def __init__(self):
        self.api_keys = {
            "etherscan": os.getenv("ETHERSCAN_API_KEY"),
            "alchemy": os.getenv("ALCHEMY_API_KEY"),
            "moralis": os.getenv("MORALIS_API_KEY"),
            "bitquery": os.getenv("BITQUERY_API_KEY"),
            "infura": os.getenv("INFURA_PROJECT_ID", "3b812a46af704e079db03728ba30b023")
        }
        self.rpc_urls = {
            "ethereum": f"https://mainnet.infura.io/v3/{self.api_keys['infura']}",
            "bsc": "https://bsc-dataseed.binance.org/",
            "polygon": "https://polygon-rpc.com/",
        }
        self.websocket_urls = {
            "ethereum": f"wss://eth-mainnet.g.alchemy.com/v2/{self.api_keys['alchemy']}",
            "bitcoin": "wss://api.amberdata.io/v2/websocket",  # Mocked if no key
            "solana": "wss://api.mainnet-beta.solana.com"
        }
        self.web3_clients = {
            "ethereum": Web3(Web3.HTTPProvider(self.rpc_urls["ethereum"])),
            "bsc": Web3(Web3.HTTPProvider(self.rpc_urls["bsc"])),
            "polygon": Web3(Web3.HTTPProvider(self.rpc_urls["polygon"]))
        }
        self.max_retries = 5
        self.rate_limit_delay = 15
        self.erc20_abi = [
            {"anonymous": False, "inputs": [{"indexed": True, "name": "from", "type": "address"}, {"indexed": True, "name": "to", "type": "address"}, {"indexed": False, "name": "value", "type": "uint256"}], "name": "Transfer", "type": "event"}
        ]
        self.known_bridges = ["0x2fbb06f838e4b5cf28c7e5e52b0028cbedcf277f", "0x1116898dda4015ed8ddefb84b6e8bc24528af2d8"]  # Example bridge addresses

    def validate_address(self, address: str, chain: str) -> bool:
        """Validate address format across multiple chains."""
        try:
            if chain in ["ethereum", "bsc", "polygon"]:
                return Web3.is_address(address) and Web3.is_checksum_address(address)
            elif chain == "bitcoin":
                return len(address) > 25 and address[0] in "13bc"
            elif chain == "solana":
                return len(address) == 44 and address.isalnum()
            elif chain == "cardano":
                return address.startswith("addr1") and len(address) > 50
            elif chain == "ton":
                return len(address) == 48 and address.isalnum()
            return False
        except Exception as e:
            logger.error(f"Address validation error for {address} on {chain}: {e}")
            return False

    async def get_transaction_data(self, session: aiohttp.ClientSession, tx_hash: str, chain: str) -> Optional[Dict]:
        """Retrieve transaction data across multiple chains with retries."""
        if chain not in ["ethereum", "bitcoin", "solana", "bsc", "polygon", "cardano", "ton"]:
            logger.error(f"Unsupported chain: {chain}")
            return None

        retry_count = 0
        while retry_count < self.max_retries:
            try:
                if chain in self.web3_clients and self.web3_clients[chain].is_connected():
                    tx = self.web3_clients[chain].eth.get_transaction(tx_hash)
                    block = self.web3_clients[chain].eth.get_block(tx["blockNumber"])
                    receipt = self.web3_clients[chain].eth.get_transaction_receipt(tx_hash)
                    token = None
                    for log in receipt.logs:
                        contract = self.web3_clients[chain].eth.contract(address=log.address, abi=self.erc20_abi)
                        event = contract.events.Transfer().process_log(log)
                        if event:
                            token = {"symbol": log.address, "value": event["args"]["value"]}
                            break
                    return {
                        "tx_hash": tx_hash,
                        "from_address": tx["from"].lower(),
                        "to_address": tx["to"].lower() if tx["to"] else None,
                        "value": tx["value"] if not token else token["value"],
                        "timestamp": block["timestamp"],
                        "block_number": tx["blockNumber"],
                        "token": token,
                        "chain": chain
                    }
                elif chain == "bitcoin":
                    async with session.get(f"https://api.blockchair.com/bitcoin/dashboards/transaction/{tx_hash}?key={self.api_keys.get('blockchair', '')}") as resp:
                        data = await resp.json()
                        if "data" in data:
                            tx = data["data"][tx_hash]["transaction"]
                            return {
                                "tx_hash": tx_hash,
                                "from_address": tx["inputs"][0]["recipient"] if tx["inputs"] else "unknown",
                                "to_address": tx["outputs"][0]["recipient"] if tx["outputs"] else "unknown",
                                "value": tx["output_total"],
                                "timestamp": tx["time"],
                                "block_number": tx["block_id"],
                                "token": None,
                                "chain": chain
                            }
                elif chain == "solana":
                    async with session.post("https://api.mainnet-beta.solana.com", json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [tx_hash, "json"]}) as resp:
                        data = await resp.json()
                        if "result" in data:
                            tx = data["result"]
                            return {
                                "tx_hash": tx_hash,
                                "from_address": tx["transaction"]["message"]["accountKeys"][0],
                                "to_address": tx["transaction"]["message"]["accountKeys"][1],
                                "value": tx["meta"]["postBalances"][1] - tx["meta"]["preBalances"][1],
                                "timestamp": tx["blockTime"],
                                "block_number": tx["slot"],
                                "token": {"symbol": "SPL", "value": tx["meta"]["postTokenBalances"][0]["uiTokenAmount"]["amount"]} if tx["meta"]["postTokenBalances"] else None,
                                "chain": chain
                            }
                # Fallback to Moralis for other chains
                async with session.get(f"https://deep-index.moralis.io/api/v2/transaction/{tx_hash}?chain={chain}", headers={"X-API-Key": self.api_keys["moralis"]}) as resp:
                    data = await resp.json()
                    if "hash" in data:
                        return {
                            "tx_hash": tx_hash,
                            "from_address": data["from_address"],
                            "to_address": data["to_address"],
                            "value": float(data["value"]) / (10**18 if chain in ["ethereum", "bsc", "polygon"] else 1),
                            "timestamp": data["block_timestamp"],
                            "block_number": int(data["block_number"]),
                            "token": {"symbol": data["to_address"], "value": float(data["value"])} if data["to_address"] in self.known_bridges else None,
                            "chain": chain
                        }
            except Exception as e:
                logger.error(f"Error fetching tx {tx_hash} on {chain}: {e}")
                retry_count += 1
                await asyncio.sleep(self.rate_limit_delay * (retry_count + 1))
        logger.error(f"Max retries exceeded for tx {tx_hash} on {chain}")
        return None

    async def get_wallet_history(self, session: aiohttp.ClientSession, address: str, chain: str, limit: int = 10) -> List[Dict]:
        """Fetch wallet transaction history across chains."""
        if not self.validate_address(address, chain):
            logger.error(f"Invalid address: {address} for {chain}")
            return []

        transactions = []
        try:
            if chain == "ethereum":
                async with session.get(f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&sort=desc&apikey={self.api_keys['etherscan']}&page=1&offset={limit}") as resp:
                    data = await resp.json()
                    if data["status"] == "1":
                        transactions.extend([{
                            "tx_hash": tx["hash"],
                            "from_address": tx["from"].lower(),
                            "to_address": tx["to"].lower(),
                            "value": float(tx["value"]) / 10**18,
                            "timestamp": tx["timeStamp"],
                            "block_number": int(tx["blockNumber"]),
                            "token": {"symbol": tx["contractAddress"], "value": float(tx["value"]) / 10**18} if tx["contractAddress"] else None,
                            "chain": chain
                        } for tx in data["result"]])
            elif chain == "bitcoin":
                async with session.get(f"https://api.blockchair.com/bitcoin/dashboards/address/{address}?limit={limit}&key={self.api_keys.get('blockchair', '')}") as resp:
                    data = await resp.json()
                    if "data" in data:
                        txs = data["data"][address]["transactions"]
                        for tx_hash in txs[:limit]:
                            tx_data = await self.get_transaction_data(session, tx_hash, chain)
                            if tx_data:
                                transactions.append(tx_data)
            elif chain == "solana":
                async with session.post("https://api.mainnet-beta.solana.com", json={"jsonrpc": "2.0", "id": 1, "method": "getConfirmedSignaturesForAddress2", "params": [address, {"limit": limit}]}) as resp:
                    data = await resp.json()
                    if "result" in data:
                        for sig in data["result"]:
                            tx_data = await self.get_transaction_data(session, sig["signature"], chain)
                            if tx_data:
                                transactions.append(tx_data)
            # Fallback to Bitquery for other chains
            else:
                query = {"query": f"{{ blockchain {{ transactions(address: \"{address}\", first: {limit}) {{ hash from to amount currency {{ symbol }} block {{ timestamp {{ unixtime }} number }} }} }} }}"}
                async with session.post("https://graphql.bitquery.io/", json=query, headers={"X-API-KEY": self.api_keys["bitquery"]}) as resp:
                    data = await resp.json()
                    transactions.extend([{
                        "tx_hash": tx["hash"],
                        "from_address": tx["from"],
                        "to_address": tx["to"],
                        "value": float(tx["amount"]),
                        "timestamp": tx["block"]["timestamp"]["unixtime"],
                        "block_number": tx["block"]["number"],
                        "token": {"symbol": tx["currency"]["symbol"], "value": float(tx["amount"])} if tx["currency"]["symbol"] != chain.upper() else None,
                        "chain": chain
                    } for tx in data.get("data", {}).get("blockchain", {}).get("transactions", [])])
            return transactions
        except Exception as e:
            logger.error(f"Error fetching wallet history for {address} on {chain}: {e}")
            return []

    async def stream_transactions(self, address: str, chain: str, callback: Callable[[Dict], None]):
        """Stream real-time transactions across chains."""
        if not self.validate_address(address, chain):
            logger.error(f"Invalid address: {address} for {chain}")
            return

        async with aiohttp.ClientSession(connector=ProxyConnector.from_url("socks5://127.0.0.1:9050")) as session:
            if chain in self.websocket_urls:
                async with websockets.connect(self.websocket_urls[chain]) as ws:
                    if chain == "ethereum":
                        await ws.send('{"jsonrpc":"2.0","id":1,"method":"eth_subscribe","params":["newPendingTransactions"]}')
                    elif chain == "bitcoin":
                        await ws.send('{"method":"subscribe","params":{"type":"transactions"}}')  # AmberData format
                    elif chain == "solana":
                        await ws.send('{"jsonrpc":"2.0","id":1,"method":"signatureSubscribe","params":["all"]}')

                    while True:
                        try:
                            msg = await ws.recv()
                            tx_hash = self._parse_websocket_msg(msg, chain)
                            if tx_hash:
                                tx_data = await self.get_transaction_data(session, tx_hash, chain)
                                if tx_data and (tx_data["from_address"] == address.lower() or tx_data["to_address"] == address.lower()):
                                    await callback(tx_data)
                        except Exception as e:
                            logger.error(f"Streaming error for {address} on {chain}: {e}")
                            await asyncio.sleep(5)
            else:
                # Fallback to polling for unsupported chains
                while True:
                    history = await self.get_wallet_history(session, address, chain, limit=1)
                    if history and history[0]["tx_hash"] not in self._seen_txs:
                        self._seen_txs.add(history[0]["tx_hash"])
                        await callback(history[0])
                    await asyncio.sleep(15)

    def _parse_websocket_msg(self, msg: str, chain: str) -> Optional[str]:
        """Parse WebSocket messages to extract transaction hashes."""
        import json
        try:
            data = json.loads(msg)
            if chain == "ethereum":
                return data.get("params", {}).get("result")
            elif chain == "bitcoin":
                return data.get("data", {}).get("hash")
            elif chain == "solana":
                return data.get("params", {}).get("result", {}).get("signature")
            return None
        except Exception:
            return None

    async def detect_cross_chain(self, tx: Dict) -> bool:
        """Detect if a transaction involves cross-chain activity."""
        to_address = tx["to_address"] or ""
        return any(bridge in to_address.lower() for bridge in self.known_bridges) or "bridge" in to_address.lower()

if __name__ == "__main__":
    connector = BlockchainConnector()
    async def test():
        async with aiohttp.ClientSession() as session:
            tx = await connector.get_transaction_data(session, "0x4e3a3754410177e6937ef1d0084000883f919978", "ethereum")
            print(tx)
            history = await connector.get_wallet_history(session, "0x28c6c06298d514db089934071355e5743bf21d60", "ethereum")
            print(f"History: {len(history)} transactions")
    asyncio.run(test())