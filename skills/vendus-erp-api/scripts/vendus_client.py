"""
Vendus (Cegid Vendus) API client — queries and confirmed document creation.

This module is part of the `vendus-erp-api` skill. It wraps the
Vendus REST API (https://www.vendus.co.ao/ws/v1.1/) with thin helpers for
clients, client balance, products, product stocks, document queries,
and explicitly confirmed document issuance.

Design rules:
  - Only write operation: confirmed POST /documents/. No generic write helper.
  - The API key is read from the VENDUS_API_KEY environment variable by
    default. It can also be passed to the constructor.
  - Pagination: list_* methods return a single page (default per_page=200).
    iterate_* methods are generators that walk every page using the
    X-Paginator-* response headers.
  - supplier_code may contain multiple codes separated by whitespace,
    commas, or semicolons in supported accounts; helpers that involve
    supplier codes split on that union of separators.

Requires: `requests` (standard for HTTP). If unavailable, install with
`pip install --break-system-packages requests`.
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterator, Optional

import requests


BASE_URL = "https://www.vendus.co.ao/ws/v1.1"
DEFAULT_PER_PAGE = 200  # Tunable. Max allowed by the API is 1000.
DEFAULT_TIMEOUT = 30  # seconds

# In supported Vendus accounts, the `supplier_code` field on a product may
# contain multiple codes separated by whitespace, commas, or semicolons (or
# any mix). Split on the union and discard empty tokens.
_SUPPLIER_CODE_SEP = re.compile(r"[\s,;]+")


class VendusError(RuntimeError):
    """Raised for any non-2xx response from the Vendus API."""


class VendusClient:
    """Thin wrapper for queries and explicitly confirmed document creation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key or os.environ.get("VENDUS_API_KEY")
        if not self.api_key:
            raise VendusError(
                "Missing API key. Set VENDUS_API_KEY environment variable "
                "or pass api_key=... to VendusClient()."
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        # API key as Basic Auth user, no password — per Vendus docs.
        self._session.auth = (self.api_key, "")

    # ------------------------------------------------------------------ #
    # Low-level
    # ------------------------------------------------------------------ #
    def _get(
        self, path: str, params: Optional[dict] = None
    ) -> tuple[Any, dict]:
        """GET a path and return (parsed_json, response_headers)."""
        url = f"{self.base_url}{path}"
        resp = self._session.get(
            url, params=params or {}, timeout=self.timeout
        )
        if not resp.ok:
            raise VendusError(
                f"GET {path} failed with {resp.status_code}: "
                f"{resp.text[:500]}"
            )
        try:
            data = resp.json()
        except ValueError:
            raise VendusError(
                f"GET {path} returned non-JSON body: {resp.text[:200]}"
            )
        return data, resp.headers

    def _paginated(
        self,
        path: str,
        params: Optional[dict] = None,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> Iterator[Any]:
        """Yield items page by page. Uses X-Paginator-Pages."""
        params = dict(params or {})
        params["per_page"] = per_page
        page = 1
        while True:
            params["page"] = page
            data, headers = self._get(path, params=params)
            if not isinstance(data, list):
                # Single-object endpoints shouldn't end up here; bail out.
                yield data
                return
            for item in data:
                yield item
            total_pages = int(headers.get("X-Paginator-Pages", page))
            if page >= total_pages or not data:
                return
            page += 1

    # ------------------------------------------------------------------ #
    # Clients
    # ------------------------------------------------------------------ #
    def list_clients(self, **filters) -> list[dict]:
        """Single-page listing of clients. Pass any of: q, fiscal_id,
        name, email, external_reference, status, date, per_page, page.
        For full-account walks use iterate_clients()."""
        data, _ = self._get("/clients/", params=filters)
        return data if isinstance(data, list) else [data]

    def iterate_clients(self, **filters) -> Iterator[dict]:
        """Generator over every client matching the filters."""
        yield from self._paginated("/clients/", params=filters)

    def get_client(
        self, client_id: int, include_balance: bool = False
    ) -> dict:
        """Fetch a single client. With include_balance=True the response
        gains a `balance` block: {total, on_time, overdue}."""
        params = {"include_balance": "yes" if include_balance else "no"}
        data, _ = self._get(f"/clients/{client_id}/", params=params)
        return data

    def list_client_balance(
        self,
        client_id: int,
        since: Optional[str] = None,
        until: Optional[str] = None,
        status: Optional[str] = None,  # all | paid | unpaid
        aggregate: Optional[str] = None,  # yes | no
    ) -> list[dict]:
        """Customer current account / statement: every document affecting
        the customer's account in the given window. status='unpaid' is
        the most useful for collections work."""
        params: dict[str, Any] = {}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if status:
            params["status"] = status
        if aggregate:
            params["aggregate"] = aggregate
        return list(
            self._paginated(
                f"/clients/{client_id}/balance/", params=params
            )
        )

    # ------------------------------------------------------------------ #
    # Products
    # ------------------------------------------------------------------ #
    def list_products(self, **filters) -> list[dict]:
        """Single-page product list. Filters: q, ids, title, store_id,
        reference, barcode, category_id, brand_id, status, type."""
        data, _ = self._get("/products/", params=filters)
        return data if isinstance(data, list) else [data]

    def iterate_products(self, **filters) -> Iterator[dict]:
        """Walk the entire product catalogue."""
        yield from self._paginated("/products/", params=filters)

    def get_product(self, product_id: int) -> dict:
        """Full product detail including stock_store, variants, lots."""
        data, _ = self._get(f"/products/{product_id}/")
        return data

    def get_product_stock(self, product_id: int) -> dict:
        """Compact stock summary: {total, stores: [{store_id, stock,
        stock_alert}, ...]}. Cheaper than get_product() if you only need
        stock numbers."""
        data, _ = self._get(f"/products/stocks/{product_id}/")
        return data

    @staticmethod
    def parse_supplier_codes(supplier_code: Optional[str]) -> list[str]:
        """Split a product's supplier_code field into individual codes.

        In supported Vendus accounts a product may carry several supplier
        codes inside the same field, separated by any combination of
        whitespace, commas, or semicolons. Examples of valid raw
        values: "ABC123 DEF456", "ABC123,DEF456",
        "ABC123; DEF456", "ABC123 , DEF456".

        Returns the list of non-empty tokens with surrounding
        whitespace stripped. Order is preserved.
        """
        if not supplier_code:
            return []
        return [
            tok for tok in _SUPPLIER_CODE_SEP.split(supplier_code) if tok
        ]

    def find_products_by_supplier_code(
        self, code: str, case_sensitive: bool = False
    ) -> list[dict]:
        """Return every product whose supplier_code field contains
        `code` as a whole token (split on whitespace, commas, and/or
        semicolons — see parse_supplier_codes).

        Strategy:
          1. Coarse pre-filter via the API's free-text `q` param (this
             matches supplier_code substrings, which slashes the
             candidate set).
          2. Verify locally that `code` appears in the parsed token
             list. This rules out partial-substring false positives,
             e.g. searching for "ABC" should not match "ABC123".
        """
        needle = code if case_sensitive else code.lower()
        results: list[dict] = []
        for p in self.iterate_products(q=code):
            tokens = self.parse_supplier_codes(p.get("supplier_code"))
            if not case_sensitive:
                tokens = [t.lower() for t in tokens]
            if needle in tokens:
                results.append(p)
        return results

    # ------------------------------------------------------------------ #
    # Documents (invoices, receipts, credit notes, ...)
    # ------------------------------------------------------------------ #
    def create_document(self, payload: dict, *, confirmed: bool = False) -> dict:
        """Issue one document after user approval of this exact payload.

        Uses existing client/product IDs only, preventing implicit catalogue
        creation. Never retries: a failed response can hide a completed issue.
        See references/document-creation.md before calling.
        """
        if confirmed is not True:
            raise VendusError("Document creation requires explicit user confirmation.")
        if self.base_url != BASE_URL:
            raise VendusError("Document creation is restricted to the Vendus Angola API.")
        if not isinstance(payload, dict):
            raise VendusError("Document payload must be a dict.")
        allowed = {
            "type", "register_id", "mode", "external_reference", "tx_id",
            "date", "date_due", "date_supply", "notes", "stock_operation",
            "client", "items", "payments", "invoices", "movement_of_goods",
            "discount_amount", "discount_percentage",
        }
        if payload.keys() - allowed:
            raise VendusError("Unsupported document fields; consult the creation reference.")
        if not isinstance(payload.get("type"), str) or not payload["type"].strip():
            raise VendusError("Specify document type explicitly.")
        if type(payload.get("register_id")) is not int or payload["register_id"] <= 0:
            raise VendusError("Specify a positive integer register_id.")
        if payload.get("mode") not in ("normal", "tests"):
            raise VendusError("Specify mode='normal' or mode='tests' explicitly.")
        if not isinstance(payload.get("external_reference"), str) or not payload["external_reference"].strip():
            raise VendusError("A stable external_reference is required for reconciliation.")
        client = payload.get("client")
        if client is not None and (
            not isinstance(client, dict) or set(client) != {"id"}
            or type(client["id"]) is not int or client["id"] <= 0
        ):
            raise VendusError("Use only client={'id': existing_client_id}, or omit client.")
        items = payload.get("items")
        if payload["type"] == "RG":
            if "items" in payload or not payload.get("invoices") or not payload.get("payments"):
                raise VendusError("RG requires invoices and payments, and must omit items.")
        else:
            if not isinstance(items, list) or not items:
                raise VendusError("This document requires a non-empty items list.")
            item_fields = {
                "id", "qty", "gross_price", "discount_amount", "discount_percentage",
                "variant_id", "lot_id", "tax_id", "tax_exemption", "text", "serial",
                "reference_document",
            }
            for item in items:
                if (not isinstance(item, dict) or item.keys() - item_fields
                        or type(item.get("id")) is not int or item["id"] <= 0):
                    raise VendusError("Each item must use an existing product id and supported line fields.")
                try:
                    qty = float(item.get("qty", 0))
                except (TypeError, ValueError, OverflowError):
                    qty = 0
                if not 0 < qty < float("inf"):
                    raise VendusError("Each item requires a finite positive qty.")
                if payload["type"] == "NC":
                    ref = item.get("reference_document")
                    if not isinstance(ref, dict) or not ref.get("document_number") or not ref.get("document_row"):
                        raise VendusError("NC items require the original document_number and document_row.")
            if payload["type"] == "NC" and (
                not isinstance(payload.get("notes"), str) or not payload["notes"].strip()
            ):
                raise VendusError("NC requires notes explaining the reason.")
        try:
            resp = self._session.post(
                f"{BASE_URL}/documents/", json=payload,
                timeout=self.timeout, allow_redirects=False,
            )
            if resp.status_code != 201:
                raise VendusError(
                    f"Document POST returned HTTP {resp.status_code}. "
                    "Do not retry automatically; reconcile by external_reference."
                )
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise VendusError(
                "Document creation outcome is unknown. Do not retry; "
                "reconcile by external_reference in Vendus."
            ) from exc
        if not isinstance(data, dict) or not data.get("id"):
            raise VendusError(
                "Creation response has no document id. Do not retry; reconcile in Vendus."
            )
        return data

    def list_documents(self, **filters) -> list[dict]:
        """Single-page document list. Filters: store_id, register_id,
        client_id, client_fiscal_id, client_country, type (CSV ok),
        subtype, since, until, q, external_reference, status, view."""
        data, _ = self._get("/documents/", params=filters)
        return data if isinstance(data, list) else [data]

    def iterate_documents(self, **filters) -> Iterator[dict]:
        """Walk every document matching the filters. Use date filters
        for any non-trivial account — there can be tens of thousands."""
        yield from self._paginated("/documents/", params=filters)

    def get_document(self, document_id: int) -> dict:
        """Full document with items, taxes, payments, debt, related
        docs, hash, atcud, etc."""
        data, _ = self._get(f"/documents/{document_id}/")
        return data

    def list_document_types(
        self,
        visible_filter: Optional[str] = None,
        visible_finalize: Optional[str] = None,
    ) -> list[dict]:
        """The document types actually configured on this account."""
        params: dict[str, Any] = {}
        if visible_filter:
            params["visible_filter"] = visible_filter
        if visible_finalize:
            params["visible_finalize"] = visible_finalize
        data, _ = self._get("/documents/types/", params=params)
        return data if isinstance(data, list) else [data]

    def download_document_pdf(
        self, document_id: int, out_path: str
    ) -> str:
        """Download the PDF rendering of a document to disk and return
        the path. Read-only — this just retrieves an existing record."""
        url = f"{self.base_url}/documents/{document_id}.pdf"
        resp = self._session.get(
            url, params={"download": 1}, timeout=self.timeout
        )
        if not resp.ok:
            raise VendusError(
                f"PDF download failed: {resp.status_code} "
                f"{resp.text[:200]}"
            )
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path
