"""Odoo access for trimatch, through the JSON-2 API only (SPEC section 3).

Build step 1 contains just the client and a connectivity check:

    uv run --project backend python -m trimatch.odoo_adapter --check

The check prints the buyer company, the suppliers and the seeded POs with ordered vs received
quantities, and exits non-zero if the seed is not what SPEC section 4 describes.
The adapter deliberately has no method that posts or pays anything.
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from trimatch.match import LinePair, PoLine, PoSnapshot
from trimatch.schema import Invoice

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_URL = "http://127.0.0.1:8069"
DEFAULT_DB = "trimatch"


class OdooError(RuntimeError):
    pass


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal .env reader (KEY=VALUE lines). Existing environment variables win.

    If a key appears twice in the file, the last line wins (a pasted new key at the
    bottom must replace the old one, not be ignored).
    """
    if not path.is_file():
        return
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in values.items():
        os.environ.setdefault(key, value)


class OdooClient:
    """Thin JSON-2 client: POST /json/2/<model>/<method> with a bearer API key."""

    def __init__(self, url: str, db: str, api_key: str, timeout: float = 30.0):
        self.db = db
        # On Windows "localhost" tries IPv6 first and costs ~2 s per request against the
        # Docker port (measured 2026-11-14: 21.8 s vs 1.3 s for 10 calls).
        url = url.replace("://localhost", "://127.0.0.1")
        self._http = httpx.Client(
            base_url=url.rstrip("/"),
            timeout=timeout,
            headers={
                "Authorization": f"bearer {api_key}",
                "X-Odoo-Database": db,
                "Content-Type": "application/json; charset=utf-8",
            },
        )

    @classmethod
    def from_env(cls) -> OdooClient:
        load_dotenv()
        key = os.environ.get("ODOO_API_KEY")
        if not key:
            raise OdooError("ODOO_API_KEY is not set (put it in .env, see odoo/README.md).")
        return cls(
            os.environ.get("ODOO_URL", DEFAULT_URL), os.environ.get("ODOO_DB", DEFAULT_DB), key
        )

    def call(self, model: str, method: str, ids: list[int] | None = None, **kwargs: Any) -> Any:
        body: dict[str, Any] = dict(kwargs)
        if ids is not None:
            body["ids"] = ids
        resp = self._http.post(f"/json/2/{model}/{method}", json=body)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("message", resp.text)
            except ValueError:
                detail = resp.text
            raise OdooError(f"{model}.{method} -> HTTP {resp.status_code}: {detail}")
        return resp.json()

    def search_read(self, model: str, domain: list, fields: list[str], **kwargs: Any) -> list[dict]:
        return self.call(model, "search_read", domain=domain, fields=fields, **kwargs)

    # --- Reads used by the pipeline -----------------------------------------------------

    def buyer_company(self) -> dict:
        companies = self.search_read("res.company", [], ["name", "partner_id"], limit=1)
        if not companies:
            raise OdooError("No company visible to the bot user.")
        company = companies[0]
        partner = self.call(
            "res.partner", "read", ids=[company["partner_id"][0]], fields=["additional_identifiers"]
        )[0]
        company["ice"] = (partner["additional_identifiers"] or {}).get("MA_ICE")
        return company

    def suppliers(self) -> list[dict]:
        rows = self.search_read(
            "res.partner",
            [("supplier_rank", ">", 0)],
            ["name", "additional_identifiers"],
            order="name",
        )
        for r in rows:
            r["ice"] = (r.pop("additional_identifiers") or {}).get("MA_ICE")
        return rows

    def find_supplier_by_ice(self, ice: str) -> list[dict]:
        """Exact ICE match, done in Python: JSON-field domains are not reliable."""
        return [s for s in self.suppliers() if s["ice"] == ice]

    def purchase_orders(self, names: list[str] | None = None) -> list[dict]:
        domain = [("name", "in", names)] if names else []
        orders = self.search_read(
            "purchase.order",
            domain,
            ["name", "partner_id", "state", "amount_untaxed"],
            order="name",
        )
        if not orders:
            return []
        lines = self.search_read(
            "purchase.order.line",
            [("order_id", "in", [o["id"] for o in orders]), ("display_type", "=", False)],
            ["order_id", "product_id", "product_qty", "qty_received", "price_unit", "uom_id"],
            order="order_id, sequence, id",
        )
        by_order: dict[int, list[dict]] = {o["id"]: [] for o in orders}
        for line in lines:
            by_order[line["order_id"][0]].append(line)
        for o in orders:
            o["lines"] = by_order[o["id"]]
        return orders

    # --- Step 3: PO snapshot, bills ------------------------------------------------------

    def po_snapshot(self, name: str) -> PoSnapshot | None:
        """The confirmed PO with this name, with billable quantities per line."""
        orders = self.search_read(
            "purchase.order",
            [("name", "=", name), ("state", "=", "purchase")],
            ["name", "partner_id", "state"],
            limit=2,
        )
        if len(orders) != 1:
            return None
        o = orders[0]
        lines = self.search_read(
            "purchase.order.line",
            [("order_id", "=", o["id"]), ("display_type", "=", False)],
            ["product_id", "product_qty", "qty_received", "qty_invoiced", "price_unit", "uom_id"],
            order="sequence, id",
        )
        products = {
            p["id"]: p
            for p in self.call(
                "product.product",
                "read",
                ids=sorted({ln["product_id"][0] for ln in lines}),
                fields=["default_code", "name"],
            )
        }
        return PoSnapshot(
            id=o["id"],
            name=o["name"],
            partner_id=o["partner_id"][0],
            state=o["state"],
            lines=[
                PoLine(
                    id=ln["id"],
                    default_code=products[ln["product_id"][0]]["default_code"] or None,
                    product_name=products[ln["product_id"][0]]["name"],
                    uom=ln["uom_id"][1],
                    qty_ordered=_dec(ln["product_qty"]),
                    qty_received=_dec(ln["qty_received"]),
                    qty_invoiced=_dec(ln["qty_invoiced"]),
                    price_unit=_dec(ln["price_unit"]),
                )
                for ln in lines
            ],
        )

    def find_bill(self, partner_id: int, ref: str) -> list[dict]:
        """Non-cancelled vendor bills of this supplier with this reference (invoice number)."""
        return self.search_read(
            "account.move",
            [
                ("move_type", "=", "in_invoice"),
                ("partner_id", "=", partner_id),
                ("ref", "=", ref),
                ("state", "!=", "cancel"),
            ],
            ["name", "state", "amount_total"],
        )

    def create_draft_bill(self, po: PoSnapshot, inv: Invoice, pairs: list[LinePair]) -> dict:
        """Draft bill from the PO (Odoo's own action), aligned line by line with the invoice.

        Returns {"id", "amount_untaxed", "amount_tax", "amount_total", "state"}. The bill is
        never posted: this adapter has no method that posts or pays.
        """
        action = self.call("purchase.order", "action_create_invoice", ids=[po.id])
        bill_id = action.get("res_id")
        if not bill_id:
            raise OdooError(f"action_create_invoice on {po.name} returned no single bill: {action}")
        lines = self.search_read(
            "account.move.line",
            [("move_id", "=", bill_id), ("display_type", "=", "product")],
            ["purchase_line_id"],
        )
        wanted = {p.po_line.id: inv.lines[p.invoice_line] for p in pairs}
        commands: list = []
        for bl in lines:
            pol = bl["purchase_line_id"][0] if bl["purchase_line_id"] else None
            if pol in wanted:
                ln = wanted[pol]
                commands.append(
                    (
                        1,
                        bl["id"],
                        {
                            "quantity": float(ln.quantity.value),
                            "price_unit": float(ln.unit_price_ht.value),
                        },
                    )
                )
            else:
                commands.append((2, bl["id"], 0))  # PO line this invoice doesn't bill
        vals: dict[str, Any] = {
            "ref": inv.number.value,
            "invoice_date": inv.date.value.isoformat(),
            "invoice_line_ids": commands,
        }
        self.call("account.move", "write", ids=[bill_id], vals=vals)
        if inv.due_date and inv.due_date.value:
            self.call(
                "account.move",
                "write",
                ids=[bill_id],
                vals={"invoice_date_due": inv.due_date.value.isoformat()},
            )
        bill = self.call(
            "account.move",
            "read",
            ids=[bill_id],
            fields=["name", "state", "amount_untaxed", "amount_tax", "amount_total"],
        )[0]
        if bill["state"] != "draft":
            raise OdooError(f"bill {bill_id} is in state {bill['state']}, expected draft")
        return bill

    def delete_own_draft(self, bill_id: int) -> None:
        """Remove a draft bill this run created seconds earlier (safety-check failure)."""
        bill = self.call("account.move", "read", ids=[bill_id], fields=["state"])[0]
        if bill["state"] != "draft":
            raise OdooError(f"refusing to delete bill {bill_id} in state {bill['state']}")
        self.call("account.move", "unlink", ids=[bill_id])

    def attach(self, model: str, res_id: int, files: list[Path]) -> list[int]:
        ids = []
        for f in files:
            ids.append(
                self.call(
                    "ir.attachment",
                    "create",
                    vals_list=[
                        {
                            "name": f.name,
                            "raw": base64.b64encode(f.read_bytes()).decode(
                                "ascii"
                            ),  # Odoo 20: no "datas"
                            "res_model": model,
                            "res_id": res_id,
                            "mimetype": mimetypes.guess_type(f.name)[0]
                            or "application/octet-stream",
                        }
                    ],
                )[0]
            )
        return ids


