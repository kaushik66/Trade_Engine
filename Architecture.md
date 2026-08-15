# Order Matching Engine — Build Spec

Purpose of this doc: lock the scope before you start coding. Anything not listed under "Feature List" is out of scope until v1 is done and tested end-to-end. If you think of a new feature while building, write it in a "Later" section at the bottom — do not build it now.

---

## 1. Components

| #   | Component               | Responsibility                                                                                                                         |
| --- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Gateway**             | Accept order requests, validate input shape, reject malformed/invalid orders before they touch the engine                              |
| 2   | **Matching Engine**     | Own the order book per symbol; match incoming orders against resting orders; emit Trade events                                         |
| 3   | **Event Log**           | Append-only, ordered record of every accepted Order and every Trade; source of truth; replayable                                       |
| 4   | **Settlement/Ledger**   | Consume Trade events; update account balances; enforce correctness under concurrent trades                                             |
| 5   | **Query Layer**         | Read-only views: order book depth, trade history, account balance                                                                      |
| 6   | **Stress/Test Harness** | Fires concurrent conflicting requests at Settlement; drives the correctness proof                                                      |
| 7   | **Presentation Layer**  | One page: live order book view + order-submission form + trade feed. Read/write via Gateway and Query Layer only — no logic of its own |

---

## 2. Interactions (data flow)

```
Client → Gateway → Matching Engine → Event Log (append order)
                          │
                          ├─ if match found → Trade(s) generated
                          │        │
                          │        ├─→ Event Log (append trade)
                          │        └─→ Settlement (update balances)
                          │
                          └─ if no match → order rests in book

Query Layer reads from: Matching Engine (book state), Event Log (history), Settlement (balances)

Presentation Layer → Gateway (submit orders)
Presentation Layer ← Query Layer (poll/subscribe: book depth, trade feed, balances)
```

**Rule:** Presentation Layer contains zero business logic — no matching, no validation beyond basic form checks, no balance math. It only calls Gateway to submit and Query Layer to read. If you find yourself computing anything domain-specific in the frontend, that logic belongs in a backend component instead.

**Rule:** Gateway never talks to Settlement or Event Log directly. Matching Engine never updates balances directly — it only emits Trade events that Settlement consumes. Keep these boundaries hard; this is what makes the system "clearly structured" rather than a tangle.

---

## 3. Dependency order (what needs what to exist first)

```
Event Log        — no dependencies, build first
Matching Engine   — depends on: Event Log (to append orders/trades)
Settlement/Ledger — depends on: Event Log (to consume trade events)
Gateway           — depends on: Matching Engine
Query Layer       — depends on: Matching Engine, Event Log, Settlement (read-only, build last)
Stress Harness    — depends on: Settlement (built alongside it, not after)
Presentation Layer — depends on: Gateway, Query Layer (build last, after everything underneath is proven correct)
```

---

## 4. Build order (day-by-day)

| Days | Build                                                               | Definition of done                                                                                                                                                                                               |
| ---- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Event Log                                                           | Can append an entry; can read back the full ordered log; append is atomic (no partial writes)                                                                                                                    |
| 2–3  | Matching Engine (single-threaded, in-memory order book)             | Given a sequence of orders, produces the correct set of trades and correct resting book state — verified by unit tests (see §6)                                                                                  |
| 4    | Wire Matching Engine → Event Log                                    | Every accepted order and every trade appears in the log, in correct order                                                                                                                                        |
| 5–6  | Settlement (naive version, no concurrency protection)               | Correctly updates balances for a _sequential_ stream of trades                                                                                                                                                   |
| 7    | Stress Harness v1                                                   | Concurrent conflicting trades against naive Settlement — **must reproduce a corrupted balance**. If it doesn't reproduce corruption, the harness is wrong, not the settlement — fix the harness before moving on |
| 8–9  | Settlement v2 (optimistic concurrency: version column + retry)      | Same stress harness run 3+ times, zero corruption every run                                                                                                                                                      |
| 10   | Gateway                                                             | Rejects malformed orders before they reach the engine; valid orders flow through end-to-end                                                                                                                      |
| 11   | Query Layer                                                         | Returns correct book depth, trade history, balances at any point mid-run                                                                                                                                         |
| 12   | End-to-end integration test                                         | Full flow: submit orders via Gateway → trades settle → query layer reflects final state correctly                                                                                                                |
| 13   | Presentation Layer (order book view + submission form + trade feed) | Can submit an order from the page, watch it match/rest, see trade feed and book update live                                                                                                                      |
| 14   | Load test + buffer / writeup                                        | Orders/sec throughput number before/after concurrency protection; fix whatever broke; do not add features here                                                                                                   |

---

