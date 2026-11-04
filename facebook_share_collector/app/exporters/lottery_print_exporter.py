import base64
import datetime
import html
import logging
import os
from typing import List
from app.models.share_profile import ContestParticipant

logger = logging.getLogger(__name__)


class LotteryPrintExporter:
    """
    Generates a print-ready HTML/PDF document containing:
    1. Cut-out Raffle / Lottery Tickets Grid (#0001, #0002, ...) with dashed cut lines,
       Avatar Photo, Display Name, and 3/3 Verified status for physical live lottery boxes.
    2. Master Live-Lottery Judge Verification Sheet for instant serial lookup during the live draw.
    """

    @staticmethod
    def _encode_avatar_data_uri(avatar_path: str) -> str:
        if avatar_path and os.path.isfile(avatar_path):
            try:
                with open(avatar_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                return f"data:image/png;base64,{b64}"
            except Exception:
                pass
        return ""

    @classmethod
    def export_printable_tickets(cls, participants: List[ContestParticipant], output_path: str) -> bool:
        try:
            if os.path.dirname(output_path):
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Filter to qualified participants with assigned serial numbers first (or 3/3 eligible); if none, include provided list
            qualified_serial = [p for p in participants if p.serial_number is not None]
            eligible = qualified_serial or [p for p in participants if p.is_eligible]
            target_list = eligible if eligible else participants

            # Ensure sequential serial numbers (#0001, #0002, ...)
            for idx, p in enumerate(target_list, 1):
                if p.serial_number is None:
                    p.serial_number = idx

            generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            tickets_html = []
            rows_html = []

            for p in target_list:
                serial_str = f"#{p.serial_number:04d}"
                safe_name = html.escape(p.display_name)
                full_comment_raw = " | ".join(c for c in p.comment_texts if c and c.strip()) if p.comment_texts else ""
                if full_comment_raw:
                    short_raw = full_comment_raw[:135] + ("..." if len(full_comment_raw) > 135 else "")
                    safe_short = f'"{html.escape(short_raw)}"'
                    safe_full = f'"{html.escape(full_comment_raw)}"'
                    is_truncated = "1" if len(full_comment_raw) > 135 else "0"
                else:
                    safe_short = '"Verified Entry"'
                    safe_full = '"Verified Entry"'
                    is_truncated = "0"

                avatar_uri = cls._encode_avatar_data_uri(p.avatar_path or "")
                initials = html.escape((p.name[:2] if p.name else "FB").upper())

                if avatar_uri:
                    avatar_tag = f'<img class="avatar" src="{avatar_uri}" alt="avatar" />'
                else:
                    avatar_tag = f'<div class="avatar-placeholder">{initials}</div>'

                raw_url = (p.profile_url or "").strip()
                id_hint = html.escape(raw_url or (f"AvatarHash:{p.avatar_hash[:8]}" if p.avatar_hash else "Verified"))
                if raw_url.startswith("http://") or raw_url.startswith("https://"):
                    safe_href = html.escape(raw_url, quote=True)
                    footer_html = f'<a class="profile-link" href="{safe_href}" target="_blank" rel="noopener noreferrer">{id_hint}</a>'
                    table_url_html = f'<a class="profile-link" href="{safe_href}" target="_blank" rel="noopener noreferrer">{id_hint}</a>'
                else:
                    footer_html = f'<span class="profile-ref">{id_hint}</span>'
                    table_url_html = id_hint

                badge_label = "ELIGIBLE 3/3 ✓" if p.is_eligible else f"QUALIFIED ({p.actions_completed}/3) ✓"
                done_meta = " · ".join(
                    lbl for flag, lbl in [(p.liked, "Like"), (p.commented, "Comment"), (p.shared, "Share")] if flag
                ) or "Verified Entry"

                tickets_html.append(f"""
                <div class="ticket">
                    <div class="ticket-header">
                        <span class="serial">{serial_str}</span>
                        <span class="badge">{badge_label}</span>
                    </div>
                    <div class="ticket-body">
                        {avatar_tag}
                        <div class="ticket-info">
                            <div class="name notranslate" translate="no">{safe_name}</div>
                            <div class="meta">{done_meta}</div>
                            <div class="comment notranslate" translate="no" data-short="{html.escape(safe_short, quote=True)}" data-full="{html.escape(safe_full, quote=True)}" data-truncated="{is_truncated}" onclick="toggleCommentText(this)" title="Click to view full comment">{safe_short}</div>
                        </div>
                    </div>
                    <div class="ticket-footer">{footer_html}</div>
                </div>
                """)

                rows_html.append(f"""
                <tr>
                    <td class="col-serial"><strong>{serial_str}</strong></td>
                    <td class="notranslate" translate="no">{safe_name}</td>
                    <td>{'Yes' if p.liked else 'No'}</td>
                    <td>{'Yes' if p.commented else 'No'} ({len(p.comment_texts)})</td>
                    <td>{'Yes' if p.shared else 'No'}</td>
                    <td class="notranslate" translate="no">{html.escape(full_comment_raw[:140])}</td>
                    <td class="col-url">{table_url_html}</td>
                </tr>
                """)

            doc = f"""<!DOCTYPE html>
<html lang="bn" translate="no" class="notranslate">
<head>
<meta charset="UTF-8">
<meta name="google" content="notranslate">
<title>Live Contest Lottery Tickets & Verification Sheet</title>
<style>
    * {{ box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans Bengali", Arial, sans-serif;
        margin: 0;
        padding: 18px;
        color: #111;
        background: #f6f8fa;
    }}
    .toolbar {{
        background: #1b8a2f;
        color: #fff;
        padding: 12px 16px;
        border-radius: 8px;
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        margin-bottom: 16px;
    }}
    .toolbar-controls {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 12px;
        font-size: 13px;
    }}
    .toolbar select {{
        padding: 6px 10px;
        border-radius: 5px;
        border: none;
        font-weight: 600;
        font-size: 13px;
        color: #111;
        background: #fff;
        cursor: pointer;
    }}
    .toolbar label {{
        display: inline-flex;
        align-items: center;
        gap: 5px;
        cursor: pointer;
        font-weight: 600;
        user-select: none;
    }}
    .toolbar button {{
        background: #fff;
        color: #1b8a2f;
        border: none;
        padding: 8px 16px;
        font-size: 14px;
        font-weight: bold;
        border-radius: 6px;
        cursor: pointer;
    }}
    .ticket-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        width: 100%;
    }}
    .ticket {{
        background: #fff;
        border-radius: 6px;
        padding: 9px 11px;
        page-break-inside: avoid;
        break-inside: avoid;
        overflow: hidden;
        min-width: 0;
    }}
    /* Border Style Customization Classes (Default: Solid Total Border Line) */
    body.border-solid .ticket {{
        border: 1.5px solid #222;
    }}
    body.border-dashed .ticket {{
        border: 1.5px dashed #222;
    }}
    body.border-none .ticket {{
        border: none;
        box-shadow: 0 1px 3px rgba(0,0,0,0.12);
    }}
    .ticket-header {{
        display: flex;
        justify-content: center;
        align-items: center;
        position: relative;
        border-bottom: 1px solid #e5e7eb;
        padding-bottom: 4px;
        margin-bottom: 7px;
    }}
    body.align-left .ticket-header {{
        justify-content: space-between;
    }}
    .serial {{
        font-size: 18px;
        font-weight: 800;
        color: #0b5ed7;
        text-align: center;
    }}
    .badge {{
        display: none;
        font-size: 9px;
        font-weight: 700;
        background: #d1e7dd;
        color: #0f5132;
        padding: 2px 6px;
        border-radius: 4px;
        margin-left: 8px;
    }}
    body.show-badge .badge {{
        display: inline-block;
    }}
    .ticket-body {{
        display: flex;
        align-items: flex-start;
        gap: 9px;
        min-width: 0;
    }}
    .avatar, .avatar-placeholder {{
        width: 40px;
        height: 40px;
        border-radius: 50%;
        flex-shrink: 0;
        object-fit: cover;
        border: 1px solid #ccc;
        margin-top: 2px;
    }}
    .avatar-placeholder {{
        background: #e9ecef;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        color: #495057;
        font-size: 13px;
    }}
    .ticket-info {{
        overflow: hidden;
        flex: 1;
        min-width: 0;
    }}
    .name {{
        font-size: 13.5px;
        font-weight: 700;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .meta {{
        font-size: 11px;
        color: #198754;
        font-weight: 600;
        margin-top: 2px;
    }}
    .comment {{
        font-size: 11px;
        line-height: 1.38;
        color: #444;
        font-style: italic;
        margin-top: 3px;
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 3;
        line-clamp: 3;
        white-space: normal;
        word-break: break-word;
        overflow: hidden;
        text-overflow: ellipsis;
        cursor: pointer;
    }}
    .comment.expanded {{
        display: block;
        -webkit-line-clamp: unset;
        line-clamp: unset;
        white-space: normal;
        word-break: break-word;
        overflow: visible;
    }}
    .ticket-footer {{
        margin-top: 6px;
        padding-top: 4px;
        border-top: 1px solid #f0f0f0;
        font-size: 9px;
        color: #555;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .profile-link {{
        color: #555;
        text-decoration: none;
    }}
    .profile-link:hover {{
        color: #0b5ed7;
        text-decoration: underline;
    }}
    .judge-sheet-section {{
        display: none;
        page-break-before: always;
        break-before: page;
        margin-top: 28px;
    }}
    body.show-judge-sheet .judge-sheet-section {{
        display: block;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        background: #fff;
        font-size: 11.5px;
    }}
    th, td {{
        border: 1px solid #ccc;
        padding: 5px 7px;
        text-align: left;
    }}
    th {{
        background: #e9ecef;
    }}
    .col-serial {{
        width: 65px;
        color: #0b5ed7;
    }}
    .col-url {{
        font-size: 10px;
        color: #555;
        max-width: 180px;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    @page {{
        margin: 8mm;
    }}
    @media print {{
        body {{
            background: #fff;
            padding: 0;
            margin: 0;
        }}
        .no-print, .toolbar {{
            display: none !important;
        }}
        .ticket-grid {{
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
            gap: 8px !important;
        }}
        body.border-none .ticket {{
            box-shadow: none !important;
        }}
    }}
</style>
<script>
    function setBorderStyle(styleVal) {{
        document.body.classList.remove("border-solid", "border-dashed", "border-none");
        document.body.classList.add("border-" + styleVal);
    }}
    function toggleCenterSerial(checked) {{
        if (checked) {{
            document.body.classList.remove("align-left");
        }} else {{
            document.body.classList.add("align-left");
        }}
    }}
    function toggleStatusBadge(checked) {{
        document.body.classList.toggle("show-badge", checked);
    }}
    function toggleJudgeSheet(checked) {{
        document.body.classList.toggle("show-judge-sheet", checked);
    }}
    function toggleCommentText(el) {{
        if (!el) return;
        const isExpanded = el.classList.toggle("expanded");
        el.textContent = isExpanded ? (el.getAttribute("data-full") || el.textContent) : (el.getAttribute("data-short") || el.textContent);
    }}
</script>
</head>
<body class="border-solid">
    <div class="toolbar no-print">
        <div>
            <strong>Contest Lottery Slips ({len(target_list)} Tickets)</strong>
            <span style="font-size:12px;opacity:0.9;margin-left:8px;">({generated_at})</span>
        </div>
        <div class="toolbar-controls">
            <label>Border:
                <select onchange="setBorderStyle(this.value)">
                    <option value="solid" selected>Total Border Line (Solid)</option>
                    <option value="dashed">--- Dashed Border (---)</option>
                    <option value="none">No Border</option>
                </select>
            </label>
            <label><input type="checkbox" checked onchange="toggleCenterSerial(this.checked)"> Center ID (#0001)</label>
            <label><input type="checkbox" onchange="toggleStatusBadge(this.checked)"> Show Status Badge</label>
            <label><input type="checkbox" onchange="toggleJudgeSheet(this.checked)"> Include Verification Table</label>
            <button onclick="window.print()">🖨️ Print</button>
        </div>
    </div>

    <div class="ticket-grid">
        {''.join(tickets_html)}
    </div>

    <div class="judge-sheet-section">
        <h3 style="margin:0 0 8px 0;">Verification Sheet ({len(target_list)} Contestants)</h3>
        <table>
            <thead>
                <tr>
                    <th>Serial #</th>
                    <th>Contestant Name</th>
                    <th>Liked</th>
                    <th>Commented</th>
                    <th>Shared</th>
                    <th>Comments Text</th>
                    <th>Profile Reference</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows_html)}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(doc)

            logger.info(f"Exported {len(target_list)} printable lottery tickets to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export printable lottery tickets: {e}")
            return False

