import os
import sqlite3
import pytest
import multiprocessing
from time import sleep
from eventlog.log import EventLog, LogEntry

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_event_log.db"
    yield str(db_path)
    if db_path.exists():
        os.remove(db_path)

def test_append_and_read_back(temp_db):
    log = EventLog(temp_db)
    
    entries_to_add = [
        ('order', {'id': '1', 'side': 'buy', 'price': 10000}),
        ('order', {'id': '2', 'side': 'sell', 'price': 10500}),
        ('trade', {'buy_order_id': '1', 'sell_order_id': '2', 'quantity': 10})
    ]
    
    for entry_type, payload in entries_to_add:
        log.append(entry_type, payload)
        
    read_entries = list(log.read_all())
    
    assert len(read_entries) == len(entries_to_add)
    
    for i, (expected_type, expected_payload) in enumerate(entries_to_add):
        assert read_entries[i].seq_no == i + 1
        assert read_entries[i].type == expected_type
        assert read_entries[i].payload == expected_payload
        assert read_entries[i].timestamp is not None

def crash_simulator(db_path, ready_event):
    """
    Simulate a process that starts writing to the database and crashes.
    Using sqlite directly to simulate an interrupted transaction.
    """
    # Connect and begin transaction
    conn = sqlite3.connect(db_path)
    conn.execute('BEGIN TRANSACTION')
    conn.execute(
        'INSERT INTO event_log (type, payload, timestamp) VALUES (?, ?, ?)',
        ('order', '{"id": "partial"}', '2026-01-01T00:00:00Z')
    )
    # Signal that we've written the partial uncommitted data
    ready_event.set()
    # Hang indefinitely (simulating a crash where connection drops abruptly without commit)
    while True:
        sleep(0.1)

def test_crash_recovery(temp_db):
    # Initialize DB with table
    EventLog(temp_db)
    
    ready_event = multiprocessing.Event()
    p = multiprocessing.Process(target=crash_simulator, args=(temp_db, ready_event))
    p.start()
    
    # Wait for the process to write uncommitted data
    ready_event.wait(timeout=2.0)
    
    # "Kill" the process abruptly to simulate a crash
    p.terminate()
    p.join()
    
    # Reconnect and ensure no partial data was committed
    log = EventLog(temp_db)
    read_entries = list(log.read_all())
    
    # Assert nothing was saved
    assert len(read_entries) == 0
