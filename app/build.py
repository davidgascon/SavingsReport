"""Renders the self-contained public page (SPEC.md: Public page contents)."""
from __future__ import annotations

import io
import json
import os
from datetime import date, datetime, timezone

from . import calc

TEMPLATE = os.path.join(os.path.dirname(__file__), "templates", "public.html")
PREVIEW_BANNER = (
    '<div class="preview-banner"><b>Preview</b> of unpublished changes. '
    "The public page updates when you publish.</div>"
)


def render(data: dict, today: date, generated_at: datetime = None, preview: bool = False) -> str:
    """The public HTML. Only computed totals are embedded: never notes or the raw data file."""
    payload = calc.report(data, today)
    payload["generated_at"] = (generated_at or datetime.now(timezone.utc)).isoformat()
    # "</" would let embedded text close the <script> tag early.
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    with io.open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("/*__REPORT__*/", blob, 1)
    if preview:
        html = html.replace("<!--PREVIEW_BANNER-->", PREVIEW_BANNER, 1)
    return html
