from unittest.mock import MagicMock, patch

import pytest

from scrapers.unifi import scrape

_URL = "https://store.ui.com/products/unifi-switch-pro-24"
_STORE = "online"
_INSTOCK = "https://schema.org/InStock"
_OUTOFSTOCK = "https://schema.org/OutOfStock"


def _mock_response(html: str) -> MagicMock:
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


def _html_product(
    name: str = "UniFi Switch Pro 24",
    availability: str = _INSTOCK,
    price: float | None = 499.0,
    use_price_spec: bool = True,
) -> str:
    if price is not None:
        if use_price_spec:
            price_part = f', "priceSpecification": {{"price": {price}}}'
        else:
            price_part = f', "price": {price}'
    else:
        price_part = ""

    return f"""
    <html><body>
    <script type="application/ld+json">
    {{
        "@type": "Product",
        "name": "{name}",
        "offers": {{"availability": "{availability}"{price_part}}}
    }}
    </script>
    </body></html>
    """


class TestUnifiScraper:
    def test_instock_with_price_spec(self):
        with patch("scrapers.unifi.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html_product())
            result = scrape(_URL, _STORE)
        assert result.in_stock is True
        assert result.price == 499.0
        assert result.product_name == "UniFi Switch Pro 24"
        assert result.store_code == _STORE
        assert result.url == _URL

    def test_out_of_stock(self):
        with patch("scrapers.unifi.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html_product(availability=_OUTOFSTOCK))
            result = scrape(_URL, _STORE)
        assert result.in_stock is False

    def test_no_jsonld_product_raises(self):
        html = "<html><body><h1>Nothing here</h1></body></html>"
        with patch("scrapers.unifi.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            with pytest.raises(ValueError, match="No JSON-LD"):
                scrape(_URL, _STORE)

    def test_price_falls_back_to_offers_price(self):
        with patch("scrapers.unifi.requests") as mock_req:
            mock_req.get.return_value = _mock_response(
                _html_product(use_price_spec=False)
            )
            result = scrape(_URL, _STORE)
        assert result.price == 499.0

    def test_price_none_when_absent(self):
        with patch("scrapers.unifi.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html_product(price=None))
            result = scrape(_URL, _STORE)
        assert result.price is None

    def test_jsonld_array_picks_product_type(self):
        html = """
        <html><body>
        <script type="application/ld+json">
        [{"@type": "WebSite", "name": "Unifi Store"},
         {"@type": "Product", "name": "Switch Pro",
          "offers": {"availability": "https://schema.org/InStock", "price": 199.0}}]
        </script>
        </body></html>
        """
        with patch("scrapers.unifi.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.product_name == "Switch Pro"
        assert result.price == 199.0

    def test_http_error_propagates(self):
        with patch("scrapers.unifi.requests") as mock_req:
            mock_req.get.return_value = MagicMock(
                raise_for_status=MagicMock(side_effect=Exception("503 Service Unavailable"))
            )
            with pytest.raises(Exception, match="503"):
                scrape(_URL, _STORE)
