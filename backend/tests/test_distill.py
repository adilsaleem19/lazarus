"""Tests for DOM distillation: noise stripping, repeat collapsing, budgets, structure detection."""

from app.ingestion.distill import distill

CARD = '<div class="card"><h3>Product {i}</h3><a href="/p/{i}">Details</a></div>'


def page(body: str, head: str = "") -> str:
    head_html = f"<head><title>Test Page</title>{head}</head>"
    return f"<!doctype html><html>{head_html}<body>{body}</body></html>"


def cards(n: int) -> str:
    return '<div id="grid">' + "".join(CARD.format(i=i) for i in range(n)) + "</div>"


class TestNoiseStripping:
    def test_strips_scripts_styles_svg_noscript(self):
        html = page(
            "<script>var secret = 1;</script>"
            "<style>.x{color:red}</style>"
            '<svg viewBox="0 0 1 1"><path d="M0 0"/></svg>'
            "<noscript>enable js</noscript>"
            "<h1>Visible</h1>"
        )
        result = distill(html)
        assert "secret" not in result.skeleton
        assert "color:red" not in result.skeleton
        assert "svg" not in result.skeleton.lower()
        assert "enable js" not in result.skeleton
        assert "Visible" in result.skeleton

    def test_strips_base64_data_uris_and_inline_style_attrs(self):
        html = page(
            '<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==" alt="logo">'
            '<div style="background:url(x.png);color:blue">Styled text</div>'
        )
        result = distill(html)
        assert "base64" not in result.skeleton
        assert "iVBORw0" not in result.skeleton
        assert "color:blue" not in result.skeleton
        assert "Styled text" in result.skeleton

    def test_strips_html_comments(self):
        html = page("<!-- hidden note --><p>Shown</p>")
        result = distill(html)
        assert "hidden note" not in result.skeleton
        assert "Shown" in result.skeleton


class TestStructurePreservation:
    def test_preserves_headings_links_ids_and_classes(self):
        html = page('<h2 id="news" class="section-title">Latest</h2><a href="/story/1">Story</a>')
        result = distill(html)
        assert "news" in result.skeleton
        assert "section-title" in result.skeleton
        assert "/story/1" in result.skeleton
        assert "Latest" in result.skeleton

    def test_truncates_long_text_nodes(self):
        long_text = "word " * 200
        html = page(f"<p>{long_text}</p>")
        result = distill(html)
        assert long_text.strip() not in result.skeleton
        assert "word" in result.skeleton


class TestRepeatCollapsing:
    def test_collapses_many_repeated_siblings_to_samples(self):
        result = distill(page(cards(12)))
        # keeps a couple of samples, not all 12
        assert result.skeleton.count('class="card"') <= 3
        assert "Product 0" in result.skeleton
        # a marker communicates how many were collapsed
        assert "more" in result.skeleton

    def test_few_siblings_are_not_collapsed(self):
        result = distill(page(cards(2)))
        assert result.skeleton.count('class="card"') == 2


class TestStructureDetection:
    def test_detects_table_with_columns_and_row_count(self):
        rows = "".join(f"<tr><td>Co {i}</td><td>{i}00</td></tr>" for i in range(8))
        html = page(
            '<table id="stocks"><thead><tr><th>Company</th><th>Price</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )
        result = distill(html)
        tables = [s for s in result.structures if s["type"] == "table"]
        assert len(tables) == 1
        assert tables[0]["columns"] == ["Company", "Price"]
        assert tables[0]["row_count"] == 8

    def test_detects_repeated_card_pattern(self):
        result = distill(page(cards(12)))
        patterns = [s for s in result.structures if s["type"] == "repeated_pattern"]
        assert any(p["count"] == 12 and "card" in p["selector"] for p in patterns)

    def test_no_structures_on_plain_page(self):
        result = distill(page("<h1>Hello</h1><p>One paragraph.</p>"))
        assert result.structures == []


class TestMetaExtraction:
    def test_extracts_title_description_and_og_tags(self):
        head = (
            '<meta name="description" content="A test page.">'
            '<meta property="og:title" content="OG Title">'
        )
        result = distill(page("<p>x</p>", head=head))
        assert result.meta["title"] == "Test Page"
        assert result.meta["description"] == "A test page."
        assert result.meta["og:title"] == "OG Title"


class TestTokenBudget:
    def test_reports_token_estimate(self):
        result = distill(page("<p>Hello world</p>"))
        assert result.token_estimate > 0

    def test_respects_max_tokens_on_huge_pages(self):
        rows = "".join(f'<div class="row-{i}"><p>{"text " * 50}</p></div>' for i in range(500))
        huge = page(rows)
        result = distill(huge, max_tokens=1000)
        assert result.token_estimate <= 1000

    def test_handles_empty_html(self):
        result = distill("")
        assert result.skeleton == ""
        assert result.structures == []
