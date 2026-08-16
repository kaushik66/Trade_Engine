import asyncio
import httpx
import time
from settlement.ledger import Ledger
from engine.core import MatchingEngine
from eventlog.log import EventLog
import uuid
import os

# Create local databases for the load test to isolate from dev environment
DB_DIR = "load_test_dbs"
os.makedirs(DB_DIR, exist_ok=True)
EVENT_LOG_PATH = os.path.join(DB_DIR, "event_log.db")
LEDGER_PATH = os.path.join(DB_DIR, "ledger.db")
os.environ["DB_DIR"] = DB_DIR

# 1. Setup DB state
if os.path.exists(EVENT_LOG_PATH): os.remove(EVENT_LOG_PATH)
if os.path.exists(LEDGER_PATH): os.remove(LEDGER_PATH)

ledger = Ledger(LEDGER_PATH)
ledger.create_account("buyer", initial_cash=1000000000)
ledger.create_account("seller", initial_cash=0, initial_holdings={"BTCUSD": 1000000})

API_URL = "http://127.0.0.1:8000/api/orders"
CONCURRENCY = 50
TOTAL_ORDERS = 1000

async def submit_order(client, side, price, qty, account_id):
    payload = {
        "account_id": account_id,
        "side": side,
        "symbol": "BTCUSD",
        "price": price,
        "quantity": qty
    }
    response = await client.post(API_URL, json=payload)
    return response.status_code

async def worker(client, queue):
    while True:
        try:
            task = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        await submit_order(client, *task)
        queue.task_done()

async def main():
    print(f"Starting Load Test: {TOTAL_ORDERS} orders at {CONCURRENCY} concurrency.")
    queue = asyncio.Queue()
    
    # Pre-fill queue with alternating buy/sell orders that will instantly match
    for _ in range(TOTAL_ORDERS // 2):
        # Buyer places aggressive bid
        queue.put_nowait(("buy", 100, 1, "buyer"))
        # Seller places matching ask
        queue.put_nowait(("sell", 100, 1, "seller"))

    start_time = time.time()
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = []
        for _ in range(CONCURRENCY):
            task = asyncio.create_task(worker(client, queue))
            tasks.append(task)
            
        await asyncio.gather(*tasks)
        
    duration = time.time() - start_time
    throughput = TOTAL_ORDERS / duration
    
    print("-" * 30)
    print("Load Test Complete")
    print(f"Duration:   {duration:.2f} seconds")
    print(f"Throughput: {throughput:.2f} orders/sec")
    print("-" * 30)

if __name__ == "__main__":
    asyncio.run(main())
