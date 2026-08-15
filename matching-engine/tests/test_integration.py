import os
import pytest
import uuid
from datetime import datetime, timezone
from eventlog.log import EventLog
from engine.models import Order
from engine.core import MatchingEngine

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "integration_event_log.db"
    yield str(db_path)
    if db_path.exists():
        os.remove(db_path)

def make_order(side, price, quantity, id=None):
    return Order(
        id=id or str(uuid.uuid4()),
        side=side,
        symbol="BTCUSD",
        price=price,
        quantity=quantity,
        account_id="acc1",
        timestamp=datetime.now(timezone.utc).isoformat()
    )

def test_wiring_order_and_trades(temp_db):
    event_log = EventLog(temp_db)
    engine = MatchingEngine(event_log)
    
    # Sell 10 @ 100
    engine.handle_order(make_order('sell', 100, 10, id="s1"))
    
    # Buy 5 @ 100 -> Should match
    engine.handle_order(make_order('buy', 100, 5, id="b1"))
    
    entries = list(event_log.read_all())
    
    # Expected sequence:
    # 1. order s1
    # 2. order b1
    # 3. trade (b1 matches with s1)
    
    assert len(entries) == 3
    assert entries[0].type == 'order'
    assert entries[0].payload['id'] == 's1'
    
    assert entries[1].type == 'order'
    assert entries[1].payload['id'] == 'b1'
    
    assert entries[2].type == 'trade'
    assert entries[2].payload['buy_order_id'] == 'b1'
    assert entries[2].payload['sell_order_id'] == 's1'
    assert entries[2].payload['quantity'] == 5

def test_replay_state_reconstruction(temp_db):
    event_log = EventLog(temp_db)
    engine = MatchingEngine(event_log)
    
    # Complex sequence
    engine.handle_order(make_order('sell', 100, 10, id="s1"))
    engine.handle_order(make_order('sell', 101, 10, id="s2"))
    engine.handle_order(make_order('buy', 100, 5, id="b1")) # Partial fill on s1
    engine.handle_cancel("BTCUSD", "s2")
    
    # Snapshot state
    book1 = engine.get_book("BTCUSD")
    bids1 = len(book1.bids)
    asks1 = len(book1.asks)
    s1_remaining = book1.asks[100][0].remaining_quantity
    
    assert asks1 == 1 # 101 was cancelled
    assert s1_remaining == 5
    
    # Initialize a completely new engine with the same DB
    engine2 = MatchingEngine(EventLog(temp_db))
    engine2.restore_from_log()
    
    book2 = engine2.get_book("BTCUSD")
    
    # Verify state is perfectly identical
    assert len(book2.bids) == bids1
    assert len(book2.asks) == asks1
    assert book2.asks[100][0].remaining_quantity == s1_remaining
    assert "s2" not in book2.order_index
    assert "s1" in book2.order_index
