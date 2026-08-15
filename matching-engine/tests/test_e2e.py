import os
import pytest
from fastapi.testclient import TestClient
from api.main import app
from settlement.ledger import Ledger
import os

@pytest.fixture
def setup_test_env(tmp_path):
    # Set environment variables so the app uses temp databases
    os.environ["DB_DIR"] = str(tmp_path)
    
    # Pre-provision accounts in the ledger before starting the app
    ledger_path = tmp_path / "ledger.db"
    ledger = Ledger(str(ledger_path))
    ledger.create_account("alice", initial_cash=10000, initial_holdings={"BTCUSD": 0})
    ledger.create_account("bob", initial_cash=0, initial_holdings={"BTCUSD": 50})
    
    # We must use TestClient inside a with block so startup events run
    with TestClient(app) as client:
        yield client
        
    del os.environ["DB_DIR"]

def test_full_e2e_flow(setup_test_env):
    client = setup_test_env
    
    # 1. Bob places a sell order (5 BTC @ $100)
    resp1 = client.post("/api/orders", json={
        "account_id": "bob",
        "side": "sell",
        "symbol": "BTCUSD",
        "price": 100,
        "quantity": 5
    })
    assert resp1.status_code == 201
    assert resp1.json()["status"] == "accepted"
    assert len(resp1.json()["fills"]) == 0
    assert resp1.json()["remaining_quantity"] == 5
    
    # 2. Check Order Book Depth
    resp2 = client.get("/api/book/BTCUSD")
    assert resp2.status_code == 200
    book = resp2.json()
    assert len(book["asks"]) == 1
    assert book["asks"][0]["price"] == 100
    assert book["asks"][0]["total_quantity"] == 5
    assert len(book["bids"]) == 0
    
    # 3. Alice places a buy order (3 BTC @ $100) -> Matches!
    resp3 = client.post("/api/orders", json={
        "account_id": "alice",
        "side": "buy",
        "symbol": "BTCUSD",
        "price": 100,
        "quantity": 3
    })
    assert resp3.status_code == 201
    assert len(resp3.json()["fills"]) == 1
    assert resp3.json()["fills"][0]["quantity"] == 3
    assert resp3.json()["remaining_quantity"] == 0
    
    # 4. Check Trades Feed
    resp4 = client.get("/api/trades?symbol=BTCUSD")
    assert resp4.status_code == 200
    trades = resp4.json()["trades"]
    assert len(trades) == 1
    assert trades[0]["quantity"] == 3
    assert trades[0]["price"] == 100
    assert trades[0]["buyer_account_id"] == "alice"
    assert trades[0]["seller_account_id"] == "bob"
    
    # 5. Check Final Balances in Ledger
    # Alice spent 3 * 100 = $300. She should have $9700 and 3 BTC
    resp5 = client.get("/api/accounts/alice")
    assert resp5.status_code == 200
    alice_acc = resp5.json()
    assert alice_acc["cash_balance"] == 9700
    assert alice_acc["holdings"]["BTCUSD"] == 3
    
    # Bob earned $300, lost 3 BTC. He should have $300 and 47 BTC
    resp6 = client.get("/api/accounts/bob")
    assert resp6.status_code == 200
    bob_acc = resp6.json()
    assert bob_acc["cash_balance"] == 300
    assert bob_acc["holdings"]["BTCUSD"] == 47

def test_validation_insufficient_funds(setup_test_env):
    client = setup_test_env
    # Alice tries to buy 200 BTC @ $100 ($20,000), but only has $10,000
    resp = client.post("/api/orders", json={
        "account_id": "alice",
        "side": "buy",
        "symbol": "BTCUSD",
        "price": 100,
        "quantity": 200
    })
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "Insufficient funds"
