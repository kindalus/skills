---
name: vendus-erp-api
description: Read-only access to Vendus/Cegid Vendus invoicing and POS accounts on www.vendus.co.ao. Use when the user asks Vendus-backed questions about customers ("clientes"), customer current accounts / balance / debt / "saldo" / "conta corrente", products ("produtos", "artigos"), stock / inventory / "existências" / quantities per store, supplier codes / "código de fornecedor", invoices ("faturas"), receipts, credit notes, transport guides, sales documents, or other billing/inventory data. Trigger when the request has Vendus context, mentions vendus.co.ao, uses Vendus document numbers or document types such as "FT", "FR", "NC", "GT", "RG", asks for customer NIF/fiscal ID lookups, customer debt/balance, stock checks, invoice listings filtered by date / store / client, or supplier-code searches. Always query Vendus before answering these questions; do NOT answer from memory. Strictly READ-ONLY; never create, update, delete, cancel, or otherwise mutate Vendus records.
license: MIT
compatibility: Requires Python 3, requests, network access to https://www.vendus.co.ao, and a user-provided VENDUS_API_KEY.
---

# Vendus ERP API (Read-Only)

This skill lets Claude answer questions about customers, their current accounts, products, stock, and invoices stored in a Vendus (Cegid Vendus) account, by querying the Vendus REST API at `https://www.vendus.co.ao/ws/v1.1/`.

**This skill is strictly read-only.** Only `GET` requests are allowed. Never call `POST`, `PATCH`, `PUT`, or `DELETE` on any endpoint, regardless of how the user phrases the request. If the user explicitly asks to create or modify something, refuse politely and explain that this skill does not perform write operations — they should use the Vendus web interface for that.

## Quick start

1. Make sure the API key is available. The recommended location is the environment variable `VENDUS_API_KEY`. Check `os.environ.get("VENDUS_API_KEY")` first.
2. If the key isn't set, ask the user to provide it once for the session — never hard-code it in scripts and never echo it back in plain text in the response.
3. Use the helper module `scripts/vendus_client.py` (it handles auth, pagination, JSON decoding, and the supplier-code splitting). Import it and call the high-level functions instead of crafting raw HTTP every time.
4. After getting results, summarise them in clear natural language for the user. Show tables for lists, totals where they matter (e.g. balance), and the underlying IDs/numbers so the user can act on them in Vendus.

```python
import sys
sys.path.insert(0, "scripts")  # adjust to the skill folder path
from vendus_client import VendusClient

vc = VendusClient()  # picks up VENDUS_API_KEY automatically
clients = vc.list_clients(q="Alberto")
```

## Authentication

The API supports three equivalent methods. Pick the one that fits the call. The helper module uses HTTP Basic Auth by default.

| Method                        | Example                                                                             |
| ----------------------------- | ----------------------------------------------------------------------------------- |
| HTTP Basic Auth (recommended) | `curl -u API_KEY: https://www.vendus.co.ao/ws/v1.1/account/`                        |
| Bearer token                  | `curl -H "Authorization: Bearer API_KEY" https://www.vendus.co.ao/ws/v1.1/account/` |
| Query parameter               | `https://www.vendus.co.ao/ws/v1.1/account/?api_key=API_KEY`                         |

**Security**: never write the API key into shared artifacts, code samples that will be saved to the user's repo without their knowledge, or chat output. If you must show a request example, mask it as `API_KEY` or `***`.

## Pagination

Collection endpoints accept `per_page` (max **1000**, default **20**) and `page` (1-indexed). The response includes two HTTP headers:

- `X-Paginator-Items` — total number of items across all pages
- `X-Paginator-Pages` — total number of pages

Always use these to decide whether to keep fetching. The helper's `iterate_*` methods do this automatically. Prefer `per_page=1000` for batch jobs to minimise round-trips.

## Sorting

Some endpoints accept `sort` (comma-separated field list, prefix `-` for descending). Not every field is sortable — check the endpoint section before relying on it.

