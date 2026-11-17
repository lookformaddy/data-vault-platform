# Data Vault Platform — architecture

## Problem

Enterprise warehouses usually grow the same way: a staging table per source,
a wide dimension table per subject, and a nightly full-refresh job that
destroys history the moment a value changes. The result is un-auditable —
nobody can answer "what did we believe about this customer on February 28?"
— and un-scalable, because every new source re-litigates the same modelling
questions. Data Vault 2.0 answers both: it separates *what exists* (hubs),
*how things relate* (links) and *how things change* (satellites), so history
is append-only, loads are incremental by construction, and new sources plug
into the same pattern without redesigning the model.

## Components

```
source records ──▶ staging ──▶ DQ gate (fail-closed, quarantine)
                        │
                        ▼
              ┌─────────────────┐
              │  VaultLoader    │  hash-diff change detection,
              │  (full + incr.) │  late-arriving handling
              └────────┬────────┘
                       ▼
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   hubs (SHA-256    links (SHA-256  satellites (effective /
   business keys)   of hub keys)    end-dated, hash-diffed)
        │              │              │
        └──────────────┼──────────────┘
                       ▼
              PIT tables + bridge tables
                       ▼
              governed marts (star schema)
                       │
        reconciliation (counts + checksums) ──▶ retention / archival
                       │
              hash-chained audit log (every event)
```

| Module | Responsibility |
|---|---|
| `config.py` | Declarative vault model (hubs/links/satellites), schema evolution, settings from env |
| `hashing.py` | Salted SHA-256 business keys, hash-diffs, order-independent checksums, hash-chain links |
| `store.py` | In-memory vault: hubs, links, end-dated satellites, PIT reads, audit columns |
| `quality.py` | Declarative DQ rules; fail-closed gate with reason-carrying quarantine |
| `loader.py` | Full + incremental loads, hash-diff inserts, late-arriving inserts, link resolution |
| `pit.py` | PIT tables (per hub key × snapshot) and bridge tables (link × snapshot) |
| `marts.py` | Governed star schema (dim_customer, dim_product, fact_orders) built from the vault only |
| `reconciliation.py` | Row counts + checksums vault-vs-source, discrepancy list |
| `retention.py` | Archival of closed satellite rows only; open rows are never archived |
| `audit.py` | Hash-chained append-only audit log with tamper detection |
| `service.py` | FastAPI surface (`/seed`, `/load`, `/pit`, `/as-of`, `/marts`, `/audit/verify`) |
| `cli.py` | `demo`, `load-demo`, `pit`, `marts`, `audit` commands |
| `demo_data.py` | Deterministic synthetic retail seed with planted history |

## Key design decisions

1. **Salted hash keys, never raw keys as join keys.** Hub/link keys are
   SHA-256 of the salted business key. The same source key always maps to
   the same hash in every environment, raw keys never leak into PIT/bridge/
   mart tables, and re-salting per environment is a one-line config change.
   Trade-off: hashes are opaque — debugging needs the business-key lookup
   the hub row itself carries.
2. **Hash-diff change detection.** A satellite row is inserted only when
   the SHA-256 of its descriptive attributes changes. Unchanged reloads
   are no-ops, so full reloads are safe and incremental loads are cheap.
   Trade-off: attribute order and float rendering must be canonicalised
   (see `hashing.canonical`); a non-canonical serialiser would create
   phantom versions.
3. **End-dated satellites with in-timeline late-arriving inserts.** A
   late-arriving row is inserted at its effective date and its neighbours'
   `end_dts` values are repaired. History is never rewritten — the row is
   new — but PIT reads stay correct. Trade-off: inserting mid-timeline is
   O(versions per key), fine for satellites, wrong for a billion-row fact.
4. **Fail-closed DQ gate.** A batch whose quarantine rate exceeds
   `DVP_MAX_QUARANTINE_RATE` (default 5%) loads nothing. Quarantined rows
   carry every violated rule, so the source owner can fix and replay.
   Trade-off: a single bad record in a tiny batch fails the whole batch;
   that is the point — small batches should be validated upstream.
5. **PIT/bridge tables are derived, not stored truth.** They are rebuilt
   from satellites/links per snapshot set, so they can never drift from
   the vault. Trade-off: rebuild cost grows with snapshot count; a
   production deployment would materialise and incrementally maintain them.
6. **Marts are built from the vault, never from source.** A mart rebuild
   for an earlier date reproduces that date's truth exactly, which is what
   makes restatements auditable. Trade-off: mart builds pay a PIT lookup
   per dimension row.
7. **Retention archives closed rows only.** The currently-effective
   version of any business key is never archived, so time-travel to the
   present always works. Trade-off: "closed" is defined by `end_dts`,
   so a satellite that never versions never archives.
8. **In-memory store behind a narrow interface.** The engine is storage
   agnostic by design: `VaultStore` is the seam where a real deployment
   plugs in Postgres/Snowflake/Databricks tables. The demo and tests run
   with zero infrastructure, which is what makes the logic testable.

## Data flow (one load)

1. Records are staged with their source `effective_dts` / `load_dts`.
2. DQ rules run; failures go to quarantine with reasons.
3. If the quarantine rate exceeds the threshold, the batch fails closed.
4. Hub upsert (new business key → new hash key), link upsert.
5. Satellite insert iff hash-diff changed; same-effective-date corrections
   replace in place; late-arriving rows slot into the timeline.
6. Audit log appends `load_completed` (or `load_gate_failed`).

## Verification story

- `tests/test_pit.py` proves PIT reads return the Jan vs Mar truth for a
  customer, a price change, and a late-arriving row loaded a month late.
- `tests/test_reconciliation_retention.py` proves reconciliation catches a
  deleted hub and a tampered satellite, and retention never archives an
  open row.
- `tests/test_loader.py` proves hash-diff dedupe, incremental checksum
  no-ops, and same-date corrections.
- `scripts/demo.py` runs the whole pipeline end to end and prints the
  headline numbers (see README).

## What this demonstrates

Data Vault 2.0 modelling in the form interviewers actually probe: why hash
keys, why satellites are append-only, how PIT tables make as-of joins fast,
how late-arriving data is handled without rewriting history, how a fail-
closed quality gate protects the vault, and how reconciliation + a hash-
chained audit log make the whole thing provable after the fact.
