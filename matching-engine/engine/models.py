from dataclasses import dataclass
from typing import Literal

@dataclass
class Order:
    """Incoming order from Gateway"""
    id: str
    side: Literal['buy', 'sell']
    symbol: str
    price: int
    quantity: int
    account_id: str
    timestamp: str

@dataclass
class RestingOrder:
    """Order resting in the order book"""
    id: str
    side: Literal['buy', 'sell']
    price: int
    remaining_quantity: int
    timestamp: str

@dataclass
class Trade:
    """Emitted when two orders match"""
    trade_id: str
    symbol: str
    price: int
    quantity: int
    buy_order_id: str
    sell_order_id: str
    timestamp: str