def _dec(x: float) -> Decimal:
    """Odoo floats -> Decimal at 4 dp (enough for qty and unit prices)."""
    return Decimal(repr(x)).quantize(Decimal("0.0001")).normalize()


# --- Step 1 check -------------------------------------------------------------------------

EXPECTED_POS = ["PO-001", "PO-002", "PO-003", "PO-004", "PO-005"]
EXPECTED_SHORT = {"PO-002"}


def run_check(client: OdooClient) -> int:
    problems: list[str] = []

    company = client.buyer_company()
    print(f"Company: {company['name']}  ICE {company['ice']}")
    if not company["ice"]:
        problems.append("company has no ICE")

    suppliers = client.suppliers()
    print(f"\nSuppliers ({len(suppliers)}):")
    for s in suppliers:
        print(f"  {s['name']:<32} ICE {s['ice']}")
    if len(suppliers) != 3 or not all(s["ice"] for s in suppliers):
        problems.append("expected 3 suppliers, each with an ICE")

    orders = client.purchase_orders(EXPECTED_POS)
    print(f"\nPurchase orders ({len(orders)}):")
    for o in orders:
        print(f"  {o['name']}  {o['partner_id'][1]}  state={o['state']}")
        short = False
        for line in o["lines"]:
            flag = ""
            if line["qty_received"] < line["product_qty"]:
                short = True
                flag = "  <- short"
            print(
                f"      {line['product_id'][1]:<52} ordered {line['product_qty']:>7.2f}"
                f"  received {line['qty_received']:>7.2f}  {line['uom_id'][1]:<8}"
                f" @ {line['price_unit']:.2f}{flag}"
            )
        if o["state"] != "purchase":
            problems.append(f"{o['name']} state is {o['state']}, expected 'purchase'")
        if short != (o["name"] in EXPECTED_SHORT):
            problems.append(f"{o['name']} receipt shortfall is {short}, expected the opposite")
    missing = set(EXPECTED_POS) - {o["name"] for o in orders}
    if missing:
        problems.append(f"missing POs: {sorted(missing)}")

    if problems:
        print("\nCHECK FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nCHECK OK: JSON-2 works and the seed matches SPEC section 4.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trimatch.odoo_adapter")
    parser.add_argument("--check", action="store_true", help="verify the seeded Odoo over JSON-2")
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 2
    try:
        return run_check(OdooClient.from_env())
    except (OdooError, httpx.HTTPError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
