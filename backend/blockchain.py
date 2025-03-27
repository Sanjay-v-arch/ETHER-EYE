import asyncio
import aiohttp
import websockets
import logging
import os
from typing import Dict, List, Callable
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BlockchainConnector:
    def __init__(self):
        self.api_keys = {
            "etherscan": os.getenv("ETHERSCAN_API_KEY", ""),
            "blockchair": os.getenv("BLOCKCHAIR_API_KEY", ""),
            "infura": os.getenv("INFURA_PROJECT_ID", "3b812a465e7748a18db963fb5d4ee14f"),
            "alchemy": os.getenv("ALCHEMY_API_KEY", "")
        }
        self.rate_limit_delay = 0.2
        self.retries = 5
        self.websocket_urls = {
            "ethereum": f"wss://eth-mainnet.g.alchemy.com/v2/{self.api_keys['alchemy'] or self.api_keys['infura']}",
            "solana": "wss://api.mainnet-beta.solana.com"
        }
        self.known_bridges = {"0x2fbb06f8": "Wormhole", "0x1116898d": "LayerZero"}
        self._seen_txs = set()

    async def _enforce_rate_limit(self):
        await asyncio.sleep(self.rate_limit_delay)

    async def get_transaction_data(self, session: aiohttp.ClientSession, tx_hash: str, chain: str) -> Dict:
        for attempt in range(self.retries):
            try:
                await self._enforce_rate_limit()
                if chain == "ethereum":
                    url = f"https://api.etherscan.io/api?module=proxy&action=eth_getTransactionByHash&txhash={tx_hash}&apikey={self.api_keys['etherscan']}"
                    async with session.get(url) as resp:
                        data = await resp.json()
                        result = data.get("result", {})
                        return {
                            "tx_hash": tx_hash,
                            "from_address": result.get("from", "").lower(),
                            "to_address": result.get("to", "").lower(),
                            "value": int(result.get("value", "0x0"), 16) / 10**18,
                            "timestamp": "N/A",
                            "block_number": int(result.get("blockNumber", "0x0"), 16),
                            "chain": chain
                        }
                elif chain == "bitcoin":
                    url = f"https://api.blockchair.com/bitcoin/dashboards/transaction/{tx_hash}?key={self.api_keys['blockchair']}"
                    async with session.get(url) as resp:
                        data = await resp.json()
                        if "data" not in data or tx_hash not in data["data"]:
                            return {}
                        tx = data["data"][tx_hash]["transaction"]
                        return {
                            "tx_hash": tx_hash,
                            "from_address": tx["inputs"][0]["recipient"] if tx["inputs"] else "N/A",
                            "to_address": tx["outputs"][0]["recipient"] if tx["outputs"] else "N/A",
                            "value": tx["output_total"] / 10**8,
                            "timestamp": tx["time"],
                            "block_number": tx["block_id"],
                            "chain": chain
                        }
                elif chain == "solana":
                    url = "https://api.mainnet-beta.solana.com"
                    payload = {"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [tx_hash, "json"]}
                    async with session.post(url, json=payload) as resp:
                        data = await resp.json()
                        if "result" not in data:
                            return {}
                        tx = data["result"]
                        return {
                            "tx_hash": tx_hash,
                            "from_address": tx["transaction"]["message"]["accountKeys"][0],
                            "to_address": tx["transaction"]["message"]["accountKeys"][1],
                            "value": (tx["meta"]["postBalances"][1] - tx["meta"]["preBalances"][1]) / 10**9,
                            "timestamp": tx["blockTime"],
                            "block_number": tx["slot"],
                            "chain": chain
                        }
            except Exception as e:
                logger.error(f"Error fetching tx {tx_hash} on {chain}: {str(e)}")
                if attempt == self.retries - 1:
                    return {}
                await asyncio.sleep(2 ** attempt)
        return {}

    async def get_wallet_history(self, session: aiohttp.ClientSession, address: str, chain: str, limit: int = 10) -> List[Dict]:
        await self._enforce_rate_limit()
        transactions = []
        try:
            if chain == "ethereum":
                url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&sort=desc&apikey={self.api_keys['etherscan']}&offset={limit}"
                async with session.get(url) as resp:
                    data = await resp.json()
                    if data["status"] != "1":
                        logger.info(f"No data for {address} on {chain}: {data.get('message')}")
                        return []
                    for tx in data["result"][:limit]:
                        transactions.append({
                            "tx_hash": tx["hash"],
                            "from_address": tx["from"].lower(),
                            "to_address": tx["to"].lower(),
                            "value": int(tx["value"]) / 10**18,
                            "timestamp": tx["timeStamp"],
                            "block_number": int(tx["blockNumber"]),
                            "chain": chain
                        })
            elif chain == "bitcoin":
                url = f"https://api.blockchair.com/bitcoin/dashboards/address/{address}?limit={limit}&key={self.api_keys['blockchair']}"
                async with session.get(url) as resp:
                    data = await resp.json()
                    if "data" not in data or address not in data["data"]:
                        logger.info(f"No data for {address} on {chain}")
                        return []
                    txs = data["data"][address].get("transactions", [])
                    for tx_hash in txs[:limit]:
                        tx_data = await self.get_transaction_data(session, tx_hash, chain)
                        if tx_data:
                            transactions.append(tx_data)
            elif chain == "solana":
                url = "https://api.mainnet-beta.solana.com"
                payload = {"jsonrpc": "2.0", "id": 1, "method": "getConfirmedSignaturesForAddress2", "params": [address, {"limit": limit}]}
                async with session.post(url, json=payload) as resp:
                    data = await resp.json()
                    if "result" not in data:
                        logger.info(f"No data for {address} on {chain}")
                        return []
                    for sig in data["result"]:
                        tx_data = await self.get_transaction_data(session, sig["signature"], chain)
                        if tx_data:
                            transactions.append(tx_data)
        except Exception as e:
            logger.error(f"Error fetching history for {address} on {chain}: {str(e)}")
        return transactions

    async def stream_transactions(self, address: str, chain: str, callback: Callable[[Dict], None]):
        async with aiohttp.ClientSession() as session:
            if chain in self.websocket_urls and self.api_keys["alchemy"]:
                try:
                    async with websockets.connect(self.websocket_urls[chain]) as ws:
                        if chain == "ethereum":
                            await ws.send('{"jsonrpc":"2.0","id":1,"method":"eth_subscribe","params":["newPendingTransactions"]}')
                        while True:
                            msg = await ws.recv()
                            import json
                            data = json.loads(msg)
                            tx_hash = data.get("params", {}).get("result", "").strip('"')
                            if tx_hash:
                                tx_data = await self.get_transaction_data(session, tx_hash, chain)
                                if tx_data and (tx_data["from_address"] == address.lower() or tx_data["to_address"] == address.lower()):
                                    await callback(tx_data)
                except Exception as e:
                    logger.error(f"WebSocket error for {chain}: {str(e)}")
            while True:
                txs = await self.get_wallet_history(session, address, chain, limit=1)
                if txs and txs[0]["tx_hash"] not in self._seen_txs:
                    self._seen_txs.add(txs[0]["tx_hash"])
                    await callback(txs[0])
                await asyncio.sleep(5)

    async def detect_cross_chain(self, tx: Dict) -> bool:
        try:
            to_address = tx.get("to_address", "").lower()
            return any(bridge in to_address for bridge in self.known_bridges)
        except Exception as e:
            logger.error(f"Cross-chain detection error for {tx.get('tx_hash', 'unknown')}: {str(e)}")
            return False

connector = BlockchainConnector()

if __name__ == "__main__":
    async def test_callback(tx: Dict):
        logger.info(f"New tx: {tx['tx_hash']}")
    asyncio.run(connector.stream_transactions("0x28c6c06298d514db089934071355e5743bf21d60", "ethereum", test_callback))