from unittest.mock import MagicMock, patch

import pytest

from scrapers.amazon import scrape

_URL = "https://www.amazon.com/dp/B0EXAMPLE123"
_STORE = "us"
_INSTOCK = "https://schema.org/InStock"
_OUTOFSTOCK = "https://schema.org/OutOfStock"


def _mock_response(html: str) -> MagicMock:
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


def _html(
    title: str | None = "Test Product",
    price_offscreen: str | None = "$99.99",
    availability: str | None = "In Stock",
    include_product_title: bool = True,
    jsonld_price: float | None = None,
    legacy_price: str | None = None,
) -> str:
    title_tag = f'<span id="productTitle">{title}</span>' if include_product_title and title else ""
    page_title = f"<title>{title} - Amazon.com</title>" if title else ""

    price_tag = ""
    if price_offscreen:
        price_tag = f'<span class="a-price"><span class="a-offscreen">{price_offscreen}</span></span>'

    avail_tag = ""
    if availability is not None:
        avail_tag = f'<div id="availability"><span>{availability}</span></div>'

    jsonld_tag = ""
    if jsonld_price is not None:
        jsonld_tag = f"""
        <script type="application/ld+json">
        {{"@type": "Product", "name": "{title}", "offers": {{"price": {jsonld_price}, "availability": "{_INSTOCK}"}}}}
        </script>
        """

    legacy_tag = ""
    if legacy_price:
        legacy_tag = f'<span id="priceblock_ourprice">{legacy_price}</span>'

    return f"""
    <html><head>{page_title}</head><body>
    {jsonld_tag}
    {title_tag}
    {price_tag}
    {legacy_tag}
    {avail_tag}
    </body></html>
    """


class TestAmazonScraper:
    def test_instock_with_price_and_name(self):
        with patch("scrapers.amazon.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html())
            result = scrape(_URL, _STORE)
        assert result.in_stock is True
        assert result.price == 99.99
        assert result.product_name == "Test Product"
        assert result.store_code == _STORE
        assert result.url == _URL

    def test_out_of_stock(self):
        with patch("scrapers.amazon.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html(availability="Out of Stock"))
            result = scrape(_URL, _STORE)
        assert result.in_stock is False

    def test_price_none_when_absent(self):
        with patch("scrapers.amazon.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html(price_offscreen=None))
            result = scrape(_URL, _STORE)
        assert result.price is None

    def test_no_availability_section_returns_out_of_stock(self):
        with patch("scrapers.amazon.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html(availability=None))
            result = scrape(_URL, _STORE)
        assert result.in_stock is False

    def test_http_error_propagates(self):
        with patch("scrapers.amazon.requests") as mock_req:
            mock_req.get.return_value = MagicMock(
                raise_for_status=MagicMock(side_effect=Exception("503 Service Unavailable"))
            )
            with pytest.raises(Exception, match="503"):
                scrape(_URL, _STORE)

    def test_name_falls_back_to_title_tag(self):
        html = _html(include_product_title=False)
        with patch("scrapers.amazon.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.product_name == "Test Product"

    def test_name_falls_back_to_url_when_no_title(self):
        html = "<html><body><div id='availability'><span>In Stock</span></div></body></html>"
        with patch("scrapers.amazon.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.product_name == _URL

    def test_price_from_jsonld(self):
        with patch("scrapers.amazon.requests") as mock_req:
            mock_req.get.return_value = _mock_response(
                _html(price_offscreen=None, jsonld_price=149.99)
            )
            result = scrape(_URL, _STORE)
        assert result.price == 149.99

    def test_price_falls_back_to_priceblock(self):
        html = _html(price_offscreen=None, legacy_price="$79.99")
        with patch("scrapers.amazon.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.price == 79.99

    def test_jsonld_array_picks_product_type(self):
        html = """
        <html><body>
        <script type="application/ld+json">
        [{"@type": "WebSite", "name": "Amazon"},
         {"@type": "Product", "name": "My Product",
          "offers": {"price": 42.0, "availability": "https://schema.org/InStock"}}]
        </script>
        <div id="availability"><span>In Stock</span></div>
        </body></html>
        """
        with patch("scrapers.amazon.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.price == 42.0
        assert result.product_name == "My Product"