---

## Endpoints used by this skill

Base URL: `https://www.vendus.co.ao/ws/v1.1/`

### 1. Clients (customers) — `GET /clients/`

Lists customers. Supports filters:

| Param                | Type                               | Notes                                       |
| -------------------- | ---------------------------------- | ------------------------------------------- |
| `q`                  | string                             | Free-text search across name/fiscal_id/etc. |
| `fiscal_id`          | string                             | Exact NIF / fiscal ID                       |
| `name`               | string                             | Name match                                  |
| `email`              | string                             | Email match                                 |
| `external_reference` | string                             | External reference                          |
| `status`             | `active` \| `inactive`             |                                             |
| `date`               | `YYYY`, `YYYY-MM`, or `YYYY-MM-DD` | Creation date                               |
| `id[min]`, `id[max]` | int                                | ID range                                    |

**Important response fields**: `id`, `fiscal_id`, `external_reference`, `name`, `address`, `city`, `postalcode`, `phone`, `mobile`, `email`, `country`, `status`, `default_pay_due` (days), `price_group {id, title, is_default}`, `irs_retention`, `notes`, `date`.

#### Single client — `GET /clients/{id}/`

Pass `?include_balance=yes` to also receive a `balance` block:

```
balance: { total: 35.55, on_time: 20.00, overdue: 15.55 }
```

This is the **fastest way** to answer "what is customer X's current balance?" — one call, summary numbers included.

### 2. Customer current account / statement — `GET /clients/{id}/balance/`

Returns the line-by-line statement for a single customer (every document that affects their account). Filters:

| Param             | Notes                                                     |
| ----------------- | --------------------------------------------------------- |
| `since` / `until` | Date range, `YYYY-MM-DD`                                  |
| `status`          | `all` \| `paid` \| `unpaid`                               |
| `aggregate`       | `yes` \| `no` — aggregate accounts that share a fiscal_id |

**Important response fields per row**: `id`, `number` (e.g. `FT 01P2016/220`), `date`, `date_due`, `amount_gross`, `amount_net`, `type`, `subtype`, `status`, `total_unpaid`, `payment_status` (`paid` \| `pending` \| `expired`), `external_reference`, `operation_type` (`in` \| `out` \| `info`), `store_id`, `register_id`.

Use this endpoint when the user asks for an account statement, an aging report, what the customer still owes line-by-line, or the history of documents for a single customer. Use `/clients/{id}/?include_balance=yes` only when the user just wants the totals.

### 3. Products — `GET /products/`

Lists products. Filters:

| Param                     | Notes                                             |
| ------------------------- | ------------------------------------------------- |
| `q`                       | Searches title + reference + barcode              |
| `ids`                     | Comma-separated IDs                               |
| `title`                   | Title match                                       |
| `reference`               | Internal reference                                |
| `barcode`                 | Barcode                                           |
| `category_id`, `brand_id` | Filter by category/brand                          |
| `store_id`                | Filter to products available in a specific store  |
| `status`                  | `on` (default) \| `off` \| `all`                  |
| `type`                    | `all` \| `normal` \| `compound` \| `has_variants` |

**Important response fields**: `id`, `reference`, `barcode`, `supplier_code`, `title`, `description`, `gross_price`, `price_without_tax`, `supply_price`, `prices` (per price group), `unit_id`, `class_name`, `type_id`, `tax_id`, `category_id`, `brand_id`, `status`, `stock` (total), `stock_alert`, `stock_store` (collection: `{store, store_id, qty, alert}`), `variants`, `images`, `stores`, `lots`.

#### ⚠️ supplier_code may contain MULTIPLE codes

In Vendus accounts supported by this skill, the `supplier_code` field can hold **more than one supplier code separated by any of: whitespace, comma `,`, or semicolon `;`**. Real values you may encounter look like `"AHSG102X BSG999"`, `"AHSG102X,BSG999"`, `"AHSG102X; BSG999"`, or any mix of those. This is a local convention — the API itself treats the field as a single opaque string. Always handle it as follows:

