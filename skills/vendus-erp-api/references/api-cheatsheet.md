# Vendus API — extra reference

This file is loaded only when needed. The main `SKILL.md` covers the four primary read paths (clients, client balance, products, documents). Read this when the user's question requires one of the secondary collections below.

Base URL: `https://www.vendus.co.ao/ws/v1.1/`. All endpoints listed here are read-only (`GET`).

## Stores — `GET /stores/`

Lookup table for store IDs that appear elsewhere (in `stock_store`, in document `store_id`, etc.). Returns `id`, `title`, address fields, and `status`.

## Registers (POS terminals) — `GET /registers/`

Filterable by `store_id`, `type` (`auto`, `pos`, `rest`, `api`, `office`, `rest_terminal`), and `isActive`. Use this when a user asks "which POS issued document X" — match `register_id` from the document to `id` here.

## Product categories — `GET /products/categories/`

Returns category tree: `id`, `title`, `parent_id`. Useful for filtering product lists by `category_id`.

## Product brands — `GET /products/brands/`

`id`, `title`. Useful for `brand_id` filters.

## Product variants — `GET /products/variants/`

For accounts that use variants (e.g. clothing with size/colour). Each product's `variants` block in `/products/{id}/` already includes the variant breakdown — only call this endpoint directly if the user asks about variant catalogues at the account level.

## Product lots — `GET /products/lots/`

For lot-controlled products (`lot_control = 1`). Returns lot title, status, expiration date, barcode. Cross-reference with the `lots` array on `/products/{id}/`.

## Price groups — `GET /products/pricegroups/`

`id`, `title`, `is_default`. The `prices` array on a product has one entry per price group. Use this to translate price-group IDs into human labels.

## Suppliers — `GET /suppliers/`

`id`, `fiscal_id`, `name`, address, contacts. **Distinct from the per-product `supplier_code` field.** If the user asks "list our suppliers" they want this endpoint. If they ask "products from supplier code XYZ" they want `find_products_by_supplier_code()` (see main SKILL.md).

## Document payment methods — `GET /documents/paymentmethods/`

`id`, `title` (e.g. "Dinheiro", "Multibanco"), and configuration flags. The `payments` array on a document detail references these by `id`.

## Document types — `GET /documents/types/`

Returns the document types active on this specific account. Always preferred over hard-coded type lists when the user asks "what document types are in use?".

## Taxes — `GET /taxes/`

The actual tax rates configured. Documents reference taxes by `id`/`code`; use this to translate `NOR`/`INT`/`RED`/`ISE`/`OUT` into the percentages and labels the account uses.

## Tax exemptions — `GET /taxes/exemptions/`

`code` (M01, M02, …, M99), `description`, `law`. The `tax_exemption` field on products and document items uses these codes.

## Account info — `GET /account/`

The account's own profile: company name, fiscal_id, address, country, default currency, etc. Useful as a sanity check and for displaying currency/locale to the user.

## Users — `GET /account/users/`

Account users / operators. Document detail includes `user_id`; resolve the operator name through this endpoint.

## Receipts — `GET /receipts/`

Convenience listing of `RG` (recibo) documents. Equivalent to `GET /documents/?type=RG` but presented as a receipts-first collection. Use whichever feels clearer for the user's question.

## Register balance — `GET /registers/{id}/balance/`

End-of-day balance per POS register. Read-only listing of historical Z-reports / opening-closing balances.

## SAFT-PT export — `GET /taxauthority/saft.doc`

Generates the SAFT-PT XML export for a date range. Triggered by tax authority requests. Note that running an export may be slow on large ranges — warn the user.

---

## Common pitfalls

1. **Empty `q`**: don't pass `q=""` — drop the param entirely.
2. **Date format**: always `YYYY-MM-DD` for `since`/`until`. Some endpoints accept `YYYY` or `YYYY-MM`; check the main SKILL.md per-endpoint.
3. **`status` semantics differ**:
   - On `/clients/`: `active` / `inactive`.
   - On `/products/`: `on` / `off` / `all`.
   - On `/documents/`: `N` / `A` / `F`.
   - On `/clients/{id}/balance/`: `all` / `paid` / `unpaid`.
4. **`type` on `/documents/`** accepts a comma-separated list — `type=FT,FR,NC` is valid.
5. **`view=detailed`** on `/documents/` returns more fields per row — but each row is heavier; only use when you actually need it.
6. **Localised account**: even though the host is `vendus.co.ao` (Angola), the underlying API is the same Portuguese-origin product. Field names and codes are in Portuguese; currencies and tax codes follow the configured account country.
