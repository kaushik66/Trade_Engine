import sqlite3
import json
from dataclasses import dataclass
from typing import Dict
from engine.models import Trade

class SettlementRetryExhausted(Exception):
    """Raised when OCC retries exceed the maximum limit."""
    pass

@dataclass
class Account:
    id: str
    version: int
    cash_balance: int
    holdings: Dict[str, int]

class Ledger:
    def __init__(self, db_path: str = "ledger.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL DEFAULT 1,
                    cash_balance INTEGER NOT NULL,
                    holdings TEXT NOT NULL
                )
            ''')

    def create_account(self, account_id: str, initial_cash: int = 0, initial_holdings: Dict[str, int] = None):
        """Helper to create an account."""
        holdings = initial_holdings or {}
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'INSERT INTO accounts (id, version, cash_balance, holdings) VALUES (?, ?, ?, ?)',
                (account_id, 1, initial_cash, json.dumps(holdings))
            )

    def get_account(self, account_id: str) -> Account:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                'SELECT id, version, cash_balance, holdings FROM accounts WHERE id = ?',
                (account_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Account {account_id} not found")
            return Account(
                id=row[0],
                version=row[1],
                cash_balance=row[2],
                holdings=json.loads(row[3])
            )

    def get_account_from_conn(self, conn: sqlite3.Connection, account_id: str) -> Account:
        """Fetch account using an existing connection."""
        cursor = conn.execute(
            'SELECT id, version, cash_balance, holdings FROM accounts WHERE id = ?',
            (account_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Account {account_id} not found")
        return Account(
            id=row[0],
            version=row[1],
            cash_balance=row[2],
            holdings=json.loads(row[3])
        )

    def process_trade(self, trade: Trade, buyer_account_id: str, seller_account_id: str, max_retries: int = 5):
        """
        Optimistic Concurrency Control (OCC) implementation.
        Requires `version` to match during UPDATE, retries on failure.
        """
        total_value = trade.price * trade.quantity

        for attempt in range(max_retries):
            # We manage transactions manually because we need to rollback and retry
            # if we encounter a version mismatch.
            conn = sqlite3.connect(self.db_path, isolation_level=None)
            try:
                conn.execute('BEGIN')
                
                # 1. READ
                buyer = self.get_account_from_conn(conn, buyer_account_id)
                seller = self.get_account_from_conn(conn, seller_account_id)

                # 2. COMPUTE
                new_buyer_cash = buyer.cash_balance - total_value
                new_seller_cash = seller.cash_balance + total_value

                if new_buyer_cash < 0:
                    raise ValueError("Buyer has insufficient funds")

                buyer_symbol_qty = buyer.holdings.get(trade.symbol, 0) + trade.quantity
                seller_symbol_qty = seller.holdings.get(trade.symbol, 0) - trade.quantity

                if seller_symbol_qty < 0:
                    raise ValueError("Seller has insufficient holdings")

                new_buyer_holdings = dict(buyer.holdings)
                new_buyer_holdings[trade.symbol] = buyer_symbol_qty

                new_seller_holdings = dict(seller.holdings)
                new_seller_holdings[trade.symbol] = seller_symbol_qty

                # 3. WRITE with OCC (Version check)
                cursor = conn.execute(
                    'UPDATE accounts SET cash_balance = ?, holdings = ?, version = version + 1 WHERE id = ? AND version = ?',
                    (new_buyer_cash, json.dumps(new_buyer_holdings), buyer.id, buyer.version)
                )
                if cursor.rowcount == 0:
                    # Version mismatch on buyer, concurrent update occurred
                    conn.execute('ROLLBACK')
                    continue
                
                cursor = conn.execute(
                    'UPDATE accounts SET cash_balance = ?, holdings = ?, version = version + 1 WHERE id = ? AND version = ?',
                    (new_seller_cash, json.dumps(new_seller_holdings), seller.id, seller.version)
                )
                if cursor.rowcount == 0:
                    # Version mismatch on seller, concurrent update occurred
                    conn.execute('ROLLBACK')
                    continue

                # Both updates succeeded with correct versions!
                conn.execute('COMMIT')
                return # Success! Exit the retry loop

            except sqlite3.OperationalError as e:
                # Handle standard SQLite locks (e.g. "database is locked")
                conn.execute('ROLLBACK')
                # If it's a lock, we retry just like a version mismatch
                continue
            finally:
                conn.close()
                
        # If we exit the loop, retries are exhausted
        raise SettlementRetryExhausted(f"Failed to settle trade {trade.trade_id} after {max_retries} attempts.")
