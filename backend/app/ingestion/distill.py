"""DOM distillation: compress a page into a structural skeleton an LLM can afford to read.

Three independent outputs from one parse:
- skeleton: noise-stripped, repeat-collapsed HTML kept under a token budget
- structures: detected tables and repeated element patterns (cards, list items)
- meta: title/description/OpenGraph tags
"""

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from selectolax.parser import HTMLParser, Node

SKIP_TAGS = {
    "script", "style", "svg", "noscript", "template", "iframe", "canvas",
    "object", "embed", "link", "meta", "source", "track", "audio", "video", "head",
}
VOID_TAGS = {"img", "br", "hr", "input", "wbr", "col"}
KEEP_ATTRS = {
    "id", "class", "href", "src", "role", "datetime", "alt",
    "type", "name", "value", "action", "placeholder",
}
# Repeats of these are structural noise (tables are detected separately).
NON_PATTERN_TAGS = {"tr", "td", "th", "thead", "tbody", "tfoot", "option", "br", "hr", "col"}
COLLAPSE_THRESHOLD = 4
TRUNCATION_MARKER = "<!-- truncated to fit token budget -->"


@dataclass(frozen=True)
class RenderProfile:
    samples: int = 2
    text_max: int = 120
    attr_max: int = 100


@dataclass
class Distilled:
    skeleton: str
    token_estimate: int
    meta: dict[str, str]
    structures: list[dict]


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def _children(node: Node) -> Iterator[Node]:
    child = node.child
    while child is not None:
        yield child
        child = child.next


def _is_element(node: Node) -> bool:
    return not node.tag.startswith(("-", "_", "!"))


def _signature(node: Node) -> tuple[str, tuple[str, ...]]:
    class_attr = (node.attributes or {}).get("class") or ""
    return (node.tag, tuple(sorted(class_attr.split())))


def _selector(signature: tuple[str, tuple[str, ...]]) -> str:
    tag, classes = signature
    return tag + "".join(f".{c}" for c in classes)


def _norm_text(raw: str, limit: int) -> str:
    text = " ".join(raw.split())
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _render_attrs(node: Node, profile: RenderProfile) -> str:
    parts = []
    for key, value in (node.attributes or {}).items():
        if key not in KEEP_ATTRS:
            continue
        value = value or ""
        if value.startswith("data:"):
            continue
        if len(value) > profile.attr_max:
            value = value[: profile.attr_max] + "…"
        parts.append(f' {key}="{value}"')
    return "".join(parts)


def _render(node: Node, profile: RenderProfile, out: list[str]) -> None:
    elements = [c for c in _children(node) if _is_element(c)]
    counts = Counter(_signature(c) for c in elements)
    emitted: Counter = Counter()

    for child in _children(node):
        if child.tag == "-text":
            text = _norm_text(child.text(deep=True), profile.text_max)
            if text:
                out.append(text)
            continue
        if not _is_element(child) or child.tag in SKIP_TAGS:
            continue

        signature = _signature(child)
        if counts[signature] >= COLLAPSE_THRESHOLD:
            emitted[signature] += 1
            if emitted[signature] == profile.samples + 1:
                remaining = counts[signature] - profile.samples
                out.append(f"<!-- +{remaining} more {_selector(signature)} -->")
            if emitted[signature] > profile.samples:
                continue

        out.append(f"<{child.tag}{_render_attrs(child, profile)}>")
        if child.tag not in VOID_TAGS:
            _render(child, profile, out)
            out.append(f"</{child.tag}>")


def _extract_meta(tree: HTMLParser) -> dict[str, str]:
    meta: dict[str, str] = {}
    title = tree.css_first("title")
    if title is not None:
        text = _norm_text(title.text(deep=True), 200)
        if text:
            meta["title"] = text
    for node in tree.css("meta"):
        attrs = node.attributes or {}
        name = (attrs.get("name") or attrs.get("property") or "").lower()
        content = attrs.get("content")
        if not name or content is None:
            continue
        if name in {"description", "author", "keywords"} or name.startswith(
            ("og:", "twitter:", "article:")
        ):
            meta[name] = _norm_text(content, 300)
    return meta


def _detect_tables(tree: HTMLParser) -> list[dict]:
    detected = []
    for table in tree.css("table"):
        header_cells = table.css("thead th")
        rows = table.css("tbody tr")
        if header_cells:
            columns = [_norm_text(c.text(deep=True), 60) for c in header_cells]
            row_count = len(rows) if rows else max(0, len(table.css("tr")) - 1)
        else:
            all_rows = table.css("tr")
            if not all_rows:
                continue
            first_ths = all_rows[0].css("th")
            if first_ths:
                columns = [_norm_text(c.text(deep=True), 60) for c in first_ths]
                row_count = len(all_rows) - 1
            else:
                columns = [f"col_{i}" for i in range(len(all_rows[0].css("td")))]
                row_count = len(all_rows)
        table_id = (table.attributes or {}).get("id")
        selector = f"table#{table_id}" if table_id else "table"
        detected.append(
            {"type": "table", "selector": selector, "columns": columns, "row_count": row_count}
        )
    return detected


def _detect_patterns(body: Node) -> list[dict]:
    detected = []
    stack = [body]
    while stack:
        node = stack.pop()
        elements = [
            c
            for c in _children(node)
            if _is_element(c) and c.tag not in SKIP_TAGS and c.tag not in NON_PATTERN_TAGS
        ]
        counts = Counter(_signature(c) for c in elements)
        for signature, count in counts.items():
            if count >= COLLAPSE_THRESHOLD:
                detected.append(
                    {
                        "type": "repeated_pattern",
                        "selector": _selector(signature),
                        "count": count,
                    }
                )
        stack.extend(elements)
    return detected


def distill(html: str, max_tokens: int = 8000) -> Distilled:
    if not html or not html.strip():
        return Distilled(skeleton="", token_estimate=0, meta={}, structures=[])

    tree = HTMLParser(html)
    meta = _extract_meta(tree)
    body = tree.body
    if body is None:
        return Distilled(skeleton="", token_estimate=0, meta=meta, structures=[])

    structures = _detect_tables(tree) + _detect_patterns(body)

    skeleton = ""
    profiles = (RenderProfile(), RenderProfile(samples=1, text_max=60, attr_max=50))
    for profile in profiles:
        out: list[str] = []
        _render(body, profile, out)
        skeleton = "".join(out)
        if estimate_tokens(skeleton) <= max_tokens:
            break

    if estimate_tokens(skeleton) > max_tokens:
        keep = max(0, max_tokens * 4 - len(TRUNCATION_MARKER))
        skeleton = skeleton[:keep] + TRUNCATION_MARKER

    return Distilled(
        skeleton=skeleton,
        token_estimate=estimate_tokens(skeleton),
        meta=meta,
        structures=structures,
    )
