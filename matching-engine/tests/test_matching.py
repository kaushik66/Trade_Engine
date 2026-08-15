import pytest
from datetime import datetime, timezone
import uuid
import random
from engine.order_book import OrderBook
from engine.models import Order

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

def test_hand_crafted_scenario():
    """sell 10@100 resting, buy 5@100 arrives -> expect 1 trade for 5@100, resting sell reduced to 5"""
    book = OrderBook("BTCUSD")
    
    sell_order = make_order('sell', 100, 10, id="sell_1")
    trades1 = book.process_order(sell_order)
    assert len(trades1) == 0
    assert len(book.asks) == 1
    assert book.asks[100][0].remaining_quantity == 10
    
    buy_order = make_order('buy', 100, 5, id="buy_1")
    trades2 = book.process_order(buy_order)
    assert len(trades2) == 1
    assert trades2[0].price == 100
    assert trades2[0].quantity == 5
    assert trades2[0].buy_order_id == "buy_1"
    assert trades2[0].sell_order_id == "sell_1"
    
    assert book.asks[100][0].remaining_quantity == 5
    assert len(book.bids) == 0

def test_exact_match():
    book = OrderBook("BTCUSD")
    book.process_order(make_order('sell', 100, 10, id="s1"))
    trades = book.process_order(make_order('buy', 100, 10, id="b1"))
    
    assert len(trades) == 1
    assert trades[0].quantity == 10
    assert len(book.asks) == 0
    assert len(book.bids) == 0

def test_out_of_bounds_no_match():
    book = OrderBook("BTCUSD")
    book.process_order(make_order('sell', 100, 10))
    trades = book.process_order(make_order('buy', 99, 10)) # buy price < sell price
    
    assert len(trades) == 0
    assert len(book.asks) == 1
    assert len(book.bids) == 1

def test_sweeping_multiple_levels():
    book = OrderBook("BTCUSD")
    # Resting sells
    book.process_order(make_order('sell', 100, 5, id="s1"))
    book.process_order(make_order('sell', 101, 5, id="s2"))
    book.process_order(make_order('sell', 102, 5, id="s3"))
    
    # Large buy sweeps 100 and 101, partially fills 102
    trades = book.process_order(make_order('buy', 102, 12, id="b1"))
    
    assert len(trades) == 3
    assert trades[0].price == 100 and trades[0].quantity == 5
    assert trades[1].price == 101 and trades[1].quantity == 5
    assert trades[2].price == 102 and trades[2].quantity == 2
    
    assert len(book.asks) == 1
    assert book.asks[102][0].remaining_quantity == 3
    assert len(book.bids) == 0

def test_cancellation():
    book = OrderBook("BTCUSD")
    order = make_order('buy', 100, 10, id="b1")
    book.process_order(order)
    
    assert len(book.bids) == 1
    assert "b1" in book.order_index
    
    success = book.cancel_order("b1")
    assert success is True
    assert len(book.bids) == 0
    assert "b1" not in book.order_index
    
    success2 = book.cancel_order("b1")
    assert success2 is False

def test_invariant_conservation():
    """sum of filled quantities across trades == sum of matched quantities in book changes"""
    book = OrderBook("BTCUSD")
    orders = []
    # Generate random sequence of orders
    for i in range(100):
        side = random.choice(['buy', 'sell'])
        price = random.randint(90, 110)
        qty = random.randint(1, 10)
        orders.append(make_order(side, price, qty, id=f"o{i}"))
        
    total_input_qty = sum(o.quantity for o in orders)
    
    total_traded_qty = 0
    for o in orders:
        trades = book.process_order(o)
        total_traded_qty += sum(t.quantity for t in trades)
        
    # Since every trade involves 2 orders, the amount of quantity "removed" from input is 2 * traded_qty
    # The total resting quantity should be total_input_qty - 2 * total_traded_qty
    
    resting_qty = 0
    for price_level in book.bids.values():
        resting_qty += sum(ro.remaining_quantity for ro in price_level)
    for price_level in book.asks.values():
        resting_qty += sum(ro.remaining_quantity for ro in price_level)
        
    assert resting_qty == total_input_qty - 2 * total_traded_qty
