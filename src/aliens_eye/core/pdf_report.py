"""Investigator-style PDF report (optional, requires the ``[pdf]`` extra: reportlab).

Renders the scan summary, per-variation Found/Maybe tables with embedded avatars,
and any correlation clusters. Importing this module raises ImportError if reportlab
is not installed; the exporter catches that and prints an install hint.
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_MAX_AVATARS = 40


def _fetch_avatar(url: str, timeout: float = 6.0) -> io.BytesIO | None:
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 aliens-eye"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-provided profile URL
            if resp.status != 200:
                return None
            data = resp.read(2_000_000)
        return io.BytesIO(data)
    except Exception:
        return None


def write_pdf(path: str | Path, results_data: dict[str, Any]) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, title="Aliens Eye Report")
    story: list[Any] = []

    summary = results_data.get("scan_summary", {})
    story.append(Paragraph("Aliens Eye — OSINT Report", styles["Title"]))
    story.append(Paragraph(f"Base username: <b>{summary.get('base_username', '')}</b>", styles["Normal"]))
    story.append(Paragraph(f"Scan level: {summary.get('scan_level', '')}", styles["Normal"]))
    story.append(Paragraph(f"Timestamp: {summary.get('timestamp', '')}", styles["Normal"]))
    story.append(Paragraph(
        f"Found: {summary.get('total_found', 0)} | "
        f"High confidence: {summary.get('total_high_confidence', 0)} | "
        f"Sites scanned: {summary.get('total_sites_scanned', 0)}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 6 * mm))

    avatars_used = 0
    for variation, block in results_data.get("variations", {}).items():
        hits = [
            (site, info)
            for site, info in (block.get("sites", {}) or {}).items()
            if info.get("status") in {"Found", "Maybe"}
        ]
        if not hits:
            continue
        hits.sort(key=lambda kv: (kv[1].get("status") != "Found", -kv[1].get("confidence", 0)))
        story.append(Paragraph(f"@{variation}", styles["Heading2"]))

        data = [["", "Site", "Status", "Conf", "Name / Bio", "URL"]]
        for site, info in hits:
            profile = info.get("ai_analysis", {}).get("signals", {}).get("profile", {}) or {}
            img_cell: Any = ""
            if avatars_used < _MAX_AVATARS and profile.get("avatar"):
                buf = _fetch_avatar(profile["avatar"])
                if buf is not None:
                    try:
                        img_cell = Image(buf, width=12 * mm, height=12 * mm)
                        avatars_used += 1
                    except Exception:
                        img_cell = ""
            name = profile.get("name", "")
            bio = (profile.get("bio", "") or "")[:120]
            name_bio = Paragraph(f"<b>{_x(name)}</b><br/>{_x(bio)}", styles["BodyText"])
            url = Paragraph(_x(info.get("url", "")), styles["BodyText"])
            data.append([
                img_cell, site, info.get("status", ""),
                f"{info.get('confidence', 0)}%", name_bio, url,
            ])

        table = Table(data, colWidths=[14 * mm, 26 * mm, 16 * mm, 12 * mm, 52 * mm, 50 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f4")]),
        ]))
        story.append(table)
        story.append(Spacer(1, 4 * mm))

    clusters = results_data.get("correlation", {}).get("clusters", [])
    if clusters:
        story.append(Paragraph("Correlation — likely same person", styles["Heading2"]))
        for i, cluster in enumerate(clusters, 1):
            sites = ", ".join(m["site"] for m in cluster["members"])
            reasons = ", ".join(cluster.get("reasons", []))
            story.append(Paragraph(f"<b>Cluster {i}</b> ({reasons}): {_x(sites)}", styles["BodyText"]))

    doc.build(story)


def _x(text: Any) -> str:
    """Escape the small subset of markup reportlab Paragraph treats as XML."""
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
