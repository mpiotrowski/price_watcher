from unittest.mock import MagicMock, patch

import pytest

from scrapers.microcenter import _parse_price_string, scrape

_URL = "https://www.microcenter.com/product/123/test-gpu"
_STORE = "055"


def _mock_response(html: str) -> MagicMock:
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


def _html(
    name_h1: str | None = "Test GPU",
    jsonld_price: str | None = "299.99",
    jsonld_name: str | None = None,
    inventory_text: str | None = "5 in stock",
    title: str | None = None,
    extra_body: str = "",
) -> str:
    h1 = f"<h1>{name_h1}</h1>" if name_h1 else ""
    inventory = f'<div class="inventory">{inventory_text}</div>' if inventory_text is not None else ""
    title_tag = f"<title>{title}</title>" if title else ""

    if jsonld_price is not None:
        ld_name = jsonld_name or name_h1 or "Test GPU"
        jsonld = f"""
        <script type="application/ld+json">
        {{"@type": "Product", "name": "{ld_name}", "offers": {{"price": "{jsonld_price}"}}}}
        </script>"""
    else:
        jsonld = ""

    return f"""
    <html><head>{title_tag}</head><body>
    {h1}{jsonld}{inventory}{extra_body}
    </body></html>
    """


class TestParsePrice:
    def test_price_from_jsonld(self):
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html(jsonld_price="299.99"))
            result = scrape(_URL, _STORE)
        assert result.price == 299.99

    def test_price_from_itemprop_when_no_jsonld_offers(self):
        html = _html(
            jsonld_price=None,
            extra_body='<span itemprop="price" content="249.99">$249.99</span>',
        )
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.price == 249.99

    def test_price_from_css_selector_fallback(self):
        html = _html(jsonld_price=None, extra_body='<span id="pricing">$199.99</span>')
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.price == 199.99

    def test_price_none_when_all_sources_absent(self):
        html = _html(jsonld_price=None)
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.price is None

    def test_jsonld_offers_list_uses_first(self):
        html = """
        <html><body>
        <h1>Test GPU</h1>
        <script type="application/ld+json">
        {"@type": "Product", "name": "GPU", "offers": [{"price": "399.99"}, {"price": "450.00"}]}
        </script>
        <div class="inventory">5 in stock</div>
        </body></html>
        """
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.price == 399.99

    def test_jsonld_array_picks_product_type(self):
        html = """
        <html><body>
        <h1>Test GPU</h1>
        <script type="application/ld+json">
        [{"@type": "BreadcrumbList", "itemListElement": []},
         {"@type": "Product", "name": "Test GPU", "offers": {"price": "299.99"}}]
        </script>
        <div class="inventory">5 in stock</div>
        </body></html>
        """
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.price == 299.99


class TestParsePriceString:
    def test_dollar_sign_with_cents(self):
        assert _parse_price_string("$299.99") == 299.99

    def test_comma_thousands_separator(self):
        assert _parse_price_string("$1,299.99") == 1299.99

    def test_bare_float_string(self):
        assert _parse_price_string("299.99") == 299.99

    def test_integer_string(self):
        assert _parse_price_string("300") == 300.0

    def test_empty_string_returns_none(self):
        assert _parse_price_string("") is None

    def test_none_input_returns_none(self):
        assert _parse_price_string(None) is None

    def test_nonnumeric_text_returns_none(self):
        assert _parse_price_string("N/A") is None


class TestParseStock:
    def test_in_stock_text(self):
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html(inventory_text="5 in stock"))
            result = scrape(_URL, _STORE)
        assert result.in_stock is True

    def test_out_of_stock_text(self):
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html(inventory_text="Out of stock"))
            result = scrape(_URL, _STORE)
        assert result.in_stock is False

    def test_no_inventory_div_returns_false(self):
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html(inventory_text=None))
            result = scrape(_URL, _STORE)
        assert result.in_stock is False


class TestParseName:
    def test_name_from_h1(self):
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html(name_h1="RTX 4090"))
            result = scrape(_URL, _STORE)
        assert result.product_name == "RTX 4090"

    def test_name_from_jsonld_when_no_h1(self):
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(
                _html(name_h1=None, jsonld_name="GPU from JSON-LD")
            )
            result = scrape(_URL, _STORE)
        assert result.product_name == "GPU from JSON-LD"

    def test_name_from_title_strips_site_suffix(self):
        html = _html(name_h1=None, jsonld_price=None, title="Best GPU | MicroCenter")
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.product_name == "Best GPU"

    def test_name_falls_back_to_url(self):
        html = "<html><body><div class='inventory'>5 in stock</div></body></html>"
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(html)
            result = scrape(_URL, _STORE)
        assert result.product_name == _URL


class TestHTTPError:
    def test_raise_for_status_propagates(self):
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = MagicMock(
                raise_for_status=MagicMock(side_effect=Exception("404 Not Found"))
            )
            with pytest.raises(Exception, match="404"):
                scrape(_URL, _STORE)

    def test_store_code_set_as_cookie(self):
        with patch("scrapers.microcenter.requests") as mock_req:
            mock_req.get.return_value = _mock_response(_html())
            scrape(_URL, "055")
        mock_req.get.assert_called_once()
        _, kwargs = mock_req.get.call_args
        assert kwargs["cookies"]["storeSelected"] == "055"
