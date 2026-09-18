"""Tenant isolation tests: users only reach businesses they were granted.

Model: ``user_business_access`` grants roles viewer < editor < owner per
business. Missing or foreign resources answer 404; insufficient role on an
accessible business answers 403.
"""
import pytest


def _register(client, username, password="pw12345", role=None):
    payload = {"username": username, "password": password}
    if role:
        payload["role"] = role
    client.post("/api/auth/register", json=payload)
    client.post("/api/auth/login", json={"username": username, "password": password})


def _make_business(client, name):
    response = client.post("/api/entities/businesses", json={"legal_name": name})
    assert response.status_code == 201
    return response.get_json()


def _make_account(client, business_id, code, account_type="asset"):
    response = client.post(
        "/api/accounting/accounts",
        json={"business_id": business_id, "code": code, "name": code, "account_type": account_type},
    )
    assert response.status_code == 201
    return response.get_json()


def _make_contact(client, business_id, name="Customer"):
    response = client.post(
        "/api/accounting/contacts",
        json={"business_id": business_id, "name": name, "contact_type": "customer"},
    )
    assert response.status_code == 201
    return response.get_json()


def _make_invoice(client, business_id, customer_id, receivable_id, revenue_id):
    response = client.post(
        "/api/accounting/invoices",
        json={
            "business_id": business_id,
            "customer_id": customer_id,
            "invoice_number": "INV-1",
            "issue_date": "2026-01-10",
            "due_date": "2026-02-10",
            "description": "Work",
            "amount": 100,
            "receivable_account_id": receivable_id,
            "revenue_account_id": revenue_id,
        },
    )
    assert response.status_code == 201
    return response.get_json()


def _make_expense(client, business_id, expense_account_id, cash_account_id):
    response = client.post(
        "/api/accounting/expenses",
        json={
            "business_id": business_id,
            "expense_date": "2026-01-20",
            "description": "Supplies",
            "amount": 50,
            "expense_account_id": expense_account_id,
            "payment_account_id": cash_account_id,
        },
    )
    assert response.status_code == 201
    return response.get_json()


def _make_entry(client, business_id, debit_account_id, credit_account_id):
    response = client.post(
        "/api/accounting/entries",
        json={
            "business_id": business_id,
            "entry_date": "2026-01-15",
            "description": "Entry",
            "lines": [
                {"account_id": debit_account_id, "debit": 100},
                {"account_id": credit_account_id, "credit": 100},
            ],
        },
    )
    assert response.status_code == 201
    return response.get_json()


def _create(client, url, payload):
    response = client.post(url, json=payload)
    assert response.status_code == 201, (url, response.get_json())
    return response.get_json()


def _two_tenants(app):
    """Return (client_a, business_a, client_b, business_b) for two users."""
    client_a = app.test_client()
    _register(client_a, "alice")
    business_a = _make_business(client_a, "Alpha LLC")

    client_b = app.test_client()
    _register(client_b, "bob")
    business_b = _make_business(client_b, "Beta LLC")
    return client_a, business_a, client_b, business_b


