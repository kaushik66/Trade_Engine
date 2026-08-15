from typing import Dict, List
import dataclasses
from eventlog.log import EventLog
from engine.order_book import OrderBook
from engine.models import Order, Trade

class MatchingEngine:
    def __init__(self, event_log: EventLog):
        self.event_log = event_log
        self.order_books: Dict[str, OrderBook] = {}

    def get_book(self, symbol: str) -> OrderBook:
        if symbol not in self.order_books:
            self.order_books[symbol] = OrderBook(symbol)
        return self.order_books[symbol]

    def handle_order(self, order: Order) -> List[Trade]:
        """
        Coordinates the logging and matching of an order.
        1. Append order to event log.
        2. Process order in the matching engine.
        3. Append resulting trades to event log.
        Returns the generated trades.
        """
        # 1. Log the order
        self.event_log.append('order', dataclasses.asdict(order))
        
        # 2. Process order
        book = self.get_book(order.symbol)
        trades = book.process_order(order)
        
        # 3. Log trades
        for trade in trades:
            self.event_log.append('trade', dataclasses.asdict(trade))
            
        return trades

    def handle_cancel(self, symbol: str, order_id: str) -> bool:
        """
        Cancels a resting order and logs the cancellation event.
        (Note: the architecture spec doesn't explicitly define a 'cancel' event type in 8.3,
        but typically we'd log it. We'll leave it simple for now, since it wasn't requested
        to be logged strictly, or we can add it if we expand the spec later. For v1, let's
        assume we just cancel it in the book. Replay might get tricky if we don't log cancel.
        Wait, 8.5/8.2 says we cancel. If we replay, how does it know? We must log the cancel!)
        """
        book = self.get_book(symbol)
        success = book.cancel_order(order_id)
        if success:
            self.event_log.append('cancel', {'order_id': order_id, 'symbol': symbol})
        return success

    def restore_from_log(self):
        """
        Reconstructs the matching engine state entirely from the event log.
        """
        self.order_books.clear()
        
        for entry in self.event_log.read_all():
            if entry.type == 'order':
                order = Order(**entry.payload)
                book = self.get_book(order.symbol)
                # Apply order to the book, but IGNORE the returned trades 
                # because they are already deterministic and recorded in the log.
                book.process_order(order)
            elif entry.type == 'cancel':
                book = self.get_book(entry.payload['symbol'])
                book.cancel_order(entry.payload['order_id'])
            # Ignore 'trade' entries for book reconstruction since trades are outputs
