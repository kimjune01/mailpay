"""Test mailto: URL and checkout link generation."""

from mailpay import mailto_url, checkout_link, qr_data


def test_mailto_basic():
    url = mailto_url(to_addr="shop@store.com")
    assert url == "mailto:shop%40store.com"


def test_mailto_with_task():
    url = mailto_url(
        to_addr="agent@example.com",
        task={"task": "translate", "text": "hello"},
        subject="Translation request",
    )
    assert "mailto:agent%40example.com?" in url
    assert "subject=Translation%20request" in url
    assert "translate" in url


def test_mailto_with_payment():
    url = mailto_url(
        to_addr="shop@store.com",
        task={"task": "purchase", "item": "widget"},
        payment_amount=50000,
        payment_token="0xUSDC",
        payment_network="base",
    )
    assert "mailto:shop%40store.com?" in url
    assert "0.05" in url  # 50000 / 1_000_000
    assert "USDC" in url


def test_checkout_link():
    url = checkout_link(
        to_addr="shop@store.com",
        items=[{"name": "widget", "qty": 1}],
        payment_amount=100000,
        order_id="#417",
    )
    assert "mailto:shop%40store.com?" in url
    assert "Order" in url
    assert "widget" in url


def test_qr_data_is_mailto():
    data = qr_data(
        to_addr="agent@example.com",
        task={"task": "ping"},
        payment_amount=1000,
    )
    assert data.startswith("mailto:")