- When **displaying** a product, split on `[\s,;]+` and show the codes as a list.
- When the user asks "which products have supplier code `XYZ`?", you cannot rely on a single API filter. The recommended pattern is:
  1. Use the API's free-text `q` param first as a coarse filter (it does match against `supplier_code`).
  2. Then in code, refine: keep only products where `XYZ` appears in the split-and-cleaned token list. The helper's `find_products_by_supplier_code(code)` already does this correctly (case-insensitive whole-token match against any of the three separators).
- When listing products for a supplier, build a deduplicated set by iterating with the helper rather than assuming one code per product.
- Never split on `,` or `;` alone — a code itself could conceivably contain other punctuation. Splitting on the union `[\s,;]+` and discarding empty tokens is the safe default.

#### Single product — `GET /products/{id}/`

Returns the same structure as the list response, plus the full `compound`, `variants`, `lots`, `modifiers`, and `stock_store` arrays. Use this for deep inspection.

### 4. Stock — `GET /products/stocks/{product_id}/`

Returns the stock for **one** product across stores:

```
{ "total": 155, "stores": [ { "store_id": 12345, "stock": 55, "stock_alert": 20 }, ... ] }
```

Note: when you have already fetched `/products/{id}/`, the `stock_store` field there contains the same per-store information plus the store name. Prefer that when the user asks about stock as part of a wider question about a product. Use `/products/stocks/{id}/` when the user only wants stock numbers and you want a smaller payload.

### 5. Documents (invoices, receipts, credit notes, …) — `GET /documents/`

Lists documents. Filters:

| Param                                | Notes                                               |
| ------------------------------------ | --------------------------------------------------- |
| `store_id`, `register_id`            | Scope to a specific store / POS                     |
| `client_id`                          | All documents for one customer                      |
| `client_fiscal_id`, `client_country` | Lookup by tax ID                                    |
| `type`                               | One or many comma-separated codes (see table below) |
| `subtype`                            | E.g. `G` for "Global"                               |
| `since` / `until`                    | Date range                                          |
| `q`                                  | Searches by document number, e.g. `01P2026/133`     |
| `external_reference`                 | External reference search                           |
| `status`                             | `N` Normal \| `A` Canceled \| `F` Invoiced          |
| `view`                               | `normal` \| `detailed`                              |

**Document type codes** (most relevant):

| Code | Meaning                           |
| ---- | --------------------------------- |
| `FT` | Fatura (invoice)                  |
| `FS` | Talão de Venda (sales slip)       |
| `FR` | Fatura Recibo (invoice + receipt) |
| `FG` | Fatura Global                     |
| `NC` | Nota de Crédito (credit note)     |
| `ND` | Nota de Débito (debit note)       |
| `RG` | Recibo (payment receipt)          |
| `GT` | Guia de Transporte                |
| `GR` | Guia de Remessa                   |
| `GD` | Guia de Devolução                 |
| `GA` | Guia de Ativos Próprios           |
| `PF` | Fatura Pró-Forma                  |
| `OT` | Orçamento (quote)                 |
| `EC` | Encomenda (order)                 |

For the live, account-specific list call `GET /documents/types/` (returns `{title, id, visible_filter, visible_finalize}` per type).

**List response fields per document**: `id`, `number`, `date`, `date_due`, `date_supply`, `system_time`, `local_time`, `amount_gross`, `amount_net`, `type`, `subtype`, `status`, `total_unpaid`, `payment_status` (`paid` \| `pending` \| `expired`), `external_reference`, `store_id`, `register_id`.

#### Single document — `GET /documents/{id}/`

Returns the full document including the `client` block, the `items` array (line-by-line), `taxes`, `discounts`, `payments`, `debt {total, paid, unpaid}`, `irs`, `movement_of_goods`, `related_docs`, plus `hash`, `atcud`, and `qrcode`. Use this when the user asks for the contents of a specific invoice ("what was on FT 01P2026/133?").

