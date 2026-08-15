from fastapi import FastAPI
from contextlib import asynccontextmanager
from eventlog.log import EventLog
from settlement.ledger import Ledger
from engine.core import MatchingEngine
from . import gateway, query
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    DB_DIR = os.getenv("DB_DIR", ".")
    EVENT_LOG_PATH = os.path.join(DB_DIR, "event_log.db")
    LEDGER_PATH = os.path.join(DB_DIR, "ledger.db")
    
    # Startup: Initialize global state
    app.state.event_log = EventLog(EVENT_LOG_PATH)
    app.state.ledger = Ledger(LEDGER_PATH)
    app.state.matching_engine = MatchingEngine(app.state.event_log)
    
    # Restore matching engine state from event log
    app.state.matching_engine.restore_from_log()
    
    yield
    # Shutdown logic (none needed for sqlite)

app = FastAPI(lifespan=lifespan, title="Trade Engine API")

app.include_router(gateway.router, prefix="/api")
app.include_router(query.router, prefix="/api")
