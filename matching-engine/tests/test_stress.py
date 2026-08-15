import os
import pytest
import concurrent.futures
from datetime import datetime, timezone
from settlement.ledger import Ledger
from engine.models import Trade

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "stress_ledger_occ.db"
    yield str(db_path)
    if db_path.exists():
        os.remove(db_path)

def test_stress_harness_occ_zero_corruption(temp_db):
    """
    Spins up N threads to concurrently hit the OCC Ledger.
    We EXPECT the final balance to perfectly match the sequential expected balance.
    Runs 3 times to prove reliability per Architecture.md.
    """
    ledger = Ledger(temp_db)
    
    num_threads = 50
    trade_price = 100
    trade_qty = 1
    total_cost_per_trade = trade_price * trade_qty
    initial_cash = num_threads * total_cost_per_trade * 10 # plenty of cash
    
    ledger.create_account("stress_buyer", initial_cash=initial_cash, initial_holdings={"BTCUSD": 0})
    ledger.create_account("stress_seller", initial_cash=0, initial_holdings={"BTCUSD": num_threads * trade_qty * 10})
    
    for run_idx in range(3):
        # 1. Fire concurrent trades
        def execute_trade(t_id):
            trade = Trade(
                trade_id=f"stress_t_{run_idx}_{t_id}",
                symbol="BTCUSD",
                price=trade_price, 
                quantity=trade_qty, 
                buy_order_id="b", 
                sell_order_id="s", 
                timestamp=datetime.now(timezone.utc).isoformat()
            )
            # Increase max_retries for heavy sqlite concurrency to avoid spurious failures
            ledger.process_trade(trade, "stress_buyer", "stress_seller", max_retries=50)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(execute_trade, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)
            
            # Verify if any exceptions were thrown
            for f in futures:
                exc = f.exception()
                if exc is not None:
                    raise exc # If any thread exhausted retries, fail the test
                    
        # 3. Assert zero corruption
        # Expected sequential balance for buyer
        trades_executed_so_far = num_threads * (run_idx + 1)
        expected_buyer_cash = initial_cash - (trades_executed_so_far * total_cost_per_trade)
        expected_seller_cash = trades_executed_so_far * total_cost_per_trade
        
        buyer = ledger.get_account("stress_buyer")
        seller = ledger.get_account("stress_seller")
        
        # We EXPECT a perfect match because OCC prevents the Lost Update anomaly.
        assert buyer.cash_balance == expected_buyer_cash, f"Run {run_idx}: Buyer balance corrupted! Expected {expected_buyer_cash}, got {buyer.cash_balance}"
        assert seller.cash_balance == expected_seller_cash, f"Run {run_idx}: Seller balance corrupted! Expected {expected_seller_cash}, got {seller.cash_balance}"