def _foreign_resources(client_b, business_id):
    """Create one record of every business-scoped kind inside tenant B."""
    res = {"business": business_id}
    cash = _make_account(client_b, business_id, "1000")
    revenue = _make_account(client_b, business_id, "4000", "revenue")
    expense_acct = _make_account(client_b, business_id, "5000", "expense")
    res["account"] = cash["id"]
    res["contact"] = _make_contact(client_b, business_id)["id"]
    res["invoice"] = _make_invoice(
        client_b, business_id, res["contact"], cash["id"], revenue["id"]
    )["id"]
    res["expense"] = _make_expense(
        client_b, business_id, expense_acct["id"], cash["id"]
    )["id"]
    res["journal_line"] = _make_entry(
        client_b, business_id, cash["id"], revenue["id"]
    )["lines"][0]["id"]
    res["budget"] = _create(client_b, "/api/accounting/budgets", {
        "business_id": business_id, "account_id": revenue["id"],
        "fiscal_year": 2026, "period": "annual", "budgeted_amount": 1000,
    })["id"]
    res["recurring"] = _create(client_b, "/api/accounting/recurring-expenses", {
        "business_id": business_id, "description": "Rent", "amount": 2000,
        "expense_account_id": expense_acct["id"],
        "payment_account_id": cash["id"], "frequency": "monthly",
        "start_date": "2026-02-01",
    })["id"]
    res["reconciliation"] = _create(client_b, "/api/accounting/reconciliations", {
        "business_id": business_id, "account_id": cash["id"],
        "statement_date": "2026-01-31", "statement_balance": 1000,
    })["id"]
    res["period"] = _create(client_b, "/api/accounting/closing-periods", {
        "business_id": business_id, "period_start": "2026-04-01",
        "period_end": "2026-06-30",
    })["id"]
    res["group"] = _create(client_b, "/api/accounting/account-groups", {
        "business_id": business_id, "name": "Assets", "account_type": "asset",
    })["id"]
    res["term"] = _create(client_b, "/api/accounting/payment-terms", {
        "business_id": business_id, "name": "Net 30", "net_days": 30,
    })["id"]
    res["credit"] = _create(client_b, "/api/accounting/credit-notes", {
        "business_id": business_id, "customer_id": res["contact"],
        "credit_number": "CN-1", "credit_date": "2026-01-15", "amount": 100,
        "receivable_account_id": cash["id"], "revenue_account_id": revenue["id"],
    })["id"]
    res["asset"] = _create(client_b, "/api/accounting/depreciation-assets", {
        "business_id": business_id, "name": "Server",
        "asset_account_id": cash["id"],
        "accumulated_account_id": expense_acct["id"],
        "depreciation_account_id": expense_acct["id"],
        "cost": 12000, "salvage_value": 0, "useful_life_months": 12,
        "method": "straight_line", "acquisition_date": "2026-01-01",
        "start_date": "2026-01-01",
    })["id"]
    res["project"] = _create(client_b, "/api/accounting/projects", {
        "business_id": business_id, "code": "P1", "name": "Project",
        "start_date": "2026-01-01",
    })["id"]
    res["tx"] = _create(client_b, "/api/accounting/bank-transactions", {
        "business_id": business_id, "account_id": cash["id"],
        "transaction_date": "2026-01-15", "amount": 500, "type": "deposit",
    })["id"]
    res["rate"] = _create(client_b, "/api/accounting/sales-tax-rates", {
        "business_id": business_id, "name": "State", "rate": 7.5,
    })["id"]
    res["po"] = _create(client_b, "/api/accounting/purchase-orders", {
        "business_id": business_id, "po_number": "PO-1",
        "order_date": "2026-01-15", "expense_account_id": expense_acct["id"],
        "payment_account_id": cash["id"],
        "lines": [{"description": "Supplies", "quantity": 2, "unit_price": 5}],
    })["id"]
    res["cost_center"] = _create(client_b, "/api/cost-centers", {
        "business_id": business_id, "code": "OPS", "name": "Ops",
    })["id"]
    res["item"] = _create(client_b, "/api/inventory/items", {
        "business_id": business_id, "sku": "W-1", "name": "Widget",
        "unit_cost": 5, "unit_price": 10,
    })["id"]
    res["payment"] = _create(client_b, "/api/tax/payments", {
        "business_id": business_id, "tax_type": "federal_estimated",
        "payment_date": "2026-03-15", "amount": 500,
        "period_start": "2026-01-01", "period_end": "2026-03-31",
    })["id"]
    res["usd"] = _create(client_b, "/api/currency/currencies", {
        "business_id": business_id, "code": "USD", "name": "Dollar",
        "is_base": True,
    })["id"]
    res["eur"] = _create(client_b, "/api/currency/currencies", {
        "business_id": business_id, "code": "EUR", "name": "Euro",
    })["id"]
    return res


