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

            # Filter to eligible (3/3) participants first; if none are eligible yet, include provided list
            eligible = [p for p in participants if p.is_eligible]
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
                comment_preview = html.escape(p.comment_texts[0][:45] + ("..." if len(p.comment_texts[0]) > 45 else "")) if p.comment_texts else "Verified Comment"
                avatar_uri = cls._encode_avatar_data_uri(p.avatar_path or "")
                initials = html.escape((p.name[:2] if p.name else "FB").upper())

                if avatar_uri:
                    avatar_tag = f'<img class="avatar" src="{avatar_uri}" alt="avatar" />'
                else:
                    avatar_tag = f'<div class="avatar-placeholder">{initials}</div>'

                id_hint = html.escape(p.profile_url or (f"AvatarHash:{p.avatar_hash[:8]}" if p.avatar_hash else "3/3 Verified"))

                tickets_html.append(f"""
                <div class="ticket">
                    <div class="ticket-header">
                        <span class="serial">{serial_str}</span>
                        <span class="badge">{'ELIGIBLE 3/3 ✓' if p.is_eligible else f'{p.actions_completed}/3'}</span>
                    </div>
                    <div class="ticket-body">
                        {avatar_tag}
                        <div class="ticket-info">
                            <div class="name">{safe_name}</div>
                            <div class="meta">👍 Like · 💬 Comment · 🔄 Share</div>
                            <div class="comment">"{comment_preview}"</div>
                        </div>
                    </div>
                    <div class="ticket-footer">{id_hint}</div>
                </div>
                """)

                rows_html.append(f"""
                <tr>
                    <td class="col-serial"><strong>{serial_str}</strong></td>
                    <td>{safe_name}</td>
                    <td>{'✅' if p.liked else '❌'}</td>
                    <td>{'✅' if p.commented else '❌'} ({len(p.comment_texts)})</td>
                    <td>{'✅' if p.shared else '❌'}</td>
                    <td>{html.escape(' | '.join(p.comment_texts)[:120])}</td>
                    <td class="col-url">{id_hint}</td>
                </tr>
                """)

            doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Live Contest Lottery Tickets & Verification Sheet</title>
<style>
    * {{ box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans Bengali", Arial, sans-serif;
        margin: 0;
        padding: 20px;
        color: #111;
        background: #f6f8fa;
    }}
    .toolbar {{
        background: #1b8a2f;
        color: #fff;
        padding: 14px 20px;
        border-radius: 8px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
    }}
    .toolbar button {{
        background: #fff;
        color: #1b8a2f;
        border: none;
        padding: 10px 18px;
        font-size: 15px;
        font-weight: bold;
        border-radius: 6px;
        cursor: pointer;
    }}
    h2 {{ margin: 10px 0 6px 0; }}
    .sub {{ color: #555; font-size: 13px; margin-bottom: 16px; }}
    .ticket-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 12px;
    }}
    .ticket {{
        background: #fff;
        border: 2px dashed #222;
        border-radius: 6px;
        padding: 10px 12px;
        page-break-inside: avoid;
        break-inside: avoid;
    }}
    .ticket-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #ddd;
        padding-bottom: 4px;
        margin-bottom: 8px;
    }}
    .serial {{
        font-size: 18px;
        font-weight: 800;
        color: #0b5ed7;
    }}
    .badge {{
        font-size: 10px;
        font-weight: 700;
        background: #d1e7dd;
        color: #0f5132;
        padding: 2px 6px;
        border-radius: 4px;
    }}
    .ticket-body {{
        display: flex;
        align-items: center;
        gap: 10px;
    }}
    .avatar, .avatar-placeholder {{
        width: 44px;
        height: 44px;
        border-radius: 50%;
        flex-shrink: 0;
        object-fit: cover;
        border: 1px solid #ccc;
    }}
    .avatar-placeholder {{
        background: #e9ecef;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        color: #495057;
        font-size: 14px;
    }}
    .ticket-info {{
        overflow: hidden;
    }}
    .name {{
        font-size: 14px;
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
        color: #555;
        font-style: italic;
        margin-top: 2px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .ticket-footer {{
        margin-top: 6px;
        padding-top: 4px;
        border-top: 1px dotted #eee;
        font-size: 9px;
        color: #666;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .page-break {{
        page-break-before: always;
        break-before: page;
        margin-top: 32px;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        background: #fff;
        font-size: 12px;
    }}
    th, td {{
        border: 1px solid #ccc;
        padding: 6px 8px;
        text-align: left;
    }}
    th {{
        background: #e9ecef;
    }}
    .col-serial {{
        width: 70px;
        color: #0b5ed7;
    }}
    .col-url {{
        font-size: 10px;
        color: #555;
        max-width: 180px;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    @media print {{
        body {{ background: #fff; padding: 0; }}
        .toolbar {{ display: none !important; }}
    }}
</style>
</head>
<body>
    <div class="toolbar">
        <div>
            <strong>Facebook Contest Live Lottery Slips</strong> — Total Printable Tickets: <strong>{len(target_list)}</strong> (Generated: {generated_at})
        </div>
        <button onclick="window.print()">🖨️ Print Tickets / Save as PDF</button>
    </div>

    <h2>Part 1: Cut-Out Live Lottery Slips ({len(target_list)} Tickets)</h2>
    <div class="sub">Cut along the dashed lines to fold into your live lottery box. Each slip has a unique Serial Number (#0001–#{len(target_list):04d}), Profile Photo, and Name.</div>
    <div class="ticket-grid">
        {''.join(tickets_html)}
    </div>

    <div class="page-break">
        <h2>Part 2: Master Judge Verification Sheet ({len(target_list)} Contestants)</h2>
        <div class="sub">Use this sheet during the live lottery draw to verify the drawn Serial Number (#) against the user's comment and profile.</div>
        <table>
            <thead>
                <tr>
                    <th>Serial #</th>
                    <th>Contestant Name</th>
                    <th>Liked</th>
                    <th>Commented</th>
                    <th>Shared</th>
                    <th>Comments Text</th>
                    <th>Identity / Profile Reference</th>
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

