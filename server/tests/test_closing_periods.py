from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines, status="posted"):
    return client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description,
        "status": status, "lines": lines,
    })


def _setup(client, name="Close LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    return business, cash, revenue


def test_close_period(client):
    business, _, _ = _setup(client)
    response = client.post("/api/accounting/closing-periods", json={
        "business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31",
        "closed_by": "admin", "notes": "Q1 close",
    })
    assert response.status_code == 201
    cp = response.get_json()
    assert cp["period_start"] == "2026-01-01"
    assert cp["period_end"] == "2026-03-31"
    assert cp["closed_by"] == "admin"


def test_list_closing_periods(client):
    business, _, _ = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-04-01", "period_end": "2026-06-30"})
    periods = client.get(f"/api/accounting/closing-periods?business_id={business['id']}").get_json()
    assert len(periods) == 2
    assert periods[0]["period_end"] == "2026-06-30"  # most recent first


def test_closed_period_blocks_journal_entries(client):
    business, cash, revenue = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    response = _entry(client, business["id"], "2026-02-15", "Blocked entry", [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 100}])
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()


def test_open_period_allows_journal_entries(client):
    business, cash, revenue = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    response = _entry(client, business["id"], "2026-05-15", "Allowed entry", [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 100}])
    assert response.status_code == 201


def test_reopen_period(client):
    business, cash, revenue = _setup(client)
    cp = client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"}).get_json()
    # Entry should be blocked
    assert _entry(client, business["id"], "2026-02-15", "Blocked", [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 100}]).status_code == 400
    # Reopen
    response = client.delete(f"/api/accounting/closing-periods/{cp['id']}")
    assert response.status_code == 200
    # Entry should now be allowed
    response = _entry(client, business["id"], "2026-02-15", "Allowed now", [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 100}])
    assert response.status_code == 201


def test_duplicate_close_rejected(client):
    business, _, _ = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    response = client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    assert response.status_code == 400


def test_overlapping_periods_rejected(client):
    business, _, _ = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-06-30"})
    response = client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-04-01", "period_end": "2026-09-30"})
    assert response.status_code == 400


def test_check_period_closed(client):
    business, _, _ = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    closed = client.get(f"/api/accounting/closing-periods/check?business_id={business['id']}&entry_date=2026-02-15").get_json()
    assert closed["closed"] is True
    open_result = client.get(f"/api/accounting/closing-periods/check?business_id={business['id']}&entry_date=2026-06-15").get_json()
    assert open_result["closed"] is False


def test_closing_periods_isolated_per_business(client):
    first, _, _ = _setup(client, "First LLC")
    second, _, _ = _setup(client, "Second LLC")
    client.post("/api/accounting/closing-periods", json={"business_id": first["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    p1 = client.get(f"/api/accounting/closing-periods?business_id={first['id']}").get_json()
    p2 = client.get(f"/api/accounting/closing-periods?business_id={second['id']}").get_json()
    assert len(p1) == 1
    assert len(p2) == 0


def test_closing_periods_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/closing-periods?business_id=1").status_code == 401
    assert client.post("/api/accounting/closing-periods", json={}).status_code == 401
