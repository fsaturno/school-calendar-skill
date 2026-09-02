#!/usr/bin/env python3
"""Fetch and mechanically clean a school webpage for Claude to read.

This script deliberately does NOT try to parse out term dates itself — real
school websites are built on wildly different CMSs (WordPress tables, PDF
attachments, JS-rendered pages, embedded Google Calendar JSON, plain prose
paragraphs...) and no fixed set of selectors/regexes generalizes across them.
Instead this script does only mechanical, deterministic work:

  - fetch the raw HTML (a real browser User-Agent, since some school sites
    block default python-requests UAs)
  - flatten <table> markup into readable pipe-delimited rows so tabular term
    dates read naturally as text
  - strip navigation/header/footer/script/style noise for a clean text body
  - enumerate every PDF link and every "this might be the term dates page"
    link, regardless of CSS visibility (a link inside a collapsed accordion
    is still present in the server HTML and still worth surfacing)
  - scan <script> tags for embedded date-shaped data before discarding them
    (some "JS-rendered" pages actually embed the real calendar data as a
    plain JSON/array literal, e.g. an embedded Google Calendar widget - that
    data doesn't need real JS execution to read, just needs to not be
    thrown away by a naive "strip all <script> tags" cleaner)
  - flag when the page honestly looks like it needs JavaScript to render its
    main content, so the calling skill can fall back honestly rather than
    silently returning nothing

Claude then reads `cleaned_text` (and `embedded_script_data`, and any PDF
text via extract_pdf_text.py) and does the actual semantic extraction of
term dates, using its own language understanding - this is what lets the
skill generalize to school websites it has never seen.

Usage:
    python3 fetch_page.py --url <url> [--mode page|crawl]

`--mode crawl` doesn't change the underlying fetch/clean logic at all - it
only signals to the caller "read links.keyword_links first, this is a
homepage, we're looking for the term-dates page" rather than "read
cleaned_text first, this should already be the term-dates page".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20

# Keyword -> relevance weight, used both to spot document/page links worth
# surfacing and to rank homepage-crawl candidates. More specific phrases
# score higher than generic ones so "Term Dates" beats an incidental
# "calendar" mention in an unrelated nav link. Deliberately NOT including
# bare generic words like "parents"/"information"/"events"/"diary" - those
# appear in nearly every school's main nav regardless of term dates, and
# would flood candidates with false positives for very little recall gain.
KEYWORDS = {
    "term dates": 100,
    "term times": 95,
    "academic calendar": 90,
    "school calendar": 85,
    "key dates": 80,
    "calendar and term dates": 100,
    "holiday dates": 75,
    "diary dates": 70,
    "important dates": 60,
    "calendar": 40,
    "dates": 25,
}

# File extensions worth surfacing as their own document type, in rough order
# of how directly usable they are once found: an .ics feed needs no
# extraction at all (the school already published structured data), PDFs
# and Word docs need text extraction (extract_pdf_text.py / extract_docx_text.py).
DOCUMENT_EXTENSIONS = {
    ".ics": "ics_links",
    ".pdf": "pdf_links",
    ".docx": "docx_links",
    ".doc": "docx_links",
}

NOISE_TAGS = ["script", "style", "noscript", "svg", "header", "nav", "footer"]

# A page's real content is very unlikely to have zero dates in a term-dates
# context; a very low visible-text/raw-HTML ratio combined with no PDF or
# embedded-data leads is the signal that a page needs JavaScript to render.
JS_RENDER_RATIO_THRESHOLD = 0.02
JS_RENDER_MIN_TEXT_LENGTH = 400

# Embedded <script> data blobs (e.g. an embedded Google Calendar widget) are
# recognized by containing several date-shaped tokens, not by trying to
# fully parse arbitrary JS.
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{8}T\d{6}\b")
_SCRIPT_DATA_MIN_MATCHES = 3
_SCRIPT_DATA_MAX_CHARS = 4000


def fetch(url: str) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"}
    return requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)


def _is_in_hidden_container(tag) -> bool:
    """Best-effort check for whether a tag sits inside something a human
    wouldn't see without clicking (e.g. a collapsed accordion body). This is
    informational only - we never filter these out, since the content is
    genuinely present in the server HTML (confirmed against a real
    Bootstrap-accordion school site) and BeautifulSoup has no concept of
    "visible", only what a browser's CSS engine would later hide.
    """
    for ancestor in tag.parents:
        if not hasattr(ancestor, "get"):
            continue
        classes = " ".join(ancestor.get("class", []) or [])
        style = ancestor.get("style", "") or ""
        if "collapse" in classes or "accordion" in classes or "display:none" in style.replace(" ", ""):
            return True
    return False


def _document_bucket(href_lower: str) -> str | None:
    path_only = href_lower.split("?")[0]
    for ext, bucket in DOCUMENT_EXTENSIONS.items():
        if path_only.endswith(ext):
            return bucket
    if "type=pdf" in href_lower:  # e.g. Juniper CMS's download.asp?file=31&type=pdf
        return "pdf_links"
    return None


def _extract_links(soup: BeautifulSoup, base_url: str) -> dict:
    buckets: dict[str, list] = {name: [] for name in set(DOCUMENT_EXTENSIONS.values())}
    seen_doc_urls: set[str] = set()
    keyword_links = []
    seen_keyword_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("mailto:") or href.lower().startswith("tel:"):
            continue
        resolved = urljoin(base_url, href)
        link_text = a.get_text(" ", strip=True)
        haystack = f"{link_text} {href}".lower()

        bucket = _document_bucket(href.lower())
        if bucket:
            if resolved not in seen_doc_urls:
                seen_doc_urls.add(resolved)
                # Some sites (e.g. icon-only accordion links) carry no link
                # text at all - fall back to the filename, which is often
                # the only clue distinguishing e.g. "2025-2026" from
                # "2026-27" when several years' documents are listed.
                filename_guess = unquote(urlparse(resolved).path.rsplit("/", 1)[-1])
                buckets[bucket].append({
                    "href": href,
                    "resolved_url": resolved,
                    "link_text": link_text or filename_guess,
                    "in_hidden_container": _is_in_hidden_container(a),
                })
            continue

        best_score = 0
        matched_keyword = None
        for kw, weight in KEYWORDS.items():
            if kw in haystack and weight > best_score:
                best_score = weight
                matched_keyword = kw
        if matched_keyword and resolved not in seen_keyword_urls:
            seen_keyword_urls.add(resolved)
            keyword_links.append({
                "href": href,
                "resolved_url": resolved,
                "link_text": link_text or "(no link text)",
                "matched_keyword": matched_keyword,
                "score": best_score,
            })

    keyword_links.sort(key=lambda x: -x["score"])
    return {**buckets, "keyword_links": keyword_links}


def _extract_embedded_script_data(soup: BeautifulSoup) -> list[dict]:
    """Find <script> blocks that look like they contain real date/event data
    (e.g. an embedded Google Calendar widget's event JSON), so this doesn't
    get thrown away when <script> tags are stripped for the clean text body.
    """
    found = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        if not text.strip():
            continue
        matches = _ISO_DATE_RE.findall(text)
        if len(matches) >= _SCRIPT_DATA_MIN_MATCHES:
            snippet = text.strip()
            if len(snippet) > _SCRIPT_DATA_MAX_CHARS:
                snippet = snippet[:_SCRIPT_DATA_MAX_CHARS] + "\n... (truncated)"
            found.append({
                "date_token_count": len(matches),
                "snippet": snippet,
            })
    return found


def _table_to_text(table) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [c.get_text(" ", strip=True) for c in cells]
        if any(cell_texts):
            rows.append(" | ".join(cell_texts))
    return "\n".join(rows)


def _clean_text_body(soup: BeautifulSoup) -> str:
    # Flatten tables innermost-first so nested tables don't get double
    # counted or fail to detach cleanly.
    for table in reversed(soup.find_all("table")):
        table.replace_with(NavigableString("\n" + _table_to_text(table) + "\n"))

    for tag_name in NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    text = soup.get_text("\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    # Collapse accidental duplicate consecutive lines (common with nav menus
    # repeated in mobile+desktop markup variants).
    deduped = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--mode", choices=["page", "crawl"], default="page")
    args = parser.parse_args()

    try:
        response = fetch(args.url)
    except requests.RequestException as exc:
        print(json.dumps({"error": True, "message": f"Could not reach that URL: {exc}", "url": args.url}, indent=2))
        sys.exit(1)

    content_type = response.headers.get("Content-Type", "")
    url_path_lower = urlparse(args.url).path.lower()
    if "application/pdf" in content_type or url_path_lower.endswith(".pdf"):
        print(json.dumps({
            "url": args.url,
            "final_url": response.url,
            "http_status": response.status_code,
            "content_type": content_type,
            "is_pdf": True,
            "note": "This URL is itself a PDF, not an HTML page - use extract_pdf_text.py on it directly.",
        }, indent=2))
        return
    if "text/calendar" in content_type or url_path_lower.endswith(".ics"):
        print(json.dumps({
            "url": args.url,
            "final_url": response.url,
            "http_status": response.status_code,
            "content_type": content_type,
            "is_ics": True,
            "note": (
                "This URL is itself an .ics calendar feed - the school already publishes "
                "structured data directly, which is the best case. Read this content as-is "
                "rather than re-extracting from HTML, but still sanity-check it actually "
                "contains term dates (not some unrelated events feed) before using it."
            ),
            "ics_preview": response.text[:2000],
        }, indent=2))
        return

    raw_html = response.text
    # Parse twice: once untouched (for link/script enumeration, so links
    # inside nav/header/footer/accordions are still found), once for the
    # cleaned text body (where that chrome is genuinely noise).
    soup_for_links = BeautifulSoup(raw_html, "lxml")
    links = _extract_links(soup_for_links, response.url)
    embedded_script_data = _extract_embedded_script_data(soup_for_links)

    soup_for_text = BeautifulSoup(raw_html, "lxml")
    cleaned_text = _clean_text_body(soup_for_text)

    ratio = (len(cleaned_text) / len(raw_html)) if raw_html else 0
    looks_js_rendered = (
        len(cleaned_text) < JS_RENDER_MIN_TEXT_LENGTH and ratio < JS_RENDER_RATIO_THRESHOLD
    )

    warnings = []
    if links["ics_links"]:
        warnings.append(
            "Found a linked .ics calendar feed - this is the best case (already-structured "
            "data, no extraction needed). Fetch it directly and sanity-check it's actually "
            "the term-dates calendar before using it, rather than extracting from cleaned_text."
        )
    if looks_js_rendered:
        if links["pdf_links"] or links["docx_links"] or embedded_script_data:
            warnings.append(
                "Visible page text is minimal and looks JavaScript-rendered, but PDF/Word-doc "
                "links and/or embedded script data were found below - read those instead "
                "of expecting dates in cleaned_text."
            )
        else:
            warnings.append(
                "This page's visible text is minimal relative to its size and no PDF or "
                "embedded data was found - it likely needs JavaScript to render its main "
                "content. A plain fetch cannot see that content. Try the WebFetch tool on "
                "this same URL first (it may render JS where a raw fetch can't); if that "
                "also comes back empty, check for a connected browser tool in this "
                "session, or ask the user to paste the visible page text, provide a "
                "different URL (e.g. a direct PDF link), or enter dates manually."
            )

    output = {
        "url": args.url,
        "final_url": response.url,
        "http_status": response.status_code,
        "content_type": content_type,
        "mode": args.mode,
        "cleaned_text": cleaned_text,
        "looks_js_rendered": looks_js_rendered,
        "js_render_signal": {
            "raw_html_length": len(raw_html),
            "visible_text_length": len(cleaned_text),
            "ratio": round(ratio, 4),
        },
        "links": links,
        "embedded_script_data": embedded_script_data,
        "warnings": warnings,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
