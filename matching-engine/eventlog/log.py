import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterator, Literal

@dataclass
class LogEntry:
    seq_no: int
    type: str  # 'order' or 'trade'
    payload: Dict
    timestamp: str

class EventLog:
    def __init__(self, db_path: str = "event_log.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initializes the event log table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS event_log (
                    seq_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            ''')

    def append(self, entry_type: Literal['order', 'trade'], payload: dict) -> LogEntry:
        """
        Appends a new event to the log.
        Uses SQLite transaction (via connection context manager) to ensure atomicity.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                'INSERT INTO event_log (type, payload, timestamp) VALUES (?, ?, ?)',
                (entry_type, payload_json, timestamp)
            )
            seq_no = cursor.lastrowid
            
        return LogEntry(
            seq_no=seq_no,
            type=entry_type,
            payload=payload,
            timestamp=timestamp
        )

    def read_all(self) -> Iterator[LogEntry]:
        """Reads and yields all log entries sequentially."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT seq_no, type, payload, timestamp FROM event_log ORDER BY seq_no ASC')
            for row in cursor:
                yield LogEntry(
                    seq_no=row[0],
                    type=row[1],
                    payload=json.loads(row[2]),
                    timestamp=row[3]
                )
