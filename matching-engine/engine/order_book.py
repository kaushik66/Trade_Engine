import collections
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from sortedcontainers import SortedDict
from .models import Order, RestingOrder, Trade

class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        # Bids: sorted descending by price. We use -price as the key to achieve this with SortedDict
        self.bids = SortedDict() 
        # Asks: sorted ascending by price.
        self.asks = SortedDict()
        
        # order_id -> (side, price) for O(1) cancel lookup
        self.order_index: Dict[str, Tuple[str, int]] = {}

    def process_order(self, order: Order) -> List[Trade]:
        """
        Process an incoming order. Matches against resting orders if possible.
        Any remaining quantity is added to the book.
        Returns a list of executed Trades.
        """
        trades = []
        remaining_qty = order.quantity
        
        # Determine opposing book and match condition
        if order.side == 'buy':
            opposing_book = self.asks
            # match if buy price >= lowest ask price
            def crosses(resting_price): return order.price >= resting_price
        else: # 'sell'
            opposing_book = self.bids
            # match if sell price <= highest bid price. Note: bids keys are negated (-price)
            def crosses(resting_price_key): return order.price <= -resting_price_key
            
        # Match loop
        while remaining_qty > 0 and opposing_book:
            # Peek at the best opposing price level (first item in SortedDict)
            best_price_key = opposing_book.peekitem(0)[0]
            if not crosses(best_price_key):
                break # No match possible
                
            level_queue = opposing_book[best_price_key]
            if not level_queue:
                # Should not happen if we clean up properly, but just in case
                del opposing_book[best_price_key]
                continue
                
            oldest_resting = level_queue[0]
            match_price = oldest_resting.price
            
            trade_qty = min(remaining_qty, oldest_resting.remaining_quantity)
            
            # Create trade
            now_ts = datetime.now(timezone.utc).isoformat()
            if order.side == 'buy':
                buy_id = order.id
                sell_id = oldest_resting.id
            else:
                buy_id = oldest_resting.id
                sell_id = order.id
                
            import uuid
            trades.append(Trade(
                trade_id=str(uuid.uuid4()),
                symbol=self.symbol,
                price=match_price,
                quantity=trade_qty,
                buy_order_id=buy_id,
                sell_order_id=sell_id,
                timestamp=now_ts
            ))
            
            # Decrement quantities
            remaining_qty -= trade_qty
            oldest_resting.remaining_quantity -= trade_qty
            
            # Clean up resting order if fully filled
            if oldest_resting.remaining_quantity == 0:
                level_queue.popleft()
                del self.order_index[oldest_resting.id]
                if not level_queue:
                    del opposing_book[best_price_key]
                    
        # Add to book if there is remaining quantity
        if remaining_qty > 0:
            resting = RestingOrder(
                id=order.id,
                side=order.side,
                price=order.price,
                remaining_quantity=remaining_qty,
                timestamp=order.timestamp
            )
            
            if order.side == 'buy':
                key = -order.price
                target_book = self.bids
            else:
                key = order.price
                target_book = self.asks
                
            if key not in target_book:
                target_book[key] = collections.deque()
            target_book[key].append(resting)
            self.order_index[order.id] = (order.side, order.price)
            
        return trades

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancels a resting order by ID.
        Returns True if cancelled, False if not found.
        """
        if order_id not in self.order_index:
            return False
            
        side, price = self.order_index[order_id]
        
        if side == 'buy':
            key = -price
            target_book = self.bids
        else:
            key = price
            target_book = self.asks
            
        if key not in target_book:
            # Inconsistent state, but handle gracefully
            del self.order_index[order_id]
            return False
            
        level_queue = target_book[key]
        
        # O(N) removal within the deque, but N is usually small (orders at same price level)
        for i, order in enumerate(level_queue):
            if order.id == order_id:
                del level_queue[i]
                del self.order_index[order_id]
                
                if not level_queue:
                    del target_book[key]
                return True
                
        return False