def test_businesses_list_only_shows_accessible(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    assert [b["id"] for b in client_a.get("/api/entities/businesses").get_json()] == [business_a["id"]]
    assert [b["id"] for b in client_b.get("/api/entities/businesses").get_json()] == [business_b["id"]]


def test_cannot_read_foreign_business_collections(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    assert client_a.get(f"/api/accounting/accounts?business_id={business_b['id']}").status_code == 404
    assert client_a.get(f"/api/accounting/invoices?business_id={business_b['id']}").status_code == 404
    assert client_a.get(f"/api/accounting/expenses?business_id={business_b['id']}").status_code == 404
    assert client_a.get(f"/api/inventory/items?business_id={business_b['id']}").status_code == 404
    assert client_a.get(f"/api/cost-centers?business_id={business_b['id']}").status_code == 404
    assert client_a.get(f"/api/accounting/reports/profit-loss?business_id={business_b['id']}").status_code == 404


def test_cannot_write_to_foreign_business(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    response = client_a.post(
        "/api/accounting/accounts",
        json={"business_id": business_b["id"], "code": "9999", "name": "Nope", "account_type": "asset"},
    )
    assert response.status_code == 404
    response = client_a.post(
        "/api/cost-centers",
        json={"business_id": business_b["id"], "code": "X", "name": "Nope"},
    )
    assert response.status_code == 404


def test_idor_read_and_modify_foreign_records(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    receivable = _make_account(client_b, business_b["id"], "1100")
    revenue = _make_account(client_b, business_b["id"], "4000", "revenue")
    contact = _make_contact(client_b, business_b["id"])
    invoice = _make_invoice(client_b, business_b["id"], contact["id"], receivable["id"], revenue["id"])
    cost_center = client_b.post(
        "/api/cost-centers",
        json={"business_id": business_b["id"], "code": "OPS", "name": "Ops"},
    ).get_json()

    assert client_a.get(f"/api/accounting/invoices/{invoice['id']}").status_code == 404
    assert client_a.get(f"/api/accounting/invoices/{invoice['id']}/print").status_code == 404
    assert client_a.put(f"/api/accounting/invoices/{invoice['id']}/void").status_code == 404
    assert client_a.delete(f"/api/cost-centers/{cost_center['id']}").status_code == 404

    # The record still exists and is untouched for its owner.
    assert client_b.get(f"/api/accounting/invoices/{invoice['id']}").status_code == 200


def test_cross_tenant_resource_reference_rejected(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    foreign_account = _make_account(client_b, business_b["id"], "1000")
    own_credit = _make_account(client_a, business_a["id"], "4000", "revenue")

    response = client_a.post(
        "/api/accounting/entries",
        json={
            "business_id": business_a["id"],
            "entry_date": "2026-01-15",
            "description": "Sneaky entry",
            "lines": [
                {"account_id": foreign_account["id"], "debit": 10},
                {"account_id": own_credit["id"], "credit": 10},
            ],
        },
    )
    assert response.status_code == 404
    assert client_a.get(f"/api/accounting/entries?business_id={business_a['id']}").get_json() == []


def test_viewer_cannot_write_but_editor_can(app):
    client_a, business_a, client_b, _ = _two_tenants(app)

    # Grant bob viewer on Alpha LLC.
    response = client_a.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 2, "role": "viewer"},
    )
    assert response.status_code == 201

    assert client_b.get(f"/api/accounting/accounts?business_id={business_a['id']}").status_code == 200
    response = client_b.post(
        "/api/accounting/accounts",
        json={"business_id": business_a["id"], "code": "2000", "name": "Denied", "account_type": "asset"},
    )
    assert response.status_code == 403

    # Promote to editor: writes now succeed.
    response = client_a.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 2, "role": "editor"},
    )
    assert response.status_code == 201
    response = client_b.post(
        "/api/accounting/accounts",
        json={"business_id": business_a["id"], "code": "2000", "name": "Allowed", "account_type": "asset"},
    )
    assert response.status_code == 201

    # Revoke entirely: even reads are rejected.
    response = client_a.delete(f"/api/entities/businesses/{business_a['id']}/access/2")
    assert response.status_code == 200
    assert client_b.get(f"/api/accounting/accounts?business_id={business_a['id']}").status_code == 404


def test_non_owner_cannot_manage_access(app):
    client_a, business_a, client_b, _ = _two_tenants(app)
    client_a.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 2, "role": "viewer"},
    )
    # Bob is a viewer on Alpha: he cannot grant or revoke.
    response = client_b.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 2, "role": "owner"},
    )
    assert response.status_code == 403
    response = client_b.delete(f"/api/entities/businesses/{business_a['id']}/access/1")
    assert response.status_code == 403
    # Bob cannot even list Alpha's grants.
    assert client_b.get(f"/api/entities/businesses/{business_a['id']}/access").status_code == 403
    # Owner sees the grants.
    grants = client_a.get(f"/api/entities/businesses/{business_a['id']}/access").get_json()
    assert {g["user_id"] for g in grants} == {1, 2}


def test_cannot_revoke_last_owner(app):
    client_a, business_a, _, _ = _two_tenants(app)
    response = client_a.delete(f"/api/entities/businesses/{business_a['id']}/access/1")
    assert response.status_code == 400


def test_business_creation_grants_creator_owner(app):
    client = app.test_client()
    _register(client, "owner1")
    business = _make_business(client, "Mine LLC")
    grants = client.get(f"/api/entities/businesses/{business['id']}/access").get_json()
    assert grants[0]["role"] == "owner"


