"""CLI for the Data Vault Platform.

Usage:
    python -m datavault.cli demo
    python -m datavault.cli load-demo
    python -m datavault.cli pit --satellite sat_customer --business-key CUST-1001 --as-of 2026-02-28T00:00:00Z
    python -m datavault.cli marts --as-of 2026-03-31T00:00:00Z
    python -m datavault.cli audit
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from datavault.config import Settings, load_default_model
from datavault.demo import print_demo, run_demo
from datavault.demo_data import seed_all
from datavault.loader import VaultLoader
from datavault.marts import build_marts
from datavault.pit import as_of_view
from datavault.store import VaultStore

ENTITY_HUB = {"customer": ("hub_customer", "sat_customer", "customer_id"),
              "product": ("hub_product", "sat_product", "product_sku"),
              "order": ("hub_order", "sat_order", "order_id"),
              "shipment": ("hub_shipment", "sat_shipment", "shipment_id")}


def _fresh() -> tuple[VaultStore, VaultLoader, Settings]:
    settings = Settings.from_env()
    model = load_default_model()
    store = VaultStore(model, settings.hash_salt)
    return store, VaultLoader(store, model, settings), settings


def cmd_demo(_args: argparse.Namespace) -> int:
    print_demo(run_demo())
    return 0


def cmd_load_demo(_args: argparse.Namespace) -> int:
    store, loader, _ = _fresh()
    for entity, records in seed_all().items():
        report = loader.load_full(entity, records, "cli-batch", "2026-01-05T09:00:00Z")
        print(f"{entity:9s} staged={report.staged} hubs={report.hubs_inserted} "
              f"sat_rows={report.satellite_rows_inserted} links={report.links_inserted} "
              f"quarantined={report.quarantined}")
    print(json.dumps(store.summary(), indent=2))
    return 0


def cmd_pit(args: argparse.Namespace) -> int:
    store, loader, _ = _fresh()
    for entity, records in seed_all().items():
        loader.load_full(entity, records, "cli-batch", "2026-01-05T09:00:00Z")
    hub_name, sat_name, key_field = ENTITY_HUB[args.entity]
    view = as_of_view(store, hub_name, {key_field: args.business_key}, sat_name, args.as_of)
    if view is None:
        print(f"no {args.entity} row in force at {args.as_of}", file=sys.stderr)
        return 1
    print(json.dumps(view, indent=2, sort_keys=True))
    return 0


def cmd_marts(args: argparse.Namespace) -> int:
    store, loader, _ = _fresh()
    for entity, records in seed_all().items():
        loader.load_full(entity, records, "cli-batch", "2026-01-05T09:00:00Z")
    marts = build_marts(store, args.as_of)
    print(json.dumps(marts["audit"], indent=2))
    print(f"fact_total_amount={sum(f['total_amount'] for f in marts['fact_orders']):.2f}")
    return 0


def cmd_audit(_args: argparse.Namespace) -> int:
    store, _, _ = _fresh()
    ok, broken = store.audit.verify()
    print(f"audit entries={len(store.audit.entries)} chain_valid={ok} "
          f"first_broken_seq={broken}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-vault",
                                     description="Data Vault 2.0 modelling platform")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="run the end-to-end demo")
    sub.add_parser("load-demo", help="load the synthetic retail seed into a fresh vault")
    pit = sub.add_parser("pit", help="point-in-time read for one business key")
    pit.add_argument("--entity", choices=list(ENTITY_HUB), required=True)
    pit.add_argument("--business-key", required=True)
    pit.add_argument("--as-of", required=True)
    marts = sub.add_parser("marts", help="build the governed star-schema marts")
    marts.add_argument("--as-of", default="2026-03-31T00:00:00Z")
    sub.add_parser("audit", help="verify the hash-chained audit log")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers: dict[str, Any] = {"demo": cmd_demo, "load-demo": cmd_load_demo,
                                "pit": cmd_pit, "marts": cmd_marts, "audit": cmd_audit}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