## 5. Feature list (v1 — nothing beyond this until it's done)

**In scope:**

- Limit orders only (buy/sell at a specified price) — **no market orders**
- Single symbol is fine; multi-symbol only if trivially easy given your data structure (map of symbol → book)
- Price-time priority matching
- Partial fills
- Order cancellation (cancel a resting order by ID)
- Append-only event log with replay-to-rebuild-state capability
- Optimistic concurrency control on Settlement
- Basic balance validation (reject orders that would overdraw an account) — simple check, not a full risk engine
- Presentation Layer, one page only: order book table (bids/asks by price level), order submission form, live trade feed. Polling is fine — no need for websockets unless trivial

**Explicitly out of scope for v1 (write here, don't build):**

- Market orders, stop orders, or any order type beyond simple limit orders
- Multi-node / distributed matching
- Persistence beyond the event log (no separate DB unless it's trivial)
- Auth, users, UI polish beyond basic readability
- Any LLM integration
- Fee calculation, margin, short-selling
- Charts, analytics dashboards, historical replay UI, multi-page frontend, styling beyond functional clarity

---

## 6. How to test each component (and how to test the interfaces between them)

**Event Log**

- Unit: append N entries, read back — order and content match exactly
- Failure test: simulate a crash mid-append (or just kill the process) — confirm no partial/corrupt entry on restart

**Matching Engine**

- Unit: hand-crafted order sequences with known expected trades (e.g., "sell 10@100 resting, buy 5@100 arrives → expect 1 trade for 5@100, resting sell reduced to 5")
- Property test if you have time: random order sequences, assert invariant "sum of filled quantities across trades == sum of matched quantities in book changes" (conservation check)
- Interface test with Event Log: after running a sequence, replay the log and confirm it reconstructs the same final book state independently

**Settlement (naive)**

- Unit: sequential trades → correct final balances
- This version is _expected_ to fail the concurrency test — that failure is itself a deliverable, don't skip documenting it

**Settlement (v2, concurrency-safe)**

- The stress harness: N concurrent workers, each executing conflicting trades against the same account, repeated across multiple runs
- Pass condition: final balance always matches the sequential-equivalent expected balance, across every run
- Also check: no silently dropped trades — every trade either commits or explicitly retries-and-commits, none vanish

**Gateway**

- Unit: malformed orders (negative price, missing fields, unknown symbol) are rejected with the trade/log/settlement never invoked — verify via a mock/spy that downstream wasn't called

**Query Layer**

- Unit: after a known sequence of orders/trades, query results match hand-computed expected state
- Interface test: run the same sequence twice (fresh state each time) — results must be identical (determinism check)

**End-to-end**

- Submit a realistic mixed sequence (rests, matches, partial fills, cancels, concurrent trades) through the Gateway only — assert final Query Layer output matches an independently hand-computed expected state

**Presentation Layer**

- Manual test: submit an order from the form, confirm it appears correctly in the book or trade feed within one poll cycle
- Confirm the page contains zero domain logic by inspection — every number shown should be traceable to a Query Layer response, not computed client-side

---

## 7. Tools

- Language: your call, but pick one that gives you real threads/async concurrency you control explicitly (Python with `threading`/`asyncio`, or Go, or Node with worker threads) — avoid a stack where concurrency is hidden from you, since demonstrating you understand the race condition is the point
- Storage: in-memory is fine for the order book; Event Log can be a simple append-only file or a single append-only DB table — no need for Kafka/etc., that's over-engineering for this scope
- Settlement store: any DB with row versioning support (Postgres works well — native `SELECT ... FOR UPDATE` or a version column) is enough for optimistic concurrency
- Testing: standard unit test framework for your language + a small script for the concurrency stress harness (spin up N threads/tasks hammering the same account)
- Presentation Layer: a single React page (or plain HTML/JS if you want zero build overhead) hitting the Gateway/Query Layer over REST — no framework beyond what's needed for a form, a table, and a polling fetch
- **Language (locked): Python.** Reasoning: the project's value is entirely in matching-algorithm correctness and the concurrency proof, not raw throughput — Python's `threading`/`asyncio` primitives are simpler to reason about and less likely to introduce unrelated memory/threading bugs that eat build time. The concurrency bug being proven is I/O-bound (DB writes), not CPU-bound, so the GIL doesn't undermine it. Flask/FastAPI reuses stack experience already built on Cortex/RetinaScan, leaving more time for the two hard components.

---

## 8. Strict per-component specification

This section is the binding contract. Once you start coding, if an implementation detail isn't listed here, it's either (a) not needed for v1, or (b) needs to be added here first — before you write the code, not after. Don't let an implementation choice exist only in your head or in code comments.

### 8.1 Gateway

**Data structures:** none of its own — stateless request handler.

**Constraints (validation rules, checked in this order, reject on first failure):**

- `side` ∈ {buy, sell}
- `price` > 0, numeric, max 2 decimal places
- `quantity` > 0, integer
- `symbol` ∈ configured symbol whitelist
- account has sufficient balance for a buy (`price × quantity ≤ available_cash`) or sufficient holdings for a sell (`quantity ≤ available_units`) — read-only check against Query Layer, not a lock

**Algorithm:** none — pure validation + forward. No retries, no business logic.

**Output contract:** on success, forwards a normalized `Order{id, side, symbol, price, quantity, account_id, timestamp}` to the Matching Engine. On failure, returns a rejection reason to the caller; nothing downstream is invoked.

---

### 8.2 Matching Engine

**Data structures (locked):**

- Order book per symbol = two sorted maps: `price → deque[Order]` — Bids sorted descending, Asks sorted ascending (balanced BST / SortedDict, e.g. Python's `sortedcontainers.SortedDict`)
- A secondary index `order_id → (side, price)` for O(1) lookup on cancellation, since a plain heap can't support O(log n) cancel-by-id and cancellation is in scope — this is why sorted map was chosen over a heap
- Each resting order retains: `id, price, remaining_quantity, timestamp`

**Constraints:**

- Matching only occurs when `best_bid_price ≥ best_ask_price`
- Match price = the **resting** order's price (the order already in the book), never the incoming order's price
- Time priority within a price level is strict FIFO — no reordering
- An order is fully consumed (removed from book) when `remaining_quantity == 0`

**Algorithm (price-time priority matching):**

1. Incoming order arrives.
2. While incoming order has remaining quantity AND opposing side's best price crosses:
   a. Take the oldest resting order at the best opposing price.
   b. `trade_qty = min(incoming.remaining_quantity, resting.remaining_quantity)`
   c. Emit `Trade{price: resting.price, quantity: trade_qty, buy_order_id, sell_order_id, timestamp}`
   d. Decrement both orders' `remaining_quantity` by `trade_qty`.
   e. If resting order's `remaining_quantity == 0`, remove it from the book.
3. If incoming order still has remaining quantity after the loop, insert it into the book as a new resting order.

**Invariant to test against:** sum of all `trade_qty` across trades from one incoming order ≤ incoming order's original quantity; book state is always fully explained by the sequence of orders and trades in the Event Log.

---

### 8.3 Event Log

**Data structures:** single append-only sequence (file or DB table) of entries: `LogEntry{seq_no, type: order|trade, payload, timestamp}`. `seq_no` is monotonically increasing, assigned at write time.

**Constraints:**

- Append is the only write operation — no update, no delete
- Writes must be atomic: a log entry is either fully written or not present — use fsync/flush-on-write or your storage engine's atomic append guarantee
- Every Order the Matching Engine accepts and every Trade it emits is logged **before** Settlement is invoked, not after

**Algorithm:** ordered append and sequential read for replay. Replay = read all entries in `seq_no` order, feed Orders back into a fresh Matching Engine instance, and Trades should reproduce exactly (used as a correctness check, not part of the runtime path).

---

### 8.4 Settlement / Ledger

**Data structures:** `Account{id, version, cash_balance, holdings: {symbol: quantity}}`. The `version` field is mandatory — it's the concurrency control mechanism.

**Constraints:**

- A trade updates exactly two accounts (buyer, seller) — both updates must succeed together or neither does (treat as one transaction)
- No balance may go negative post-update
- Every update must check `version` and increment it — non-negotiable, it's the whole mechanism

**Algorithm (optimistic concurrency control):**

1. Read account row including current `version`.
2. Compute new balance in memory.
3. Write update `WHERE id = account_id AND version = read_version`, setting `version = read_version + 1`.
4. If the write affected 0 rows (version mismatch = concurrent write happened), retry from step 1.
5. Cap retries (e.g. 5) — if exceeded, surface an error rather than retrying forever.

**Interface test contract:** the stress harness must be able to fire ≥2 concurrent conflicting trades at the same account and, after all complete, the account balance must equal the value computed by applying the same trades sequentially in any order.

---

### 8.5 Query Layer

**Data structures:** none of its own — reads directly from Matching Engine's in-memory book, Event Log, and Settlement's account store. No caching/materialized view for v1.

**Constraints:** read-only, no side effects, must never block a write in Matching Engine or Settlement.

**Algorithm:** direct reads, formatted for output (e.g. top N price levels for book depth).

---

### 8.6 Stress / Test Harness

**Data structures:** a fixed test-account setup with known starting balance; a list of conflicting trade instructions to fire concurrently.

**Constraints:** must use real concurrency (actual threads/async tasks/processes), not sequential calls disguised as concurrent.

**Algorithm:**

1. Set up account with known balance.
2. Spawn N concurrent workers, each executing a trade against that account.
3. Wait for all to complete (or retry-exhaust).
4. Assert final balance == sequential-equivalent expected balance.
5. Repeat the run ≥3 times (timing-dependent bugs need repeated runs to prove absence, not one clean pass).

---

### 8.7 Presentation Layer

**Data structures:** none — component state only (current book snapshot, trade feed, form inputs), sourced entirely from Gateway/Query Layer responses.

**Constraints:** zero domain computation (restated from §2) — every number on screen must trace to a Query Layer field, not a client-side calculation.

**Algorithm:** poll Query Layer on an interval (e.g. every 1–2s) for book depth and trade feed; submit form data to Gateway on user action; no algorithm beyond that.

---

## 9. Agent-build contract (API, structure, errors, stack)

This section exists so an AI coding agent (or you, across sessions) has zero ambiguity to fill in on its own. Locked decisions, not suggestions.

### 9.1 Locked tech stack

- Language: Python 3.11+
- Web framework: FastAPI (async-native, pairs well with the concurrency work in Settlement)
- Settlement store: SQLite for v1 (has enough transactional support for optimistic concurrency; swap to Postgres only if SQLite's locking gets in the way during the stress test)
- Event Log: append-only SQLite table (`event_log`), separate file/DB from the account store to keep it conceptually independent
- Order book: in-memory only, per-process (no persistence needed — it's rebuilt from Event Log replay on restart)
- Test framework: `pytest`; concurrency stress harness uses `concurrent.futures.ThreadPoolExecutor` or `asyncio.gather`
- Presentation Layer: plain HTML/JS with `fetch()` polling — no React build step, to keep setup friction at zero

### 9.2 Project structure

```
matching-engine/
  api/
    gateway.py          # FastAPI routes, validation (8.1)
    query.py            # read-only endpoints (8.5)
  engine/
    order_book.py        # sorted-map book, matching loop (8.2)
    models.py             # Order, Trade dataclasses
  eventlog/
    log.py                 # append + replay (8.3)
  settlement/
    ledger.py              # Account model, OCC update logic (8.4)
  tests/
    test_matching.py
    test_eventlog.py
    test_settlement.py
    test_stress.py         # concurrency harness (8.6)
    test_integration.py
  frontend/
    index.html              # presentation layer (8.7)
  requirements.txt
  README.md
```

### 9.3 API contract

All request/response bodies are JSON. All endpoints prefixed `/api`.

**POST /api/orders** — submit an order

- Request: `{account_id: str, side: "buy"|"sell", symbol: str, price: number, quantity: int}`
- Response 201: `{order_id: str, status: "accepted", fills: [{trade_id, price, quantity}], remaining_quantity: int}`
- Response 400: `{error: str, field: str}` — validation failure per §8.1's rule list; nothing downstream is invoked

**DELETE /api/orders/{order_id}** — cancel a resting order

- Response 200: `{order_id: str, status: "cancelled"}`
- Response 404: `{error: "order not found or already filled"}`

**GET /api/book/{symbol}** — order book depth

- Response 200: `{symbol: str, bids: [{price, total_quantity}], asks: [{price, total_quantity}]}` (top N levels, N=10 default)

**GET /api/trades?symbol=&limit=** — recent trade feed

- Response 200: `{trades: [{trade_id, symbol, price, quantity, timestamp}]}`

**GET /api/accounts/{account_id}** — balance/holdings

- Response 200: `{account_id, cash_balance, holdings: {symbol: quantity}, version}`

### 9.4 Error handling conventions

- Gateway validation failure → HTTP 400, response shape above, Matching Engine never invoked
- Matching Engine internal error (should not happen if invariants hold, but defensively) → HTTP 500, order is NOT written to Event Log if the engine failed before producing a result
- Settlement retry exhaustion (§8.4 step 5) → the triggering trade is marked `status: "settlement_failed"` in the Event Log (append a new entry, never mutate the original), HTTP 500 returned to whichever request path triggered it; do not silently drop it
- Every error response includes a `field` or `component` key identifying where it originated — this matters for debugging across the five backend components

### 9.5 Naming/style conventions (for consistency across agent sessions)

- All monetary values: integers in smallest unit (cents/paise), never floats — avoids float rounding bugs in balance math
- All timestamps: UTC, ISO 8601 strings
- All IDs: UUIDv4 strings
- snake_case for all JSON keys and Python identifiers

---

## 10. Later (parking lot — do not build during v1)

_(empty — add here if you think of something mid-build, and only revisit after Day 12 integration test passes)_