PDF: `GET /documents/{id}.pdf` returns a PDF rendering. With `?download=1` it downloads as an attachment. The helper exposes `download_document_pdf(id, path)`.

---

## Common workflows

### A) "How much does customer X owe us?"

```python
vc = VendusClient()
matches = vc.list_clients(q="X")     # narrow to one match
client = vc.get_client(matches[0]["id"], include_balance=True)
print(client["name"], client["balance"])
# -> {'total': 35.55, 'on_time': 20.00, 'overdue': 15.55}
```

If there are several matches, list them and ask the user which one. Never guess.

### B) "Show customer X's current account / statement, only what's unpaid"

```python
rows = vc.list_client_balance(client_id, status="unpaid")
# Each row: number, date, date_due, amount_gross, total_unpaid, payment_status, type
```

Render as a table sorted by `date_due`, with a final line summing `total_unpaid`.

### C) "How much stock do we have of product REF-001?"

```python
products = vc.list_products(reference="REF-001")
if not products:
    products = vc.list_products(q="REF-001")  # fallback
p = vc.get_product(products[0]["id"])
# Use p["stock_store"] -> [{store, store_id, qty, alert}, ...]
```

Always show per-store quantities, not just the total — multi-store accounts care.

### D) "Which products are below their stock alert in store 1234?"

```python
low = []
for p in vc.iterate_products(store_id=1234):
    for s in p.get("stock_store", []):
        if s["store_id"] == 1234 and s["alert"] and s["qty"] < s["alert"]:
            low.append((p["title"], p["reference"], s["qty"], s["alert"]))
```

This may require pagination across thousands of products — `iterate_products` handles it.

### E) "Find all products with supplier code AHSG102X"

```python
hits = vc.find_products_by_supplier_code("AHSG102X")
# Internally: pre-filters with q=AHSG102X, then verifies AHSG102X is one of
# the whitespace-separated tokens in product["supplier_code"]
```

### F) "List all invoices for customer 12345 in March 2026"

```python
docs = vc.list_documents(
    client_id=12345, type="FT",
    since="2026-03-01", until="2026-03-31",
)
```

Show `number`, `date`, `amount_gross`, `payment_status`, `total_unpaid`. Total at the bottom.

### G) "What was on invoice FT 01P2026/133?"

```python
hits = vc.list_documents(q="01P2026/133")
doc = vc.get_document(hits[0]["id"])
# doc["items"] -> line items with title, qty, gross_unit, gross_total, tax, etc.
```

---

## Reading & answering style

- For lists, default to a markdown table with the most useful columns. Keep it under ~25 rows on screen and tell the user the total count — offer to export the rest if they want a file.
- For money, show the currency the account uses (Vendus accounts on the `.co.ao` domain default to AOA / Kwanza but the API returns plain numbers — never assume a symbol you haven't seen in the data).
- Always include the human-readable document number (`number`) and the internal `id`. The user uses `number` to find things in Vendus; the `id` is what subsequent API calls need.
- When a request is ambiguous (e.g. multiple matching clients), list candidates and ask which one — don't guess.
- If pagination would be huge (>5 pages of 1000), warn the user and ask whether to continue, sample, or filter further before fetching.

## Things this skill must NOT do

- Never POST, PATCH, PUT or DELETE.
- Never create or update a client, product, document, payment, or stock movement.
- Never call `/documents/` with method `POST` to "draft" or "preview" a document.
- Never call any non-Vendus URL using the Vendus API key.
- Never store the API key in a file the user will share or commit.

If the user asks for any of the above, decline and tell them to do it directly in the Vendus web interface.

## Reference files

- `references/api-cheatsheet.md` — extra endpoint detail and field references for less common cases (variants, lots, brands, categories, payment methods, stores, registers). Read this only if the user asks something the main SKILL.md doesn't already cover.
- `scripts/vendus_client.py` — the Python helper. Read it once before using it so you understand the exact function signatures.