def test_dashboard_overview_excludes_foreign_businesses(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    _make_account(client_b, business_b["id"], "1000")
    _make_account(client_b, business_b["id"], "4000", "revenue")

    data = client_a.get("/api/dashboard/overview").get_json()
    assert data["counts"]["businesses"] == 1
    assert data["counts"]["accounts"] == 0

    _make_account(client_a, business_a["id"], "1000")
    data = client_a.get("/api/dashboard/overview").get_json()
    assert data["counts"]["accounts"] == 1


# --- Numeric-string and malformed identifier bypass attempts ---------------


def test_string_business_id_cannot_bypass_guard(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    response = client_a.post(
        "/api/accounting/accounts",
        json={
            "business_id": str(business_b["id"]),
            "code": "9999",
            "name": "Nope",
            "account_type": "asset",
        },
    )
    assert response.status_code == 404
    # Nothing was created in Bob's tenant.
    assert (
        client_b.get(
            f"/api/accounting/accounts?business_id={business_b['id']}"
        ).get_json()
        == []
    )


def test_chart_template_apply_with_string_business_id_denied(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    response = client_a.post(
        "/api/accounting/chart-templates/llc/apply",
        json={"business_id": str(business_b["id"])},
    )
    assert response.status_code == 404
    assert (
        client_b.get(
            f"/api/accounting/accounts?business_id={business_b['id']}"
        ).get_json()
        == []
    )


def test_string_encoded_foreign_ids_denied(app):
    """JSON numeric strings normalize before the access check: no id
    representation accepted by the service layer may bypass it."""
    client_a, business_a, client_b, business_b = _two_tenants(app)
    res = _foreign_resources(client_b, business_b["id"])

    a_cash = _make_account(client_a, business_a["id"], "1000")
    a_revenue = _make_account(client_a, business_a["id"], "4000", "revenue")
    a_tx = _create(client_a, "/api/accounting/bank-transactions", {
        "business_id": business_a["id"], "account_id": a_cash["id"],
        "transaction_date": "2026-01-15", "amount": 100, "type": "deposit",
    })

    attempts = [
        ("post", "/api/accounting/accounts",
         {"business_id": str(business_b["id"]), "code": "X", "name": "X",
          "account_type": "asset"}),
        ("post", "/api/accounting/entries", {
            "business_id": business_a["id"], "entry_date": "2026-01-16",
            "description": "x",
            "lines": [{"account_id": str(res["account"]), "debit": 10},
                      {"account_id": a_revenue["id"], "credit": 10}]}),
        ("post", "/api/accounting/entries", {
            "business_id": business_a["id"], "entry_date": "2026-01-16",
            "description": "x",
            "lines": [
                {"account_id": a_cash["id"], "debit": 10,
                 "cost_center_id": str(res["cost_center"])},
                {"account_id": a_revenue["id"], "credit": 10}]}),
        ("post", "/api/accounting/invoices", {
            "business_id": business_a["id"],
            "customer_id": str(res["contact"]), "invoice_number": "INV-X",
            "issue_date": "2026-01-10", "due_date": "2026-02-10",
            "description": "x", "amount": 10,
            "receivable_account_id": a_cash["id"],
            "revenue_account_id": a_revenue["id"]}),
        ("post", "/api/accounting/payments", {
            "invoice_id": str(res["invoice"]),
            "cash_account_id": a_cash["id"],
            "payment_date": "2026-01-20", "amount": 10}),
        ("put", f"/api/accounting/accounts/{a_cash['id']}/assign-group",
         {"group_id": str(res["group"])}),
        ("put", f"/api/accounting/bank-transactions/{a_tx['id']}/match",
         {"journal_line_id": str(res["journal_line"])}),
        ("post", "/api/inventory/movements", {
            "business_id": business_a["id"], "item_id": str(res["item"]),
            "movement_type": "purchase", "quantity": 1,
            "movement_date": "2026-01-20"}),
        ("post", "/api/currency/rates", {
            "business_id": business_a["id"],
            "from_currency_id": str(res["usd"]),
            "to_currency_id": str(res["eur"]),
            "rate": 1.1, "rate_date": "2026-01-01"}),
        ("post", "/api/accounting/expenses", {
            "business_id": business_a["id"], "expense_date": "2026-01-20",
            "description": "x", "amount": 10,
            "expense_account_id": str(res["account"]),
            "payment_account_id": a_cash["id"]}),
        ("post", "/api/cost-centers",
         {"business_id": str(business_b["id"]), "code": "X", "name": "X"}),
        ("post", "/api/tax/payments", {
            "business_id": str(business_b["id"]),
            "tax_type": "federal_estimated", "payment_date": "2026-03-15",
            "amount": 100, "period_start": "2026-01-01",
            "period_end": "2026-03-31"}),
    ]
    for method, url, payload in attempts:
        response = getattr(client_a, method)(url, json=payload)
        assert response.status_code in (403, 404), (method, url, response.get_json())

    # No rejected request mutated either tenant's data.
    assert (
        len(
            client_b.get(
                f"/api/accounting/accounts?business_id={business_b['id']}"
            ).get_json()
        )
        == 3
    )
    invoice = client_b.get(f"/api/accounting/invoices/{res['invoice']}").get_json()
    assert invoice["amount_paid"] == 0
    tx = client_a.get(
        f"/api/accounting/bank-transactions?business_id={business_a['id']}"
    ).get_json()[0]
    assert tx["matched_journal_line_id"] is None
    assert (
        client_a.get(
            f"/api/accounting/entries?business_id={business_a['id']}"
        ).get_json()
        == []
    )


def test_alternate_numeric_representations_denied(app):
    """Whitespace, signs, decimals and floats all resolve to the same id."""
    client_a, business_a, client_b, business_b = _two_tenants(app)
    bid = business_b["id"]
    for encoded in (f" {bid} ", f"{bid}.0", float(bid), f"0{bid}", f"+{bid}"):
        response = client_a.post(
            "/api/accounting/accounts",
            json={"business_id": encoded, "code": "X", "name": "X",
                  "account_type": "asset"},
        )
        assert response.status_code in (403, 404), encoded
    # Same for query strings, which are always textual.
    assert client_a.get(
        f"/api/accounting/accounts?business_id={bid}.0"
    ).status_code == 404


def test_malformed_identifiers_rejected(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    for bad in ("abc", "", True, {"id": 1}, [1]):
        response = client_a.post(
            "/api/accounting/accounts",
            json={"business_id": bad, "code": "X", "name": "X",
                  "account_type": "asset"},
        )
        assert response.status_code in (400, 403, 404), bad
    assert client_a.get(
        "/api/accounting/accounts?business_id=abc"
    ).status_code == 400


# --- Every direct-id route denies foreign records ---------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/accounting/invoices/{invoice}"),
        ("get", "/api/accounting/invoices/{invoice}/print"),
        ("put", "/api/accounting/invoices/{invoice}/void"),
        ("put", "/api/accounting/expenses/{expense}/approve"),
        ("put", "/api/accounting/expenses/{expense}/reject"),
        ("put", "/api/accounting/budgets/{budget}"),
        ("delete", "/api/accounting/budgets/{budget}"),
        ("put", "/api/accounting/recurring-expenses/{recurring}"),
        ("delete", "/api/accounting/recurring-expenses/{recurring}"),
        ("put", "/api/accounting/reconciliations/{reconciliation}"),
        ("delete", "/api/accounting/reconciliations/{reconciliation}"),
        ("delete", "/api/accounting/closing-periods/{period}"),
        ("get", "/api/accounting/statements/customer/{contact}"),
        ("get", "/api/accounting/statements/vendor/{contact}"),
        ("put", "/api/accounting/account-groups/{group}"),
        ("delete", "/api/accounting/account-groups/{group}"),
        ("put", "/api/accounting/accounts/{account}/assign-group"),
        ("put", "/api/accounting/payment-terms/{term}"),
        ("delete", "/api/accounting/payment-terms/{term}"),
        ("put", "/api/accounting/credit-notes/{credit}/void"),
        ("get", "/api/accounting/depreciation-assets/{asset}/schedule"),
        ("post", "/api/accounting/depreciation-assets/{asset}/post"),
        ("post", "/api/accounting/depreciation-assets/{asset}/dispose"),
        ("put", "/api/accounting/projects/{project}"),
        ("delete", "/api/accounting/projects/{project}"),
        ("get", "/api/accounting/projects/{project}/profitability"),
        ("put", "/api/accounting/bank-transactions/{tx}/match"),
        ("put", "/api/accounting/bank-transactions/{tx}/unmatch"),
        ("delete", "/api/accounting/bank-transactions/{tx}"),
        ("put", "/api/accounting/sales-tax-rates/{rate}"),
        ("delete", "/api/accounting/sales-tax-rates/{rate}"),
        ("put", "/api/accounting/purchase-orders/{po}/status"),
        ("delete", "/api/accounting/purchase-orders/{po}"),
        ("put", "/api/accounting/contacts/{contact}/1099"),
        ("put", "/api/inventory/items/{item}"),
        ("delete", "/api/inventory/items/{item}"),
        ("put", "/api/cost-centers/{cost_center}"),
        ("delete", "/api/cost-centers/{cost_center}"),
        ("delete", "/api/tax/payments/{payment}"),
        ("get", "/api/backup/export/{business}"),
    ],
)
def test_every_direct_id_route_denies_foreign_records(app, method, path):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    res = _foreign_resources(client_b, business_b["id"])
    url = path.format(**res)
    kwargs = {"json": {}} if method in ("post", "put") else {}
    response = getattr(client_a, method)(url, **kwargs)
    assert response.status_code in (403, 404), (method, url, response.status_code)


# --- Structural regression: future routes cannot silently bypass the guard --


TENANT_BLUEPRINTS = {
    "accounting", "inventory", "cost_centers", "currency", "dashboard",
    "tax", "backup",
}

# Route params that reference rows outside the tenant model: access grants
# (users) and taxpayer-scoped tax returns, which stay admin-gated.
NON_TENANT_ID_PARAMS = {"user_id", "return_id"}


def test_business_scoped_routes_stay_covered_by_guard(app):
    from access import FIELD_TO_TABLE, tenant_guard

    for name in TENANT_BLUEPRINTS:
        assert tenant_guard in app.before_request_funcs.get(name, []), (
            f"blueprint {name} lost its tenant_guard"
        )

    uncovered = []
    for rule in app.url_map.iter_rules():
        blueprint = rule.endpoint.split(".", 1)[0]
        if blueprint not in TENANT_BLUEPRINTS:
            continue
        for argument in rule.arguments:
            if (
                argument.endswith("_id")
                and argument not in set(FIELD_TO_TABLE) | NON_TENANT_ID_PARAMS
            ):
                uncovered.append(f"{rule} <{argument}>")
    assert not uncovered


def test_grant_access_to_nonexistent_user_is_controlled(app):
    client_a, business_a, _, _ = _two_tenants(app)
    response = client_a.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 9999, "role": "viewer"},
    )
    assert response.status_code == 400
    grants = client_a.get(
        f"/api/entities/businesses/{business_a['id']}/access"
    ).get_json()
    assert {g["user_id"] for g in grants} == {1}


