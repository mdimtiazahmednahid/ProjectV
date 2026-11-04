import base64
import datetime
import html
import logging
import os
from typing import List, Optional, Dict, Set
from app.models.share_profile import ContestParticipant
from app.utils.sentra_brand import get_sentra_logo_svg

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
    def export_printable_tickets(
        cls,
        participants: List[ContestParticipant],
        output_path: str,
        qualified_keys: Optional[Set[str]] = None,
        evaluations: Optional[Dict[str, object]] = None,
        default_scope: str = "all",
    ) -> bool:
        try:
            if os.path.dirname(output_path):
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

            target_list = list(participants)

            # Determine which participants are Qualified vs Disqualified/Incomplete
            has_explicit_serials = any(p.serial_number is not None for p in target_list)
            has_eligible = any(p.is_eligible for p in target_list)

            def _is_participant_qualified(p: ContestParticipant) -> bool:
                if qualified_keys is not None:
                    return p.normalized_key in qualified_keys
                if has_explicit_serials:
                    return p.serial_number is not None
                if has_eligible:
                    return bool(p.is_eligible)
                return True

            qual_Flags = [_is_participant_qualified(p) for p in target_list]
            qual_count = sum(1 for q in qual_Flags if q)
            disq_count = len(target_list) - qual_count
            total_count = len(target_list)

            if default_scope == "qualified" and qual_count == 0:
                default_scope = "all"
            elif default_scope == "disqualified" and disq_count == 0:
                default_scope = "all"
            elif default_scope not in ("all", "qualified", "disqualified"):
                default_scope = "all"

            generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            tickets_html = []
            rows_html = []

            all_idx = 0
            qual_idx = 0
            disq_idx = 0

            for p, is_qual in zip(target_list, qual_Flags):
                all_idx += 1
                serial_all_str = f"#{all_idx:04d}"
                if is_qual:
                    qual_idx += 1
                    serial_qual_str = f"#{qual_idx:04d}"
                    serial_disq_str = "-"
                    if p.serial_number is None:
                        p.serial_number = qual_idx
                else:
                    disq_idx += 1
                    serial_qual_str = "-"
                    serial_disq_str = f"#{disq_idx:04d}"

                if default_scope == "qualified":
                    initial_serial_str = serial_qual_str if is_qual else serial_all_str
                elif default_scope == "disqualified":
                    initial_serial_str = serial_disq_str if not is_qual else serial_all_str
                else:
                    initial_serial_str = serial_all_str

                status_attr = "qualified" if is_qual else "disqualified"
                safe_name = html.escape(p.display_name)
                full_comment_raw = " | ".join(c for c in p.comment_texts if c and c.strip()) if p.comment_texts else ""
                if not full_comment_raw and getattr(p, "share_contents", None):
                    full_comment_raw = " | ".join(s for s in p.share_contents if s and s.strip())

                if full_comment_raw:
                    short_raw = full_comment_raw[:135] + ("..." if len(full_comment_raw) > 135 else "")
                    safe_short = f'"{html.escape(short_raw)}"'
                    safe_full = f'"{html.escape(full_comment_raw)}"'
                    is_truncated = "1" if len(full_comment_raw) > 135 else "0"
                else:
                    fallback_comment = '"Verified Entry"' if p.commented else '"No comment"'
                    safe_short = fallback_comment
                    safe_full = fallback_comment
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

                full_share_caption_raw = (
                    " | ".join(s for s in p.share_contents if s and s.strip())
                    if getattr(p, "share_contents", None)
                    else ""
                )
                raw_shared_post_url = getattr(p, "primary_shared_post_url", "") or ""
                if raw_shared_post_url.startswith("http://") or raw_shared_post_url.startswith("https://"):
                    safe_post_href = html.escape(raw_shared_post_url, quote=True)
                    safe_post_label = html.escape(raw_shared_post_url)
                    table_shared_post_html = f'<a class="profile-link" href="{safe_post_href}" target="_blank" rel="noopener noreferrer">{safe_post_label}</a>'
                else:
                    table_shared_post_html = html.escape(raw_shared_post_url)

                missing_actions = []
                if not p.liked:
                    missing_actions.append("No Reaction")
                if not p.commented:
                    missing_actions.append("No Comment")
                if not p.shared:
                    missing_actions.append("No Share")

                ev = evaluations.get(p.normalized_key) if evaluations else None
                ev_status = getattr(ev, "status_label", "") if ev else ""

                if is_qual:
                    badge_cls = "badge badge-qual"
                    badge_label = "ELIGIBLE 3/3 ✓" if p.is_eligible else f"QUALIFIED ({p.actions_completed}/3) ✓"
                else:
                    badge_cls = "badge badge-disq"
                    if ev_status and ("WRONG" in ev_status.upper() or "DISQUALIFIED" in ev_status.upper()):
                        clean_ev = ev_status.replace("❌", "").strip()
                        badge_label = f"{html.escape(clean_ev)} ✗"
                    elif missing_actions:
                        badge_label = f"DISQUALIFIED ({', '.join(missing_actions)}) ✗"
                    else:
                        badge_label = f"DISQUALIFIED ({p.actions_completed}/3) ✗"

                like_cls = "act-done" if p.liked else "act-missing"
                like_sign = "✅" if p.liked else "❌"
                comment_cls = "act-done" if p.commented else "act-missing"
                comment_sign = "✅" if p.commented else "❌"
                share_cls = "act-done" if p.shared else "act-missing"
                share_sign = "✅" if p.shared else "❌"

                done_meta = (
                    f'<span class="act-item act-like {like_cls}" onclick="toggleSingleAction(this)" title="Click to toggle Reaction status">'
                    f'<span class="act-icon">{like_sign} </span>Reaction</span>'
                    f'<span class="act-sep"> · </span>'
                    f'<span class="act-item act-comment {comment_cls}" onclick="toggleSingleAction(this)" title="Click to toggle Comment status">'
                    f'<span class="act-icon">{comment_sign} </span>Comment</span>'
                    f'<span class="act-sep"> · </span>'
                    f'<span class="act-item act-share {share_cls}" onclick="toggleSingleAction(this)" title="Click to toggle Share status">'
                    f'<span class="act-icon">{share_sign} </span>Share</span>'
                )

                tickets_html.append(f"""
                <div class="ticket" data-status="{status_attr}" data-serial-all="{serial_all_str}" data-serial-qual="{serial_qual_str}" data-serial-disq="{serial_disq_str}">
                    <div class="ticket-header">
                        <span class="serial">{initial_serial_str}</span>
                        <span class="{badge_cls}">{badge_label}</span>
                    </div>
                    <div class="ticket-body">
                        {avatar_tag}
                        <div class="ticket-info">
                            <div class="name notranslate" translate="no">{safe_name}</div>
                            <div class="meta">{done_meta}</div>
                            <div class="comment notranslate" translate="no" data-short="{html.escape(safe_short, quote=True)}" data-full="{html.escape(safe_full, quote=True)}" data-truncated="{is_truncated}" onclick="toggleCommentText(this)" title="Click to view full comment">{safe_full}</div>
                        </div>
                    </div>
                    <div class="ticket-footer">{footer_html}</div>
                </div>
                """)

                rows_html.append(f"""
                <tr data-status="{status_attr}" data-serial-all="{serial_all_str}" data-serial-qual="{serial_qual_str}" data-serial-disq="{serial_disq_str}">
                    <td class="col-serial"><strong class="row-serial">{initial_serial_str}</strong></td>
                    <td class="notranslate" translate="no">{safe_name}</td>
                    <td>{'✅ Reaction' if p.liked else '❌ Reaction'}</td>
                    <td>{'✅ Comment' if p.commented else '❌ Comment'} ({len(p.comment_texts)})</td>
                    <td>{'✅ Share' if p.shared else '❌ Share'}</td>
                    <td>{badge_label}</td>
                    <td class="notranslate" translate="no">{html.escape(" | ".join(p.comment_texts)[:140])}</td>
                    <td class="notranslate" translate="no">{html.escape(full_share_caption_raw[:140])}</td>
                    <td class="col-url">{table_url_html}</td>
                    <td class="col-url">{table_shared_post_html}</td>
                </tr>
                """)

            if default_scope == "qualified":
                initial_visible_count = qual_count
            elif default_scope == "disqualified":
                initial_visible_count = disq_count
            else:
                initial_visible_count = total_count

            sel_all = "selected" if default_scope == "all" else ""
            sel_qual = "selected" if default_scope == "qualified" else ""
            sel_disq = "selected" if default_scope == "disqualified" else ""

            doc = f"""<!DOCTYPE html>
<html lang="bn" translate="no" class="notranslate">
<head>
<meta charset="UTF-8">
<meta name="google" content="notranslate">
<title>Sentra — Live Lottery Tickets & Verification Sheet</title>
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
    body.id-left .ticket-header,
    body.align-left .ticket-header {{
        justify-content: space-between;
    }}
    body.id-hide .serial {{
        display: none !important;
    }}
    body.id-hide:not(.show-badge) .ticket-header {{
        display: none !important;
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
        white-space: nowrap;
    }}
    .badge-disq {{
        background: #fee2e2;
        color: #991b1b;
    }}
    body.show-badge .badge {{
        display: inline-block;
    }}
    /* Ticket Scope Filtering (All / Qualified Only / Disqualified Only) */
    body[data-scope="qualified"] .ticket[data-status="disqualified"] {{
        display: none !important;
    }}
    body[data-scope="disqualified"] .ticket[data-status="qualified"] {{
        display: none !important;
    }}
    body[data-scope="qualified"] tr[data-status="disqualified"] {{
        display: none !important;
    }}
    body[data-scope="disqualified"] tr[data-status="qualified"] {{
        display: none !important;
    }}
    .ticket-body {{
        display: flex;
        align-items: flex-start;
        gap: 8px;
        min-width: 0;
    }}
    .avatar, .avatar-placeholder {{
        width: 38px;
        height: 38px;
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
        font-size: 13px;
        font-weight: 700;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .meta {{
        font-size: 9.6px;
        font-weight: 600;
        margin-top: 2px;
        display: flex;
        flex-wrap: nowrap;
        white-space: nowrap;
        align-items: center;
        gap: 1px;
        letter-spacing: -0.15px;
        overflow: hidden;
    }}
    .act-item {{
        display: inline-flex;
        align-items: center;
        white-space: nowrap;
        flex-shrink: 0;
        cursor: pointer;
        user-select: none;
    }}
    .act-done {{
        color: #15803d;
    }}
    .act-missing {{
        color: #b91c1c;
        opacity: 0.9;
    }}
    .act-sep {{
        color: #9ca3af;
        margin: 0 2px;
        flex-shrink: 0;
    }}
    /* Action Display Customization Modes */
    body.actions-done-icons .act-missing {{
        display: none !important;
    }}
    body.actions-done-icons .act-sep {{
        display: none !important;
    }}
    body.actions-done-icons .act-done {{
        margin-right: 6px;
    }}
    body.actions-done-text .act-missing {{
        display: none !important;
    }}
    body.actions-done-text .act-icon {{
        display: none !important;
    }}
    body.actions-done-text .act-sep {{
        display: none !important;
    }}
    body.actions-done-text .act-done {{
        margin-right: 6px;
    }}
    body.actions-hide .meta {{
        display: none !important;
    }}
    body.hide-act-like .act-like {{
        display: none !important;
    }}
    body.hide-act-comment .act-comment {{
        display: none !important;
    }}
    body.hide-act-share .act-share {{
        display: none !important;
    }}
    /* Comment Line Customization (Default: 2 Lines) */
    .comment {{
        font-size: 11px;
        line-height: 1.38;
        color: #444;
        font-style: italic;
        margin-top: 3px;
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
        line-clamp: 2;
        white-space: normal;
        word-break: break-word;
        overflow: hidden;
        text-overflow: ellipsis;
        cursor: pointer;
    }}
    body.comment-lines-1 .comment {{
        display: block;
        -webkit-line-clamp: unset;
        line-clamp: unset;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    body.comment-lines-2 .comment {{
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
        line-clamp: 2;
        white-space: normal;
    }}
    body.comment-lines-3 .comment {{
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 3;
        line-clamp: 3;
        white-space: normal;
    }}
    body.comment-lines-4 .comment {{
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 4;
        line-clamp: 4;
        white-space: normal;
    }}
    body.comment-lines-full .comment {{
        display: block;
        -webkit-line-clamp: unset;
        line-clamp: unset;
        white-space: normal;
        overflow: visible;
    }}
    body.comment-lines-hide .comment {{
        display: none !important;
    }}
    .comment.expanded {{
        display: block !important;
        -webkit-line-clamp: unset !important;
        line-clamp: unset !important;
        white-space: normal !important;
        word-break: break-word !important;
        overflow: visible !important;
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
        margin: 6mm;
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
            gap: 6px !important;
        }}
        .ticket {{
            padding: 6px 7px !important;
        }}
        .ticket-body {{
            gap: 5px !important;
        }}
        .avatar, .avatar-placeholder {{
            width: 30px !important;
            height: 30px !important;
            font-size: 10.5px !important;
        }}
        .name {{
            font-size: 11.5px !important;
        }}
        .meta {{
            font-size: 8.3px !important;
            flex-wrap: nowrap !important;
            white-space: nowrap !important;
            gap: 1px !important;
            letter-spacing: -0.2px !important;
        }}
        .act-sep {{
            margin: 0 1px !important;
        }}
        .comment {{
            font-size: 10px !important;
            line-height: 1.32 !important;
        }}
        body.border-none .ticket {{
            box-shadow: none !important;
        }}
    }}
</style>
<script>
    function setTicketScope(scopeVal) {{
        document.body.setAttribute("data-scope", scopeVal);
        let visibleCount = 0;
        document.querySelectorAll(".ticket").forEach(function(ticketEl) {{
            const status = ticketEl.getAttribute("data-status");
            const isVisible = (
                scopeVal === "all" ||
                (scopeVal === "qualified" && status === "qualified") ||
                (scopeVal === "disqualified" && status === "disqualified")
            );
            if (isVisible) {{
                visibleCount++;
                const serialAttr = (
                    scopeVal === "qualified" ? "data-serial-qual" :
                    scopeVal === "disqualified" ? "data-serial-disq" :
                    "data-serial-all"
                );
                const sVal = ticketEl.getAttribute(serialAttr) || ("#" + String(visibleCount).padStart(4, "0"));
                const serialSpan = ticketEl.querySelector(".serial");
                if (serialSpan) {{
                    serialSpan.textContent = sVal;
                }}
            }}
        }});
        document.querySelectorAll("tbody tr").forEach(function(rowEl) {{
            const serialAttr = (
                scopeVal === "qualified" ? "data-serial-qual" :
                scopeVal === "disqualified" ? "data-serial-disq" :
                "data-serial-all"
            );
            const sVal = rowEl.getAttribute(serialAttr);
            const rowSerial = rowEl.querySelector(".row-serial");
            if (rowSerial && sVal) {{
                rowSerial.textContent = sVal;
            }}
        }});
        const titleCountEl = document.getElementById("toolbarTicketCount");
        if (titleCountEl) {{
            titleCountEl.textContent = "Sentra Lottery Slips (" + visibleCount + " Tickets)";
        }}
        const sheetCountEl = document.getElementById("sheetTicketCount");
        if (sheetCountEl) {{
            sheetCountEl.textContent = "Sentra Verification Sheet (" + visibleCount + " Contestants)";
        }}
    }}
    function setBorderStyle(styleVal) {{
        document.body.classList.remove("border-solid", "border-dashed", "border-none");
        document.body.classList.add("border-" + styleVal);
    }}
    function setIdPosition(posVal) {{
        document.body.classList.remove("id-center", "id-left", "id-hide", "align-left");
        document.body.classList.add("id-" + posVal);
    }}
    function toggleCenterSerial(checked) {{
        setIdPosition(checked ? "center" : "left");
    }}
    function setActionStyle(modeVal) {{
        document.body.classList.remove("actions-all-icons", "actions-done-icons", "actions-done-text", "actions-hide");
        document.body.classList.add("actions-" + modeVal);
    }}
    function toggleActionItemVisibility(actName, checked) {{
        document.body.classList.toggle("hide-act-" + actName, !checked);
    }}
    function setCommentLines(linesVal) {{
        document.body.classList.remove(
            "comment-lines-1",
            "comment-lines-2",
            "comment-lines-3",
            "comment-lines-4",
            "comment-lines-full",
            "comment-lines-hide"
        );
        document.body.classList.add("comment-lines-" + linesVal);
        document.querySelectorAll(".comment.expanded").forEach(function(el) {{
            el.classList.remove("expanded");
        }});
    }}
    function toggleSingleAction(el) {{
        if (!el) return;
        const isDone = el.classList.contains("act-done");
        el.classList.toggle("act-done", !isDone);
        el.classList.toggle("act-missing", isDone);
        const iconSpan = el.querySelector(".act-icon");
        if (iconSpan) {{
            iconSpan.textContent = !isDone ? "✅ " : "❌ ";
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
        if (el.getAttribute("data-full")) {{
            el.textContent = el.getAttribute("data-full");
        }}
    }}
</script>
</head>
<body class="border-solid id-center actions-all-icons comment-lines-2" data-scope="{default_scope}">
    <div class="toolbar no-print">
        <div style="display:flex;align-items:center;gap:8px;">
            {get_sentra_logo_svg(size=28, bg_fill="#0b1120")}
            <span style="font-weight:800;letter-spacing:1px;font-size:15px;">SENTRA</span>
            <span style="opacity:0.65;">|</span>
            <strong id="toolbarTicketCount">Sentra Lottery Slips ({initial_visible_count} Tickets)</strong>
            <span style="font-size:12px;opacity:0.9;margin-left:4px;">({generated_at})</span>
        </div>
        <div class="toolbar-controls">
            <label>Show:
                <select id="scopeSelect" onchange="setTicketScope(this.value)">
                    <option value="all" {sel_all}>All Participants ({total_count}) — Include ❌ Disqualified</option>
                    <option value="qualified" {sel_qual}>Verified / Qualified Only ({qual_count} ✅)</option>
                    <option value="disqualified" {sel_disq}>Disqualified / Incomplete Only ({disq_count} ❌)</option>
                </select>
            </label>
            <label>Border:
                <select onchange="setBorderStyle(this.value)">
                    <option value="solid" selected>Total Border Line (Solid)</option>
                    <option value="dashed">--- Dashed Border (---)</option>
                    <option value="none">No Border</option>
                </select>
            </label>
            <label>ID (#0001):
                <select onchange="setIdPosition(this.value)">
                    <option value="center" selected>Center ID (#0001)</option>
                    <option value="left">Left Align ID (#0001)</option>
                    <option value="hide">Hide / Remove ID</option>
                </select>
            </label>
            <label>Actions:
                <select onchange="setActionStyle(this.value)">
                    <option value="all-icons" selected>✅ / ❌ All 3 (Reaction · Comment · Share)</option>
                    <option value="done-icons">✅ Completed Only</option>
                    <option value="done-text">Plain Text (Completed)</option>
                    <option value="hide">Hide Actions</option>
                </select>
            </label>
            <label><input type="checkbox" checked onchange="toggleActionItemVisibility('like', this.checked)"> Reaction</label>
            <label><input type="checkbox" checked onchange="toggleActionItemVisibility('comment', this.checked)"> Comment</label>
            <label><input type="checkbox" checked onchange="toggleActionItemVisibility('share', this.checked)"> Share</label>
            <label>Comment Lines:
                <select onchange="setCommentLines(this.value)">
                    <option value="1">1 Line (...)</option>
                    <option value="2" selected>2 Lines (Default)</option>
                    <option value="3">3 Lines (...)</option>
                    <option value="4">4 Lines (...)</option>
                    <option value="full">Full Comment</option>
                    <option value="hide">Hide Comment</option>
                </select>
            </label>
            <label><input type="checkbox" onchange="toggleStatusBadge(this.checked)"> Show Status Badge</label>
            <label><input type="checkbox" onchange="toggleJudgeSheet(this.checked)"> Include Verification Table</label>
            <button onclick="window.print()">🖨️ Print</button>
        </div>
    </div>

    <div class="ticket-grid">
        {''.join(tickets_html)}
    </div>

    <div class="judge-sheet-section">
        <h3 id="sheetTicketCount" style="margin:0 0 8px 0;">Sentra Verification Sheet ({initial_visible_count} Contestants)</h3>
        <table>
            <thead>
                <tr>
                    <th>Serial #</th>
                    <th>Contestant Name</th>
                    <th>Reaction</th>
                    <th>Comment</th>
                    <th>Share</th>
                    <th>Contest Status / Reason</th>
                    <th>Comments Text</th>
                    <th>Shared Caption</th>
                    <th>Profile Reference</th>
                    <th>Shared Post Link</th>
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

