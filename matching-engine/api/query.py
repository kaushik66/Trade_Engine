import sqlite3
from fastapi import APIRouter, HTTPException, Request
from collections import defaultdict
from typing import List, Dict

router = APIRouter()

@router.get("/book/{symbol}")
def get_order_book(symbol: str, request: Request):
    engine = request.app.state.matching_engine
    if symbol not in engine.order_books:
        return {"symbol": symbol, "bids": [], "asks": []}
    
    book = engine.order_books[symbol]
    
    def aggregate_levels(book_side, limit=10):
        levels = []
        for price_key in book_side.keys()[:limit]:
            queue = book_side[price_key]
            price = queue[0].price
            total_qty = sum(order.remaining_quantity for order in queue)
            levels.append({"price": price, "total_quantity": total_qty})
        return levels

    return {
        "symbol": symbol,
        "bids": aggregate_levels(book.bids),
        "asks": aggregate_levels(book.asks)
    }

@router.get("/trades")
def get_trades(request: Request, symbol: str, limit: int = 50):
    event_log = request.app.state.event_log
    trades = []
    
    # Simple naive scan from the end; in a real DB we'd use ORDER BY id DESC LIMIT N
    all_events = list(event_log.read_all())
    for event in reversed(all_events):
        if event.type == 'trade':
            payload = event.payload
            if payload.get('symbol') == symbol:
                trades.append(payload)
                if len(trades) >= limit:
                    break
    return {"trades": trades}

@router.get("/accounts/{account_id}")
def get_account(account_id: str, request: Request):
    ledger = request.app.state.ledger
    try:
        account = ledger.get_account(account_id)
        return {
            "account_id": account.id,
            "cash_balance": account.cash_balance,
            "holdings": account.holdings,
            "version": account.version
        }
    except ValueError:
        raise HTTPException(status_code=404, detail="Account not found")
