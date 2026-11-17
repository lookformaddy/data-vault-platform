# data-vault-platform

Data Vault 2.0 modelling platform — build an auditable enterprise data vault
from raw staged records: deterministic salted hash keys, hubs, links and
end-dated satellites, point-in-time (PIT) and bridge tables, incremental
loading with hash-diff change detection, late-arriving data handling, and a
governed star-schema marts layer. Pure-stdlib core; optional FastAPI service.

**Track:** Data Engineering · **Day 31**

## The enterprise problem

Most warehouses destroy history the moment a value changes: a nightly
full-refresh overwrites yesterday's customer address, product price, or
order status, and nobody can later answer *"what did we believe about this
customer on February 28?"* Rebuilding that answer from source backups is
slow, error-prone, and unauditable — and every new source re-litigates the
same modelling questions.

Data Vault 2.0 fixes the shape of the problem: **hubs** record what exists
(business keys, hashed), **links** record how things relate, and
**satellites** record how things change (append-only, effective/end-dated).
History becomes a first-class citizen, loads become incremental by
construction, and new sources plug into the same pattern.

## What this builds

- **Salted SHA-256 hash keys** — every hub/link key is a deterministic hash
  of the business key, so the same source key maps to the same hash in every
  environment and raw keys never leak into downstream tables.
- **Hubs, links, satellites** — declared once in a config model
  (`config.load_default_model`), so adding a satellite is a config change.
- **Incremental loading with hash-diff change detection** — a satellite row
  is inserted only when its descriptive attributes actually changed;
  replays are checksum no-ops.
- **Late-arriving data** — rows effective earlier than the current version
  slot into the timeline and neighbours are re-end-dated; PIT reads stay
  correct without rewriting history.
- **Point-in-time (PIT) and bridge tables** — pre-computed as-of state per
  hub key × snapshot date, so as-of joins become equality joins.
- **Fail-closed data-quality gates** — bad records are quarantined with
  every violated rule attached; a batch over the quarantine-rate threshold
  loads nothing.
- **Schema evolution** — new satellite attributes register with a backfill
  default; existing rows keep their hash-diff and gain the default on read.
- **Governed marts layer** — `dim_customer`, `dim_product`, `fact_orders`
  built from the vault (never from source), so a rebuild for an earlier
  date reproduces that date's truth exactly.
- **Reconciliation** — row counts + order-independent checksums, vault vs
  source, with an explicit discrepancy list.
- **Retention / archival** — only closed satellite rows are eligible; the
  currently-effective version of any key is never archived.
- **Hash-chained audit log** — every load, PIT build, mart build, and
  retention run appends a tamper-evident entry; `verify()` reports the
  first broken sequence number.
- **FastAPI service + CLI** — the same engine behind HTTP (`/seed`,
  `/load`, `/pit`, `/as-of`, `/marts`, `/audit/verify`) and the command line.

## Architecture overview

```
source records → staging → DQ gate (fail-closed, quarantine)
                              │
                              ▼
                    VaultLoader (full + incremental,
                    hash-diff, late-arriving)
                              ▼
              hubs ── links ── satellites (end-dated)
                              ▼
                    PIT tables + bridge tables
                              ▼
                    governed marts (star schema)
                              │
        reconciliation ── retention ── hash-chained audit log
```

Full design notes, decisions and trade-offs: [`docs/architecture.md`](docs/architecture.md).

## How to run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# End-to-end demo (seed → loads → PIT → marts → reconciliation → audit)
python scripts/demo.py
# or: make demo

# Tests
python -m pytest -q
# or: make test

# CLI
PYTHONPATH=src python -m datavault.cli load-demo
PYTHONPATH=src python -m datavault.cli pit --entity customer \
    --business-key CUST-1001 --as-of 2026-02-28T00:00:00Z
PYTHONPATH=src python -m datavault.cli marts --as-of 2026-03-31T00:00:00Z
PYTHONPATH=src python -m datavault.cli audit

# API
make serve   # uvicorn datavault.service:app on :8000
curl -X POST localhost:8000/seed
curl "localhost:8000/as-of/customer?business_key=CUST-1001&as_of=2026-01-31T00:00:00Z"
curl localhost:8000/audit/verify

# Docker
docker build -t data-vault-platform . && docker run -p 8000:8000 data-vault-platform
```

## Demo (synthetic retail: customers, orders, products, shipments)

Seeded history is planted so PIT reads are verifiable: a customer moves
city and tier mid-quarter, a product reprices, orders move
placed → shipped → delivered, and one customer update is late-arriving
(effective Feb 10, loaded Mar 5). Headline demo numbers:

- **Loads:** 12 customers (15 satellite rows), 8 products (10 rows),
  20 orders (40 satellite rows, 40 links), 12 shipments
- **Incremental replay:** 15/15 customer records skipped as checksum no-ops
- **Quarantine:** 3 corrupt records quarantined (bad email, negative price,
  unknown status); the corrupt batch fails the DQ gate
- **PIT:** Ada is in Springfield (gold) on Jan 31 and Riverton (platinum)
  on Mar 31; the late-arriving Edsger row is correctly visible on Feb 28;
  the backpack is $89.99 in Jan and $99.99 in Mar
- **Marts:** 12 dim_customer / 8 dim_product / 20 fact_orders
- **Reconciliation:** all 4 entities pass (counts + checksums)
- **Audit log:** hash chain verifies

## Key design decisions and trade-offs

- **Hash keys, not raw keys** — deterministic, environment-stable, and
  PII-safe in downstream tables; the cost is opacity (the hub row carries
  the business-key lookup for debugging).
- **Hash-diff inserts** — unchanged reloads are no-ops; requires canonical
  serialisation, or phantom versions appear.
- **End-dated satellites + in-timeline late inserts** — PIT reads stay
  correct without rewriting history; mid-timeline inserts are O(versions
  per key), fine for satellites.
- **Fail-closed DQ gate** (default 5% quarantine rate) — a bad feed cannot
  poison the vault; small batches fail on a single bad record by design.
- **PIT/bridge tables are derived, not stored truth** — rebuilt from
  satellites/links per snapshot set, so they can never drift.
- **Marts built from the vault only** — rebuilds are reproducible as-of any
  date, which is what makes restatements auditable.
- **In-memory store behind a narrow interface** — `VaultStore` is the seam
  where Postgres/Snowflake/Databricks tables plug in; the demo and tests
  run with zero infrastructure.

## What it demonstrates

Data Vault 2.0 modelling as interviewers probe it: why hash keys, why
satellites are append-only, how PIT tables make as-of joins fast, how
late-arriving data is handled without rewriting history, how a fail-closed
quality gate protects the vault, and how reconciliation plus a hash-chained
audit log make the whole thing provable after the fact.

## Project layout

```
src/datavault/      hashing, config, store, quality, loader, pit, marts,
                    reconciliation, retention, audit, demo_data, demo,
                    service (FastAPI), cli
tests/              pytest suite (core logic + service + CLI)
docs/               architecture.md, github-actions-ci.yml
scripts/demo.py     end-to-end demo runner
```

## Configuration

Copy `.env.example` to `.env`. `DVP_HASH_SALT` namespaces every hash key
(change per environment); `DVP_MAX_QUARANTINE_RATE` sets the fail-closed
gate; `DVP_RETENTION_DAYS` drives the archival policy.
