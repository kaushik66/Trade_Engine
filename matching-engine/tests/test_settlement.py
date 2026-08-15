import os
import pytest
from datetime import datetime, timezone
from settlement.ledger import Ledger
from engine.models import Trade

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_ledger.db"
    yield str(db_path)
    if db_path.exists():
        os.remove(db_path)

def test_sequential_settlement(temp_db):
    ledger = Ledger(temp_db)
    
    # Initialize accounts
    ledger.create_account("buyer1", initial_cash=10000, initial_holdings={"BTCUSD": 0})
    ledger.create_account("seller1", initial_cash=0, initial_holdings={"BTCUSD": 50})
    
    # Process a sequential stream of trades
    trades = [
        Trade(trade_id="t1", symbol="BTCUSD", price=100, quantity=10, buy_order_id="b1", sell_order_id="s1", timestamp=datetime.now(timezone.utc).isoformat()),
        Trade(trade_id="t2", symbol="BTCUSD", price=105, quantity=20, buy_order_id="b2", sell_order_id="s2", timestamp=datetime.now(timezone.utc).isoformat()),
    ]
    
    for t in trades:
        ledger.process_trade(t, "buyer1", "seller1")
        
    # Verify final balances
    # Buyer spent: 100*10 + 105*20 = 1000 + 2100 = 3100. Remaining: 10000 - 3100 = 6900
    # Buyer got: 10 + 20 = 30 BTCUSD
    buyer = ledger.get_account("buyer1")
    assert buyer.cash_balance == 6900
    assert buyer.holdings["BTCUSD"] == 30
    
    # Seller earned: 3100. Remaining: 0 + 3100 = 3100
    # Seller spent: 30 BTCUSD. Remaining: 50 - 30 = 20
    seller = ledger.get_account("seller1")
    assert seller.cash_balance == 3100
    assert seller.holdings["BTCUSD"] == 20

def test_insufficient_funds_rejected(temp_db):
    ledger = Ledger(temp_db)
    ledger.create_account("buyer1", initial_cash=500, initial_holdings={"BTCUSD": 0})
    ledger.create_account("seller1", initial_cash=0, initial_holdings={"BTCUSD": 50})
    
    trade = Trade(trade_id="t1", symbol="BTCUSD", price=100, quantity=10, buy_order_id="b1", sell_order_id="s1", timestamp=datetime.now(timezone.utc).isoformat())
    
    # 100 * 10 = 1000, which is > 500
    with pytest.raises(ValueError, match="Buyer has insufficient funds"):
        ledger.process_trade(trade, "buyer1", "seller1")
