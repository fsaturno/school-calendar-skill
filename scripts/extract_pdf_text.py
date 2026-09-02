#!/usr/bin/env python3
"""Download one or more PDFs and extract their text for Claude to read.

Used when fetch_page.py finds no usable date text in a page's HTML but does
find linked PDF(s) - a very common real-world pattern (roughly half the UK
school sites checked while designing this skill publish term dates only as
a PDF). Extraction uses pypdf, a pure-Python library with no system/browser
dependencies - appropriate for a non-technical parent's machine.

Scanned/image-only PDFs are explicitly out of scope: this script doesn't
attempt OCR, it just flags when a PDF looks like a scan (very little
extractable text per page) so the calling skill can honestly tell the user
and fall back to asking them to paste text or enter dates manually.

Usage:
    python3 extract_pdf_text.py --url <pdf_url> [--url <pdf_url> ...]
"""
from __future__ import annotations

import argparse
import io
import json

import requests
from pypdf import PdfReader

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 30

# Below this many extracted characters per page, a PDF is more likely a scan
# (image-only) than genuine embedded text. This is a cheap heuristic, not an
# image classifier - it just avoids confidently returning garbage.
MIN_CHARS_PER_PAGE = 40


def extract_one(url: str) -> dict:
    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        return {"url": url, "error": True, "message": f"Could not download this PDF: {exc}"}

    try:
        reader = PdfReader(io.BytesIO(response.content))
    except Exception as exc:
        return {"url": url, "error": True, "message": f"Could not read this as a PDF: {exc}"}

    num_pages = len(reader.pages)
    text_parts = []
    for page in reader.pages:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            text_parts.append("")
    extracted_text = "\n".join(text_parts).strip()
    char_count = len(extracted_text)

    looks_scanned_or_empty = num_pages > 0 and (char_count / num_pages) < MIN_CHARS_PER_PAGE
    warning = None
    if looks_scanned_or_empty:
        warning = (
            "This PDF looks like a scanned image rather than a text document "
            "(very little text could be extracted). Ask the user to open it and "
            "paste the term dates directly, or enter them manually - do not guess."
        )

    return {
        "url": url,
        "num_pages": num_pages,
        "extracted_text": extracted_text,
        "char_count": char_count,
        "looks_scanned_or_empty": looks_scanned_or_empty,
        "warning": warning,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", action="append", required=True, dest="urls")
    args = parser.parse_args()

    sources = [extract_one(url) for url in args.urls]
    print(json.dumps({"sources": sources}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