def test_sole_owner_cannot_be_downgraded(app):
    client_a, business_a, _, _ = _two_tenants(app)
    for role in ("editor", "viewer"):
        response = client_a.post(
            f"/api/entities/businesses/{business_a['id']}/access",
            json={"user_id": 1, "role": role},
        )
        assert response.status_code == 400
    # She is still the owner afterwards.
    grants = client_a.get(
        f"/api/entities/businesses/{business_a['id']}/access"
    ).get_json()
    assert grants[0]["role"] == "owner"


def test_owner_downgrade_allowed_when_another_owner_remains(app):
    client_a, business_a, client_b, _ = _two_tenants(app)
    response = client_a.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 2, "role": "owner"},
    )
    assert response.status_code == 201

    response = client_a.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 1, "role": "editor"},
    )
    assert response.status_code == 201
    grants = {
        g["user_id"]: g["role"]
        for g in client_b.get(
            f"/api/entities/businesses/{business_a['id']}/access"
        ).get_json()
    }
    assert grants == {1: "editor", 2: "owner"}

    # The new sole owner can no longer be downgraded or revoked.
    assert client_b.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 2, "role": "viewer"},
    ).status_code == 400
    assert client_b.delete(
        f"/api/entities/businesses/{business_a['id']}/access/2"
    ).status_code == 400


def test_cannot_delete_sole_business_owner(app):
    admin = app.test_client()
    _register(admin, "root", role="admin")
    client_b = app.test_client()
    _register(client_b, "bob")
    business_b = _make_business(client_b, "Beta LLC")

    # Bob is the sole owner of Beta LLC: deleting him is blocked.
    response = admin.delete("/api/auth/users/2")
    assert response.status_code == 400
    users = {u["id"] for u in admin.get("/api/auth/users").get_json()}
    assert 2 in users

    # Once another owner exists, deletion is allowed again.
    response = client_b.post(
        f"/api/entities/businesses/{business_b['id']}/access",
        json={"user_id": 1, "role": "owner"},
    )
    assert response.status_code == 201
    assert admin.delete("/api/auth/users/2").status_code == 200
