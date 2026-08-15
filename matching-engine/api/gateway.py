from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal
import uuid
import dataclasses
from datetime import datetime, timezone
from engine.models import Order
from settlement.ledger import SettlementRetryExhausted

router = APIRouter()

ALLOWED_SYMBOLS = {"BTCUSD"}

class OrderRequest(BaseModel):
    account_id: str
    side: Literal["buy", "sell"]
    symbol: str
    price: int = Field(gt=0, description="Price must be strictly positive")
    quantity: int = Field(gt=0, description="Quantity must be strictly positive")

@router.post("/orders", status_code=201)
def submit_order(order_req: OrderRequest, request: Request):
    if order_req.symbol not in ALLOWED_SYMBOLS:
        raise HTTPException(status_code=400, detail={"error": f"Symbol {order_req.symbol} not allowed", "field": "symbol"})
        
    ledger = request.app.state.ledger
    engine = request.app.state.matching_engine
    
    # Validation against Query Layer (Ledger)
    try:
        account = ledger.get_account(order_req.account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail={"error": "Account not found", "field": "account_id"})
        
    if order_req.side == 'buy':
        required_cash = order_req.price * order_req.quantity
        if account.cash_balance < required_cash:
            raise HTTPException(status_code=400, detail={"error": "Insufficient funds", "field": "price_qty"})
    else:
        available_units = account.holdings.get(order_req.symbol, 0)
        if available_units < order_req.quantity:
            raise HTTPException(status_code=400, detail={"error": "Insufficient holdings", "field": "quantity"})
            
    # Forward to Matching Engine
    order_id = str(uuid.uuid4())
    order = Order(
        id=order_id,
        side=order_req.side,
        symbol=order_req.symbol,
        price=order_req.price,
        quantity=order_req.quantity,
        account_id=order_req.account_id,
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    
    trades = engine.handle_order(order)
    
    # Forward trades to Settlement
    for trade in trades:
        try:
            ledger.process_trade(trade, trade.buyer_account_id, trade.seller_account_id)
        except SettlementRetryExhausted as e:
            # Mark as failed in event log
            request.app.state.event_log.append('settlement_failed', {'trade_id': trade.trade_id, 'reason': str(e)})
            raise HTTPException(status_code=500, detail={"error": "Settlement retries exhausted", "component": "settlement"})
            
    # Compute remaining quantity (naive approximation for response, engine owns truth)
    filled_qty = sum(t.quantity for t in trades)
    remaining_qty = order.quantity - filled_qty
    
    return {
        "order_id": order.id,
        "status": "accepted",
        "fills": [dataclasses.asdict(t) for t in trades],
        "remaining_quantity": remaining_qty
    }

@router.delete("/orders/{order_id}")
def cancel_order(order_id: str, request: Request, symbol: str = "BTCUSD"):
    engine = request.app.state.matching_engine
    success = engine.handle_cancel(symbol, order_id)
    
    if success:
        return {"order_id": order_id, "status": "cancelled"}
    else:
        raise HTTPException(status_code=404, detail={"error": "order not found or already filled", "field": "order_id"})
