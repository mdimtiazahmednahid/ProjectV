import base64
import datetime
import html
import json
import logging
import os
import re
from typing import Dict, List, Optional, Set
from app.models.share_profile import ContestParticipant
from app.utils.sentra_brand import get_sentra_logo_svg

logger = logging.getLogger(__name__)

VALID_MEANINGFUL_RE = re.compile(r"[a-zA-Z0-9\u0980-\u09FF]")
TAG_OR_MENTION_RE = re.compile(r"[@#][a-zA-Z0-9_\u0980-\u09FF]+")


class LotteryPrintExporter:
    """
    Generates an interactive, print-ready HTML/PDF document containing:
    1. Embedded Live Advanced Filtering & Correct-Answer Keyword Engine (3-Slot Action Chain +
       3-Slot Keyword Chain with Whole-Word Bangla/English boundaries, Contains, Exact, Regex,
       Emoji-Only exclusion, Min Words/Chars, Live Search, and Category Pills).
    2. Customizable Page Layout & Typography:
       - Cards per Row (1, 2, 3, or 4 columns) where 1 or 2 cards/row automatically scales up
         card dimensions, avatars, names, and comment fonts.
       - Cards per Printed Page selector (Auto, 2, 4, 6, 8, 9, 10, 12, 15, 18, 24 cards/page)
         with exact print page-break pagination.
       - Adjustable Comment & Card Font Size scaling (`Auto`, `Comfortable`, `Large`, `XL`, `Jumbo`).
    3. Master Live-Lottery Judge Verification Sheet for instant serial lookup during the live draw.
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
        filter_config: Optional[object] = None,
    ) -> bool:
        try:
            if os.path.dirname(output_path):
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

            target_list = list(participants)

            # Determine initial Qualified vs Disqualified state
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

            qual_flags = [_is_participant_qualified(p) for p in target_list]
            qual_count = sum(1 for q in qual_flags if q)
            disq_count = len(target_list) - qual_count
            total_count = len(target_list)

            if default_scope == "qualified" and qual_count == 0:
                default_scope = "all"
            elif default_scope == "disqualified" and disq_count == 0:
                default_scope = "all"
            elif default_scope not in ("all", "qualified", "disqualified", "correct", "wrong", "invalid", "no_comments"):
                default_scope = "all"

            generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Extract initial filter configuration from desktop app if provided
            init_cfg = {
                "act_f1_on": bool(getattr(filter_config, "act_f1_enabled", True)) if filter_config else True,
                "act_f1_val": str(getattr(filter_config, "act_f1_val", "like") or "like") if filter_config else "like",
                "act_op1": str(getattr(filter_config, "act_op1", "AND") or "AND") if filter_config else "AND",
                "act_f2_on": bool(getattr(filter_config, "act_f2_enabled", True)) if filter_config else True,
                "act_f2_val": str(getattr(filter_config, "act_f2_val", "comment") or "comment") if filter_config else "comment",
                "act_op2": str(getattr(filter_config, "act_op2", "AND") or "AND") if filter_config else "AND",
                "act_f3_on": bool(getattr(filter_config, "act_f3_enabled", True)) if filter_config else True,
                "act_f3_val": str(getattr(filter_config, "act_f3_val", "share") or "share") if filter_config else "share",
                "act_group_right": bool(getattr(filter_config, "act_group_right", False)) if filter_config else False,
                "kw_f1_on": bool(getattr(filter_config, "kw_f1_enabled", True)) if filter_config else True,
                "kw_f1_text": str(getattr(filter_config, "kw_f1_text", "") or getattr(filter_config, "or_keywords", "") or "") if filter_config else "",
                "kw_op1": str(getattr(filter_config, "kw_op1", "AND") or "AND") if filter_config else "AND",
                "kw_f2_on": bool(getattr(filter_config, "kw_f2_enabled", True)) if filter_config else True,
                "kw_f2_text": str(getattr(filter_config, "kw_f2_text", "") or getattr(filter_config, "and_keywords", "") or "") if filter_config else "",
                "kw_op2": str(getattr(filter_config, "kw_op2", "NOT") or "NOT") if filter_config else "NOT",
                "kw_f3_on": bool(getattr(filter_config, "kw_f3_enabled", True)) if filter_config else True,
                "kw_f3_text": str(getattr(filter_config, "kw_f3_text", "") or getattr(filter_config, "not_keywords", "") or "") if filter_config else "",
                "kw_group_right": bool(getattr(filter_config, "kw_group_right", False)) if filter_config else False,
                "match_mode": str(getattr(filter_config, "match_mode", "whole_word") or "whole_word") if filter_config else "whole_word",
                "min_chars": int(getattr(filter_config, "min_comment_length", 0) or 0) if filter_config else 0,
                "min_words": int(getattr(filter_config, "min_word_count", 0) or 0) if filter_config else 0,
                "exclude_emoji": bool(getattr(filter_config, "exclude_invalid_emoji", False)) if filter_config else False,
                "require_tag": bool(getattr(filter_config, "require_mention_or_hashtag", False)) if filter_config else False,
                "include_share_text": bool(getattr(filter_config, "include_share_text", True)) if filter_config else True,
            }
            init_cfg_json = json.dumps(init_cfg, ensure_ascii=False)

            tickets_html = []
            rows_html = []

            all_idx = 0
            qual_idx = 0
            disq_idx = 0

            for p, is_qual in zip(target_list, qual_flags):
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
                comment_list = [c.strip() for c in (p.comment_texts or []) if c and c.strip()]
                share_list = [s.strip() for s in (getattr(p, "share_contents", None) or []) if s and s.strip()]

                full_comment_raw = " | ".join(comment_list)
                if not full_comment_raw and share_list:
                    full_comment_raw = " | ".join(share_list)

                if full_comment_raw:
                    short_raw = full_comment_raw[:180] + ("..." if len(full_comment_raw) > 180 else "")
                    safe_short = f'"{html.escape(short_raw)}"'
                    safe_full = f'"{html.escape(full_comment_raw)}"'
                    is_truncated = "1" if len(full_comment_raw) > 180 else "0"
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

                full_share_caption_raw = " | ".join(share_list)
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
                ev_status = (getattr(ev, "reason_badge", "") or getattr(ev, "status_label", "")) if ev else ""

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
                react_types_str = getattr(p, "combined_reactions", "") or ""
                react_badge_text = getattr(p, "reaction_badge", "") or ("✅ Reaction" if p.liked else "❌ Reaction")
                react_short_label = react_badge_text.replace("✅ ", "").replace("❌ ", "") if react_types_str else "Reaction"

                comment_cls = "act-done" if p.commented else "act-missing"
                comment_sign = "✅" if p.commented else "❌"
                share_cls = "act-done" if p.shared else "act-missing"
                share_sign = "✅" if p.shared else "❌"

                done_meta = (
                    f'<span class="act-item act-like {like_cls}" onclick="toggleSingleAction(this, \'like\')" title="Click to toggle Reaction status">'
                    f'<span class="act-icon">{like_sign} </span>{html.escape(react_short_label)}</span>'
                    f'<span class="act-sep"> · </span>'
                    f'<span class="act-item act-comment {comment_cls}" onclick="toggleSingleAction(this, \'comment\')" title="Click to toggle Comment status">'
                    f'<span class="act-icon">{comment_sign} </span>Comment</span>'
                    f'<span class="act-sep"> · </span>'
                    f'<span class="act-item act-share {share_cls}" onclick="toggleSingleAction(this, \'share\')" title="Click to toggle Share status">'
                    f'<span class="act-icon">{share_sign} </span>Share</span>'
                )

                comments_json_attr = html.escape(json.dumps(comment_list, ensure_ascii=False), quote=True)
                shares_json_attr = html.escape(json.dumps(share_list, ensure_ascii=False), quote=True)
                data_liked = "1" if p.liked else "0"
                data_commented = "1" if p.commented else "0"
                data_shared = "1" if p.shared else "0"
                clean_comment_len = len(full_comment_raw.strip())
                comment_align_cls = (
                    "comment-short"
                    if (clean_comment_len <= 45 and "\n" not in full_comment_raw)
                    else "comment-long"
                )

                tickets_html.append(f"""
                <div class="ticket"
                     data-idx="{all_idx}"
                     data-status="{status_attr}"
                     data-liked="{data_liked}"
                     data-commented="{data_commented}"
                     data-shared="{data_shared}"
                     data-name="{html.escape(p.display_name, quote=True)}"
                     data-url="{html.escape(raw_url, quote=True)}"
                     data-comments="{comments_json_attr}"
                     data-shares="{shares_json_attr}"
                     data-serial-all="{serial_all_str}"
                     data-serial-qual="{serial_qual_str}"
                     data-serial-disq="{serial_disq_str}">
                    <div class="ticket-body">
                        <div class="profile-row" onclick="openTicketProfileUrl(this)" title="Click to open Facebook profile: {html.escape(raw_url or id_hint, quote=True)}" style="cursor:pointer;">
                            <span class="serial">{initial_serial_str}</span>
                            {avatar_tag}
                            <div class="name notranslate" translate="no">{safe_name}</div>
                            <span class="{badge_cls}">{badge_label}</span>
                        </div>
                        <div class="ticket-info">
                            <div class="meta">{done_meta}</div>
                            <div class="comment {comment_align_cls} notranslate" translate="no" data-raw="{html.escape(full_comment_raw, quote=True)}" data-short="{html.escape(safe_short, quote=True)}" data-full="{html.escape(safe_full, quote=True)}" data-truncated="{is_truncated}" onclick="toggleCommentText(this)" title="Click to expand/collapse full comment">{safe_full}</div>
                        </div>
                    </div>
                    <div class="ticket-footer">{footer_html}</div>
                </div>
                """)

                rows_html.append(f"""
                <tr data-idx="{all_idx}" data-status="{status_attr}" data-serial-all="{serial_all_str}" data-serial-qual="{serial_qual_str}" data-serial-disq="{serial_disq_str}">
                    <td class="col-serial"><strong class="row-serial">{initial_serial_str}</strong></td>
                    <td class="notranslate" translate="no">{safe_name}</td>
                    <td class="row-like">{html.escape(react_badge_text)}</td>
                    <td class="row-comment">{'✅ Comment' if p.commented else '❌ Comment'} ({len(comment_list)})</td>
                    <td class="row-share">{'✅ Share' if p.shared else '❌ Share'}</td>
                    <td class="row-status">{badge_label}</td>
                    <td class="notranslate row-comment-text" translate="no">{html.escape(" | ".join(comment_list)[:220])}</td>
                    <td class="notranslate" translate="no">{html.escape(full_share_caption_raw[:180])}</td>
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
<title>Sentra — Live Lottery Tickets, Answer Filter & Verification Sheet</title>
<style>
    * {{ box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans Bengali", Arial, sans-serif;
        margin: 0;
        padding: 16px;
        color: #0f172a;
        background: #f1f5f9;
    }}
    /* Top Brand & Layout Toolbar */
    .toolbar {{
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        color: #f8fafc;
        padding: 12px 16px;
        border-radius: 10px 10px 0 0;
        border: 1px solid #334155;
        border-bottom: none;
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
    }}
    .toolbar-controls {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        font-size: 12.5px;
    }}
    .toolbar select, .filter-panel select, .filter-panel input[type="text"], .filter-panel input[type="number"] {{
        padding: 5px 9px;
        border-radius: 6px;
        border: 1px solid #475569;
        font-weight: 600;
        font-size: 12.5px;
        color: #0f172a;
        background: #ffffff;
    }}
    .toolbar label, .filter-panel label {{
        display: inline-flex;
        align-items: center;
        gap: 5px;
        cursor: pointer;
        font-weight: 600;
        user-select: none;
    }}
    .btn-print {{
        background: #16a34a;
        color: #ffffff;
        border: 1px solid #22c55e;
        padding: 8px 16px;
        font-size: 13.5px;
        font-weight: 800;
        border-radius: 7px;
        cursor: pointer;
        box-shadow: 0 2px 6px rgba(22, 163, 74, 0.35);
    }}
    .btn-print:hover {{
        background: #15803d;
    }}
    .btn-toggle-filter {{
        background: #0284c7;
        color: #ffffff;
        border: 1px solid #38bdf8;
        padding: 7px 12px;
        font-size: 12.5px;
        font-weight: 700;
        border-radius: 6px;
        cursor: pointer;
    }}

    /* Embedded Advanced Filtering & Correct Answer Picker Panel */
    .filter-panel {{
        background: #0f172a;
        color: #e2e8f0;
        padding: 12px 16px;
        border: 1px solid #334155;
        border-radius: 0 0 10px 10px;
        margin-bottom: 16px;
        display: flex;
        flex-direction: column;
        gap: 9px;
    }}
    .filter-panel.collapsed {{
        display: none !important;
    }}
    .filter-row {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        font-size: 12px;
    }}
    .filter-row-label {{
        color: #38bdf8;
        font-weight: 800;
        min-width: 125px;
        font-size: 12px;
    }}
    .slot-pill {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        background: #1e293b;
        border: 1px solid #475569;
        padding: 3px 8px;
        border-radius: 6px;
    }}
    .op-select {{
        background: #334155 !important;
        color: #fbbf24 !important;
        border: 1px solid #64748b !important;
        font-weight: 800 !important;
        padding: 4px 6px !important;
    }}
    .kw-input {{
        min-width: 195px;
        flex: 1;
    }}
    .formula-bar {{
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 12px;
        color: #bae6fd;
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        align-items: center;
        gap: 8px;
    }}
    .category-pills {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        align-items: center;
    }}
    .cat-pill {{
        background: #1e293b;
        color: #e2e8f0;
        border: 1px solid #475569;
        border-radius: 999px;
        padding: 4px 11px;
        font-size: 11.5px;
        font-weight: 700;
        cursor: pointer;
        transition: all 0.12s ease;
    }}
    .cat-pill:hover {{
        border-color: #38bdf8;
        color: #ffffff;
    }}
    .cat-pill.active {{
        background: #0284c7;
        color: #ffffff;
        border: 2px solid #ffffff;
    }}
    .cat-pill.pill-qual.active {{ background: #16a34a; }}
    .cat-pill.pill-wrong.active {{ background: #dc2626; }}
    .cat-pill.pill-invalid.active {{ background: #d97706; }}

    /* Responsive Ticket Grid & Column Layout Modes (1, 2, 3, or 4 Cards per Row) */
    .ticket-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        width: 100%;
    }}
    body.cols-1 .ticket-grid {{
        grid-template-columns: minmax(0, 1fr);
        gap: 14px;
    }}
    body.cols-2 .ticket-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
    }}
    body.cols-3 .ticket-grid {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 11px;
    }}
    body.cols-4 .ticket-grid {{
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 8px;
    }}

    .ticket {{
        background: #ffffff;
        border-radius: 8px;
        padding: 11px 13px;
        page-break-inside: avoid;
        break-inside: avoid;
        overflow: hidden;
        min-width: 0;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }}
    .ticket.hidden-by-filter {{
        display: none !important;
    }}
    /* Automatic page break marker when admin selects fixed Cards per Page */
    .page-break-divider {{
        grid-column: 1 / -1;
        height: 0;
        margin: 0;
        padding: 0;
        border: none;
        page-break-after: always;
        break-after: page;
    }}
    @media screen {{
        .page-break-divider {{
            height: 18px;
            border-bottom: 2px dashed #94a3b8;
            margin: 6px 0 10px 0;
            position: relative;
        }}
        .page-break-divider::after {{
            content: attr(data-page-label);
            position: absolute;
            right: 8px;
            top: -2px;
            background: #cbd5e1;
            color: #1e293b;
            font-size: 10.5px;
            font-weight: 800;
            padding: 1px 8px;
            border-radius: 4px;
        }}
    }}

    /* Border & Easy-Cut Grid Design Classes */
    body.border-solid .ticket {{
        border: 1.5px solid #000000;
    }}
    body.border-dashed .ticket {{
        border: 1.5px dashed #000000;
    }}
    body.border-none .ticket {{
        border: none;
        box-shadow: 0 1px 4px rgba(0,0,0,0.12);
    }}
    /* Easy-Cut Continuous Black Line Grid (Zero gap, shared straight black cut lines across full row & column) */
    body.border-cut-solid .ticket-grid,
    body.border-cut-dashed .ticket-grid {{
        gap: 0 !important;
        padding-left: 1.5px;
        padding-top: 1.5px;
        background: #ffffff;
    }}
    body.border-cut-solid .ticket {{
        border-radius: 0 !important;
        border: 1.5px solid #000000 !important;
        margin-left: -1.5px;
        margin-top: -1.5px;
        box-shadow: none !important;
    }}
    body.border-cut-dashed .ticket {{
        border-radius: 0 !important;
        border: 1.5px dashed #000000 !important;
        margin-left: -1.5px;
        margin-top: -1.5px;
        box-shadow: none !important;
    }}
    /* Row 1: Serial ID (#0001) + Profile Avatar + Contestant Name all on the FIRST ROW to save vertical space for comments */
    .profile-row {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 7px;
        width: 100%;
        min-width: 0;
        position: relative;
        border-bottom: 1px solid #e2e8f0;
        padding-bottom: 5px;
        margin-bottom: 3px;
    }}
    .profile-row:hover .name {{
        color: #0b5ed7;
        text-decoration: underline;
    }}
    body.id-left .profile-row,
    body.align-left .profile-row {{
        justify-content: flex-start;
    }}
    body.id-after-name .profile-row .serial {{
        order: 3;
    }}
    body.id-corner-left .profile-row .serial {{
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
    }}
    body.id-hide .serial {{
        display: none !important;
    }}
    .serial {{
        font-size: 10px;
        font-weight: 800;
        color: #0b5ed7;
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        padding: 1.5px 6px;
        border-radius: 5px;
        text-align: center;
        line-height: 1.15;
        flex-shrink: 0;
    }}
    body.custom-id-size .serial {{
        font-size: var(--serial-custom-size, 10px) !important;
    }}
    .badge {{
        display: none;
        font-size: 9.5px;
        font-weight: 700;
        background: #dcfce7;
        color: #166534;
        padding: 2px 6px;
        border-radius: 4px;
        margin-left: 4px;
        white-space: nowrap;
        flex-shrink: 0;
    }}
    .badge-disq {{
        background: #fee2e2;
        color: #991b1b;
    }}
    body.show-badge .badge {{
        display: inline-block;
    }}
    .ticket-body {{
        display: flex;
        flex-direction: column;
        align-items: stretch;
        gap: 3px;
        min-width: 0;
        flex: 1;
    }}
    .avatar, .avatar-placeholder {{
        width: 32px;
        height: 32px;
        border-radius: 50%;
        flex-shrink: 0;
        object-fit: cover;
        border: 1.5px solid #cbd5e1;
        margin-top: 0;
    }}
    .avatar-placeholder {{
        background: #e2e8f0;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        color: #334155;
        font-size: 12px;
    }}
    .ticket-info {{
        overflow: hidden;
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        align-items: stretch;
    }}
    .name {{
        font-size: 14.5px;
        font-weight: 800;
        color: #0f172a;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        text-align: center;
    }}
    /* Row 2: Reaction · Comment · Share (Slightly bigger & well-fitted) */
    .meta {{
        font-size: 11.8px;
        font-weight: 700;
        margin-top: 1px;
        display: flex;
        flex-wrap: nowrap;
        white-space: nowrap;
        justify-content: center;
        align-items: center;
        gap: 4px;
        width: 100%;
        overflow: hidden;
    }}
    body.id-left .meta,
    body.align-left .meta {{
        justify-content: flex-start;
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
        color: #94a3b8;
        margin: 0 3px;
        flex-shrink: 0;
    }}
    /* Action Display Customization Modes */
    body.actions-done-icons .act-missing {{ display: none !important; }}
    body.actions-done-icons .act-sep {{ display: none !important; }}
    body.actions-done-icons .act-done {{ margin-right: 6px; }}
    body.actions-done-text .act-missing {{ display: none !important; }}
    body.actions-done-text .act-icon {{ display: none !important; }}
    body.actions-done-text .act-sep {{ display: none !important; }}
    body.actions-done-text .act-done {{ margin-right: 6px; }}
    body.actions-hide .meta {{ display: none !important; }}
    body.hide-act-like .act-like {{ display: none !important; }}
    body.hide-act-comment .act-comment {{ display: none !important; }}
    body.hide-act-share .act-share {{ display: none !important; }}

    /* Row 4: Comment (Starts from center by default for short comments, starts from left when bigger/multi-line) */
    .comment {{
        font-size: 13.5px;
        line-height: 1.44;
        color: #1e293b;
        font-weight: 500;
        background: transparent;
        border: none;
        padding: 0;
        margin-top: 4px;
        width: 100%;
        text-align: center;
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
    .comment.comment-short {{
        text-align: center;
    }}
    .comment.comment-long {{
        text-align: left;
    }}
    body.comment-align-center .comment {{
        text-align: center !important;
    }}
    body.comment-align-left .comment {{
        text-align: left !important;
    }}
    .comment mark.kw-hit {{
        background: #fef08a;
        color: #854d0e;
        font-weight: 800;
        padding: 0 3px;
        border-radius: 3px;
    }}

    /* Automatic Card & Font Scaling when 2 Cards/Row or 1 Card/Row is selected */
    body.cols-2 .ticket {{
        padding: 14px 16px;
    }}
    body.cols-2 .serial {{
        font-size: 15.5px;
    }}
    body.cols-2 .badge {{
        font-size: 11.5px;
        padding: 3px 8px;
    }}
    body.cols-2 .avatar, body.cols-2 .avatar-placeholder {{
        width: 44px;
        height: 44px;
        font-size: 15px;
    }}
    body.cols-2 .name {{
        font-size: 16.5px;
    }}
    body.cols-2 .meta {{
        font-size: 13.2px;
        margin-top: 2px;
        gap: 6px;
    }}
    body.cols-2 .comment {{
        font-size: 15.5px;
        line-height: 1.48;
        padding: 0;
        margin-top: 5px;
    }}
    body.cols-2 .ticket-footer {{
        font-size: 10.5px;
        margin-top: 8px;
    }}

    body.cols-1 .ticket {{
        padding: 18px 22px;
    }}
    body.cols-1 .serial {{
        font-size: 17px;
    }}
    body.cols-1 .badge {{
        font-size: 13px;
        padding: 4px 10px;
    }}
    body.cols-1 .avatar, body.cols-1 .avatar-placeholder {{
        width: 54px;
        height: 54px;
        font-size: 18px;
    }}
    body.cols-1 .name {{
        font-size: 19px;
    }}
    body.cols-1 .meta {{
        font-size: 14.8px;
        margin-top: 3px;
        gap: 8px;
    }}
    body.cols-1 .comment {{
        font-size: 18px;
        line-height: 1.5;
        padding: 0;
        margin-top: 6px;
    }}
    body.cols-1 .ticket-footer {{
        font-size: 12px;
        margin-top: 10px;
    }}

    body.cols-4 .ticket {{
        padding: 8px 9px;
    }}
    body.cols-4 .serial {{
        font-size: 12.5px;
    }}
    body.cols-4 .avatar, body.cols-4 .avatar-placeholder {{
        width: 28px;
        height: 28px;
        font-size: 10.5px;
    }}
    body.cols-4 .name {{
        font-size: 12.5px;
    }}
    body.cols-4 .meta {{
        font-size: 10.2px;
        gap: 2px;
    }}
    body.cols-4 .comment {{
        font-size: 12px;
        padding: 0;
    }}

    /* Explicit Font Size Override Classes (Admin Font Zoom Selector) */
    body.font-md .comment {{ font-size: 14.5px !important; }}
    body.font-md .name {{ font-size: 15.5px !important; }}
    body.font-md .meta {{ font-size: 12.4px !important; }}
    body.font-lg .comment {{ font-size: 16.5px !important; }}
    body.font-lg .name {{ font-size: 17.5px !important; }}
    body.font-lg .meta {{ font-size: 13.5px !important; }}
    body.font-xl .comment {{ font-size: 19px !important; line-height: 1.5 !important; }}
    body.font-xl .name {{ font-size: 19.5px !important; }}
    body.font-xl .meta {{ font-size: 14.8px !important; }}
    body.font-jumbo .comment {{ font-size: 22px !important; line-height: 1.52 !important; }}
    body.font-jumbo .name {{ font-size: 22px !important; }}
    body.font-jumbo .meta {{ font-size: 16px !important; }}

    /* Comment Line Clamping Modes */
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
    body.comment-lines-5 .comment {{
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 5;
        line-clamp: 5;
        white-space: normal;
    }}
    body.comment-lines-6 .comment {{
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 6;
        line-clamp: 6;
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
        border-top: 1px solid #f1f5f9;
        font-size: 9.5px;
        color: #64748b;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        text-align: center;
    }}
    body.id-center .ticket-footer {{
        text-align: center;
    }}
    body.id-left .ticket-footer,
    body.align-left .ticket-footer {{
        text-align: left;
    }}
    body.fb-link-center .ticket-footer {{
        text-align: center !important;
    }}
    body.fb-link-left .ticket-footer {{
        text-align: left !important;
    }}
    /* When FB Link is hidden, reclaim the bottom footer space directly for comments (+1 extra visible line & full flex height) */
    body.fb-link-hide .ticket-footer {{
        display: none !important;
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
    }}
    body.fb-link-hide.comment-lines-2 .comment {{
        -webkit-line-clamp: 3;
        line-clamp: 3;
    }}
    body.fb-link-hide.comment-lines-3 .comment {{
        -webkit-line-clamp: 4;
        line-clamp: 4;
    }}
    body.fb-link-hide.comment-lines-4 .comment {{
        -webkit-line-clamp: 5;
        line-clamp: 5;
    }}
    body.fb-link-hide .comment {{
        margin-bottom: 1px;
    }}
    .profile-link {{
        color: #475569;
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
        font-size: 12px;
    }}
    th, td {{
        border: 1px solid #cbd5e1;
        padding: 6px 8px;
        text-align: left;
    }}
    th {{
        background: #e2e8f0;
        color: #0f172a;
    }}
    tr.hidden-by-filter {{
        display: none !important;
    }}
    .col-serial {{
        width: 65px;
        color: #0b5ed7;
    }}
    .col-url {{
        font-size: 10.5px;
        color: #475569;
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
        .no-print, .toolbar, .filter-panel {{
            display: none !important;
        }}
        /* Respect the user's selected column count (1, 2, 3, or 4 cards per row) when printing! */
        body.cols-1 .ticket-grid {{
            grid-template-columns: minmax(0, 1fr) !important;
            gap: 10px !important;
        }}
        body.cols-2 .ticket-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 9px !important;
        }}
        body.cols-3 .ticket-grid {{
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
            gap: 7px !important;
        }}
        body.cols-4 .ticket-grid {{
            grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
            gap: 5px !important;
        }}
        body.border-cut-solid .ticket-grid,
        body.border-cut-dashed .ticket-grid {{
            gap: 0 !important;
        }}
        body.border-none .ticket {{
            box-shadow: none !important;
            border: 1px solid #e2e8f0 !important;
        }}
    }}
</style>
<script>
    const INITIAL_FILTER_CONFIG = {init_cfg_json};
    let activeCategory = "{default_scope}";
    let cardsPerPage = 10; // Default: 10 Cards / Page

    const BN_DIGIT_MAP = {{
        '০': '0', '১': '1', '২': '2', '৩': '3', '৪': '4',
        '৫': '5', '৬': '6', '৭': '7', '৮': '8', '৯': '9'
    }};

    function normalizeDigits(str) {{
        return (str || "").replace(/[০-৯]/g, function(ch) {{ return BN_DIGIT_MAP[ch] || ch; }});
    }}

    function escapeRegExp(str) {{
        return (str || "").replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
    }}

    function parseKeywordList(raw) {{
        if (!raw || !raw.trim()) return [];
        return raw.split(/[,;\\n]+/).map(function(s) {{ return s.trim(); }}).filter(Boolean);
    }}

    function isMeaningfulText(text) {{
        return /[a-zA-Z0-9\\u0980-\\u09FF]/.test(text || "");
    }}

    function matchSingleKeyword(commentText, keyword, matchMode) {{
        if (!keyword || !keyword.trim()) return true;
        if (!commentText) return false;

        const normText = normalizeDigits(commentText.toLowerCase());
        const normKw = normalizeDigits(keyword.trim().toLowerCase());
        if (!normKw) return true;

        if (matchMode === "exact") {{
            const strippedText = normText.replace(/^[^a-zA-Z0-9\\u0980-\\u09FF]+|[^a-zA-Z0-9\\u0980-\\u09FF]+$/g, "").trim();
            const strippedKw = normKw.replace(/^[^a-zA-Z0-9\\u0980-\\u09FF]+|[^a-zA-Z0-9\\u0980-\\u09FF]+$/g, "").trim();
            return Boolean(strippedKw) && strippedText === strippedKw;
        }}
        if (matchMode === "regex") {{
            try {{
                const re = new RegExp(keyword.trim(), "i");
                return re.test(commentText);
            }} catch (e) {{
                return normText.indexOf(normKw) !== -1;
            }}
        }}
        if (matchMode === "contains") {{
            return normText.indexOf(normKw) !== -1;
        }}
        // Default: whole_word (Bangla + English word boundary)
        const pattern = "(?:^|[^a-zA-Z0-9\\u0980-\\u09FF])" + escapeRegExp(normKw) + "(?=$|[^a-zA-Z0-9\\u0980-\\u09FF])";
        try {{
            const re = new RegExp(pattern, "i");
            return re.test(normText);
        }} catch (e) {{
            return normText.indexOf(normKw) !== -1;
        }}
    }}

    function matchAnyKeywordInTexts(texts, keywords, matchMode) {{
        if (!keywords || keywords.length === 0) return true;
        if (!texts || texts.length === 0) return false;
        for (let i = 0; i < texts.length; i++) {{
            for (let j = 0; j < keywords.length; j++) {{
                if (matchSingleKeyword(texts[i], keywords[j], matchMode)) {{
                    return true;
                }}
            }}
        }}
        return false;
    }}

    function applyBoolOp(lhs, op, rhs) {{
        const o = (op || "AND").toUpperCase();
        if (o === "OR") return lhs || rhs;
        if (o === "NOT" || o === "AND_NOT") return lhs && (!rhs);
        if (o === "OR_NOT") return lhs || (!rhs);
        return lhs && rhs;
    }}

    function evaluateThreeSlotChain(s1On, v1, op1, s2On, v2, op2, s3On, v3, groupRight) {{
        if (s1On && s2On && s3On) {{
            if (groupRight) {{
                const r23 = applyBoolOp(v2, op2, v3);
                return applyBoolOp(v1, op1, r23);
            }}
            const r12 = applyBoolOp(v1, op1, v2);
            return applyBoolOp(r12, op2, v3);
        }}
        if (s1On && s2On) return applyBoolOp(v1, op1, v2);
        if (s1On && s3On) return applyBoolOp(v1, op2, v3);
        if (s2On && s3On) {{
            const start2 = (op1 === "NOT" || op1 === "AND_NOT") ? (!v2) : v2;
            return applyBoolOp(start2, op2, v3);
        }}
        if (s1On) return v1;
        if (s2On) return (op1 === "NOT" || op1 === "AND_NOT") ? (!v2) : v2;
        if (s3On) return (op2 === "NOT" || op2 === "AND_NOT") ? (!v3) : v3;
        return true;
    }}

    function evalSingleActionVal(liked, commented, shared, val) {{
        const v = (val || "none").toLowerCase();
        if (v === "like" || v === "reaction") return liked;
        if (v === "comment") return commented;
        if (v === "share") return shared;
        if (v === "not_like") return !liked;
        if (v === "not_comment") return !commented;
        if (v === "not_share") return !shared;
        return true;
    }}

    function highlightMatchedKeywords(rawText, positiveKeywords) {{
        const escaped = (rawText || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
        if (!positiveKeywords || positiveKeywords.length === 0 || !rawText) {{
            return '"' + escaped + '"';
        }}
        let result = escaped;
        positiveKeywords.forEach(function(kw) {{
            const cleanKw = (kw || "").trim();
            if (!cleanKw) return;
            try {{
                const re = new RegExp("(" + escapeRegExp(cleanKw) + ")", "gi");
                result = result.replace(re, '<mark class="kw-hit">$1</mark>');
            }} catch (e) {{}}
        }});
        return '"' + result + '"';
    }}

    function applyLiveFilters() {{
        const f1On = document.getElementById("actF1On").checked && document.getElementById("actF1Val").value !== "none";
        const f1Val = document.getElementById("actF1Val").value;
        const op1 = document.getElementById("actOp1").value;
        const f2On = document.getElementById("actF2On").checked && document.getElementById("actF2Val").value !== "none";
        const f2Val = document.getElementById("actF2Val").value;
        const op2 = document.getElementById("actOp2").value;
        const f3On = document.getElementById("actF3On").checked && document.getElementById("actF3Val").value !== "none";
        const f3Val = document.getElementById("actF3Val").value;
        const actGroupRight = document.getElementById("actGroupRight").checked;

        const kw1Raw = document.getElementById("kwF1Text").value || "";
        const kw1List = parseKeywordList(kw1Raw);
        const kw1On = document.getElementById("kwF1On").checked && kw1List.length > 0;
        const kwOp1 = document.getElementById("kwOp1").value;

        const kw2Raw = document.getElementById("kwF2Text").value || "";
        const kw2List = parseKeywordList(kw2Raw);
        const kw2On = document.getElementById("kwF2On").checked && kw2List.length > 0;
        const kwOp2 = document.getElementById("kwOp2").value;

        const kw3Raw = document.getElementById("kwF3Text").value || "";
        const kw3List = parseKeywordList(kw3Raw);
        const kw3On = document.getElementById("kwF3On").checked && kw3List.length > 0;

        const hasKeywordRules = kw1On || kw2On || kw3On;
        const matchMode = document.getElementById("matchModeSelect").value;
        const minChars = parseInt(document.getElementById("minCharsInput").value || "0", 10) || 0;
        const minWords = parseInt(document.getElementById("minWordsInput").value || "0", 10) || 0;
        const excludeEmoji = document.getElementById("excludeEmojiChk").checked;
        const requireTag = document.getElementById("requireTagChk").checked;
        const includeShares = document.getElementById("includeShareTextChk").checked;
        const searchQuery = (document.getElementById("liveSearchInput").value || "").trim().toLowerCase();

        // Collect positive keywords for visual highlighting inside ticket comments
        let highlightKws = [];
        if (kw1On) highlightKws = highlightKws.concat(kw1List);
        if (kw2On && kwOp1 !== "NOT") highlightKws = highlightKws.concat(kw2List);
        if (kw3On && kwOp2 !== "NOT") highlightKws = highlightKws.concat(kw3List);

        const counts = {{
            all: 0,
            qualified: 0,
            correct: 0,
            wrong: 0,
            invalid: 0,
            no_comments: 0,
            disqualified: 0
        }};

        const rowMap = {{}};
        document.querySelectorAll("tbody tr[data-idx]").forEach(function(r) {{
            rowMap[r.getAttribute("data-idx")] = r;
        }});

        const tickets = Array.from(document.querySelectorAll(".ticket[data-idx]"));

        tickets.forEach(function(ticketEl) {{
            const idx = ticketEl.getAttribute("data-idx");
            const liked = ticketEl.getAttribute("data-liked") === "1";
            const commented = ticketEl.getAttribute("data-commented") === "1";
            const shared = ticketEl.getAttribute("data-shared") === "1";
            const name = ticketEl.getAttribute("data-name") || "";
            const url = ticketEl.getAttribute("data-url") || "";
            let comments = [];
            let shares = [];
            try {{ comments = JSON.parse(ticketEl.getAttribute("data-comments") || "[]"); }} catch (e) {{}}
            try {{ shares = JSON.parse(ticketEl.getAttribute("data-shares") || "[]"); }} catch (e) {{}}

            const evalTexts = includeShares ? comments.concat(shares) : comments.slice();
            const combinedText = evalTexts.join(" | ");
            const hasComment = commented || evalTexts.length > 0;
            const hasMeaningful = evalTexts.some(isMeaningfulText);
            const isInvalidEmoji = hasComment && !hasMeaningful;

            // 1. Action Chain Evaluation
            const vA1 = f1On ? evalSingleActionVal(liked, commented, shared, f1Val) : true;
            const vA2 = f2On ? evalSingleActionVal(liked, commented, shared, f2Val) : true;
            const vA3 = f3On ? evalSingleActionVal(liked, commented, shared, f3Val) : true;
            const passesAction = evaluateThreeSlotChain(f1On, vA1, op1, f2On, vA2, op2, f3On, vA3, actGroupRight);

            // 2. Keyword Chain Evaluation
            let passesKeyword = true;
            let isCorrectAnswer = false;
            let isWrongAnswer = false;
            if (hasKeywordRules) {{
                if (!hasComment) {{
                    passesKeyword = false;
                }} else {{
                    const m1 = kw1On ? matchAnyKeywordInTexts(evalTexts, kw1List, matchMode) : true;
                    const m2 = kw2On ? matchAnyKeywordInTexts(evalTexts, kw2List, matchMode) : true;
                    const m3 = kw3On ? matchAnyKeywordInTexts(evalTexts, kw3List, matchMode) : true;
                    passesKeyword = evaluateThreeSlotChain(kw1On, m1, kwOp1, kw2On, m2, kwOp2, kw3On, m3, false);
                    if (passesKeyword) {{
                        isCorrectAnswer = true;
                    }} else {{
                        isWrongAnswer = true;
                    }}
                }}
            }} else if (hasComment && !isInvalidEmoji) {{
                isCorrectAnswer = true;
            }}

            // 3. Content Constraints (Min chars, Min words, Emoji-only, @Mention/#Hashtag)
            let passesContent = true;
            if (excludeEmoji && isInvalidEmoji) passesContent = false;
            if (minChars > 0) {{
                const maxLen = evalTexts.reduce(function(acc, t) {{ return Math.max(acc, (t || "").trim().length); }}, 0);
                if (maxLen < minChars) passesContent = false;
            }}
            if (minWords > 0) {{
                const maxWords = evalTexts.reduce(function(acc, t) {{
                    const w = (t || "").trim().split(/\\s+/).filter(Boolean).length;
                    return Math.max(acc, w);
                }}, 0);
                if (maxWords < minWords) passesContent = false;
            }}
            if (requireTag) {{
                const hasTag = evalTexts.some(function(t) {{ return /[@#][a-zA-Z0-9_\\u0980-\\u09FF]+/.test(t || ""); }});
                if (!hasTag) passesContent = false;
            }}

            const isQualified = passesAction && passesKeyword && passesContent;
            const isDisqualified = !isQualified;

            counts.all++;
            if (isQualified) counts.qualified++;
            if (isDisqualified) counts.disqualified++;
            if (!hasComment) counts.no_comments++;
            else if (isInvalidEmoji) counts.invalid++;
            if (isCorrectAnswer) counts.correct++;
            if (isWrongAnswer) counts.wrong++;

            // Update card status attribute & badge text
            ticketEl.setAttribute("data-status", isQualified ? "qualified" : "disqualified");
            ticketEl.setAttribute("data-correct", isCorrectAnswer ? "1" : "0");
            ticketEl.setAttribute("data-wrong", isWrongAnswer ? "1" : "0");
            ticketEl.setAttribute("data-invalid", isInvalidEmoji ? "1" : "0");
            ticketEl.setAttribute("data-nocomment", !hasComment ? "1" : "0");

            const badgeEl = ticketEl.querySelector(".badge");
            const actionsDoneCount = (liked ? 1 : 0) + (commented ? 1 : 0) + (shared ? 1 : 0);
            let badgeText = "";
            if (isQualified) {{
                badgeText = (hasKeywordRules && isCorrectAnswer)
                    ? "✅ CORRECT ANSWER · ELIGIBLE ✓"
                    : (actionsDoneCount === 3 ? "ELIGIBLE 3/3 ✓" : "QUALIFIED (" + actionsDoneCount + "/3) ✓");
                if (badgeEl) {{
                    badgeEl.className = "badge badge-qual";
                    badgeEl.textContent = badgeText;
                }}
            }} else {{
                let reasons = [];
                if (!passesAction) {{
                    if (!liked) reasons.push("No Reaction");
                    if (!commented) reasons.push("No Comment");
                    if (!shared) reasons.push("No Share");
                }}
                if (isWrongAnswer) reasons.push("Wrong Answer");
                else if (hasKeywordRules && !hasComment) reasons.push("No Answer");
                if (excludeEmoji && isInvalidEmoji) reasons.push("Emoji-Only");
                if (!passesContent && reasons.length === 0) reasons.push("Filter Mismatch");
                badgeText = "DISQUALIFIED (" + (reasons.join(", ") || (actionsDoneCount + "/3")) + ") ✗";
                if (badgeEl) {{
                    badgeEl.className = "badge badge-disq";
                    badgeEl.textContent = badgeText;
                }}
            }}

            // Highlight matched keywords inside comment box
            const commentEl = ticketEl.querySelector(".comment");
            if (commentEl) {{
                const rawC = commentEl.getAttribute("data-raw") || "";
                if (rawC) {{
                    commentEl.innerHTML = highlightMatchedKeywords(rawC, highlightKws);
                }}
            }}

            // Check category visibility + search query
            let matchesCategory = true;
            if (activeCategory === "qualified") matchesCategory = isQualified;
            else if (activeCategory === "disqualified") matchesCategory = isDisqualified;
            else if (activeCategory === "correct") matchesCategory = isCorrectAnswer;
            else if (activeCategory === "wrong") matchesCategory = isWrongAnswer;
            else if (activeCategory === "invalid") matchesCategory = isInvalidEmoji;
            else if (activeCategory === "no_comments") matchesCategory = !hasComment;

            let matchesSearch = true;
            if (searchQuery) {{
                const hay = (name + " " + combinedText + " " + url + " #" + String(idx).padStart(4, "0")).toLowerCase();
                matchesSearch = hay.indexOf(searchQuery) !== -1;
            }}

            const isVisible = matchesCategory && matchesSearch;
            ticketEl.classList.toggle("hidden-by-filter", !isVisible);

            const rowEl = rowMap[idx];
            if (rowEl) {{
                rowEl.classList.toggle("hidden-by-filter", !isVisible);
                const rowStatus = rowEl.querySelector(".row-status");
                if (rowStatus) rowStatus.textContent = badgeText;
            }}
        }});

        // Sequentially number visible tickets (#0001, #0002, ...) and rebuild page-break dividers
        document.querySelectorAll(".page-break-divider").forEach(function(el) {{ el.remove(); }});
        let visibleCount = 0;
        const gridEl = document.querySelector(".ticket-grid");

        tickets.forEach(function(ticketEl) {{
            const idx = ticketEl.getAttribute("data-idx");
            const rowEl = rowMap[idx];
            if (!ticketEl.classList.contains("hidden-by-filter")) {{
                visibleCount++;
                const serialStr = "#" + String(visibleCount).padStart(4, "0");
                const serialSpan = ticketEl.querySelector(".serial");
                if (serialSpan) serialSpan.textContent = serialStr;
                if (rowEl) {{
                    const rowSerial = rowEl.querySelector(".row-serial");
                    if (rowSerial) rowSerial.textContent = serialStr;
                }}
                if (cardsPerPage > 0 && visibleCount % cardsPerPage === 0 && gridEl) {{
                    const pageNum = Math.floor(visibleCount / cardsPerPage);
                    const brk = document.createElement("div");
                    brk.className = "page-break-divider";
                    brk.setAttribute("data-page-label", "End of Page " + pageNum + " (" + cardsPerPage + " cards/page)");
                    ticketEl.insertAdjacentElement("afterend", brk);
                }}
            }} else if (rowEl) {{
                const rowSerial = rowEl.querySelector(".row-serial");
                if (rowSerial) rowSerial.textContent = "-";
            }}
        }});

        // Update Category Pill counts & percentages
        const total = Math.max(counts.all, 1);
        const pct = function(n) {{ return counts.all > 0 ? " (" + ((n / total) * 100).toFixed(1) + "%)" : ""; }};
        const setPill = function(id, label, n, showPct) {{
            const el = document.getElementById(id);
            if (el) el.textContent = label + ": " + n + (showPct ? pct(n) : "");
        }};
        setPill("pillAll", "📋 All", counts.all, false);
        setPill("pillQual", "🏆 Qualified Winners", counts.qualified, true);
        setPill("pillCorrect", "✅ Correct Answer", counts.correct, true);
        setPill("pillWrong", "❌ Wrong Answer", counts.wrong, true);
        setPill("pillInvalid", "⚠️ Invalid / Emoji", counts.invalid, true);
        setPill("pillNoComm", "📝 No Comments", counts.no_comments, true);
        setPill("pillDisq", "⛔ Disqualified", counts.disqualified, true);

        // Also update the Show dropdown labels & header counters
        const scopeSel = document.getElementById("scopeSelect");
        if (scopeSel && scopeSel.value !== activeCategory) {{
            scopeSel.value = activeCategory;
        }}
        const titleCountEl = document.getElementById("toolbarTicketCount");
        if (titleCountEl) {{
            titleCountEl.textContent = "Sentra Lottery Slips (" + visibleCount + " Tickets)";
        }}
        const sheetCountEl = document.getElementById("sheetTicketCount");
        if (sheetCountEl) {{
            sheetCountEl.textContent = "Sentra Verification Sheet (" + visibleCount + " Contestants)";
        }}

        // Update Page Estimate badge
        const pageEstEl = document.getElementById("pageEstimateBadge");
        if (pageEstEl) {{
            if (cardsPerPage > 0) {{
                const pages = Math.max(1, Math.ceil(visibleCount / cardsPerPage));
                pageEstEl.textContent = "📄 " + pages + (pages === 1 ? " Page" : " Pages") + " (" + cardsPerPage + " cards/page)";
            }} else {{
                pageEstEl.textContent = "📄 Auto Pagination (" + visibleCount + " visible)";
            }}
        }}

        updateCommentAlignments();
    }}

    function updateCommentAlignments() {{
        document.querySelectorAll(".ticket:not(.hidden-by-filter) .comment").forEach(function(el) {{
            const raw = (el.getAttribute("data-raw") || "").trim();
            const cs = window.getComputedStyle(el);
            const lh = parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) * 1.44) || 19.5;
            const isMultiLineRendered = el.scrollHeight > (lh * 1.45);
            const isLongText = raw.length > 45 || raw.indexOf("\\n") !== -1 || isMultiLineRendered;
            el.classList.toggle("comment-long", isLongText);
            el.classList.toggle("comment-short", !isLongText);
        }});
    }}

    function setTicketScope(scopeVal) {{
        activeCategory = scopeVal;
        document.querySelectorAll(".cat-pill").forEach(function(btn) {{
            btn.classList.toggle("active", btn.getAttribute("data-cat") === scopeVal);
        }});
        applyLiveFilters();
    }}

    function setColumnsPerRow(colsVal) {{
        document.body.classList.remove("cols-1", "cols-2", "cols-3", "cols-4");
        document.body.classList.add("cols-" + colsVal);
        updateCommentAlignments();
    }}

    function setCardsPerPage(val) {{
        cardsPerPage = parseInt(val || "0", 10) || 0;
        applyLiveFilters();
    }}

    function setFontScale(scaleVal) {{
        document.body.classList.remove("font-auto", "font-md", "font-lg", "font-xl", "font-jumbo");
        document.body.classList.add("font-" + scaleVal);
        updateCommentAlignments();
    }}

    function setIdSize(sizeVal) {{
        if (!sizeVal || sizeVal === "auto") {{
            document.body.classList.remove("custom-id-size");
            document.body.style.removeProperty("--serial-custom-size");
        }} else {{
            document.body.classList.add("custom-id-size");
            document.body.style.setProperty("--serial-custom-size", sizeVal);
        }}
    }}

    function setCommentAlignMode(modeVal) {{
        document.body.classList.remove("comment-align-center", "comment-align-left");
        if (modeVal === "center" || modeVal === "left") {{
            document.body.classList.add("comment-align-" + modeVal);
        }} else {{
            updateCommentAlignments();
        }}
    }}

    function toggleFilterPanel() {{
        const panel = document.getElementById("advancedFilterPanel");
        if (panel) panel.classList.toggle("collapsed");
    }}

    function resetAllFilterRules() {{
        document.getElementById("actF1On").checked = true;
        document.getElementById("actF1Val").value = "like";
        document.getElementById("actOp1").value = "AND";
        document.getElementById("actF2On").checked = true;
        document.getElementById("actF2Val").value = "comment";
        document.getElementById("actOp2").value = "AND";
        document.getElementById("actF3On").checked = true;
        document.getElementById("actF3Val").value = "share";
        document.getElementById("actGroupRight").checked = false;

        document.getElementById("kwF1On").checked = true;
        document.getElementById("kwF1Text").value = "";
        document.getElementById("kwOp1").value = "AND";
        document.getElementById("kwF2On").checked = true;
        document.getElementById("kwF2Text").value = "";
        document.getElementById("kwOp2").value = "NOT";
        document.getElementById("kwF3On").checked = true;
        document.getElementById("kwF3Text").value = "";
        document.getElementById("matchModeSelect").value = "whole_word";
        document.getElementById("minCharsInput").value = "0";
        document.getElementById("minWordsInput").value = "0";
        document.getElementById("excludeEmojiChk").checked = false;
        document.getElementById("requireTagChk").checked = false;
        document.getElementById("includeShareTextChk").checked = true;
        document.getElementById("liveSearchInput").value = "";
        setTicketScope("all");
    }}

    function setBorderStyle(styleVal) {{
        document.body.classList.remove("border-solid", "border-dashed", "border-none", "border-cut-solid", "border-cut-dashed");
        document.body.classList.add("border-" + styleVal);
    }}
    function setIdPosition(posVal) {{
        document.body.classList.remove("id-center", "id-after-name", "id-corner-left", "id-left", "id-hide", "align-left");
        document.body.classList.add("id-" + posVal);
        const fbSel = document.getElementById("fbLinkSelect");
        if (fbSel && fbSel.value !== "hide" && (posVal === "center" || posVal === "left")) {{
            fbSel.value = posVal;
            setFbLinkMode(posVal);
        }}
    }}
    function setFbLinkMode(modeVal) {{
        document.body.classList.remove("fb-link-center", "fb-link-left", "fb-link-hide");
        if (modeVal === "center" || modeVal === "left" || modeVal === "hide") {{
            document.body.classList.add("fb-link-" + modeVal);
        }}
        const fbSel = document.getElementById("fbLinkSelect");
        if (fbSel && fbSel.value !== modeVal) {{
            fbSel.value = modeVal;
        }}
        const fbChk = document.getElementById("showFbLinkChk");
        if (fbChk) {{
            fbChk.checked = (modeVal !== "hide");
        }}
        updateCommentAlignments();
    }}
    function toggleFbLinkCheckbox(checked) {{
        if (!checked) {{
            setFbLinkMode("hide");
        }} else {{
            const isLeft = document.body.classList.contains("id-left") || document.body.classList.contains("align-left");
            setFbLinkMode(isLeft ? "left" : "center");
        }}
    }}
    function openTicketProfileUrl(el) {{
        if (!el) return;
        const ticketEl = el.closest(".ticket");
        if (!ticketEl) return;
        const rawUrl = (ticketEl.getAttribute("data-url") || "").trim();
        if (rawUrl && (rawUrl.indexOf("http://") === 0 || rawUrl.indexOf("https://") === 0)) {{
            window.open(rawUrl, "_blank", "noopener,noreferrer");
        }}
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
            "comment-lines-5",
            "comment-lines-6",
            "comment-lines-full",
            "comment-lines-hide"
        );
        document.body.classList.add("comment-lines-" + linesVal);
        document.querySelectorAll(".comment.expanded").forEach(function(el) {{
            el.classList.remove("expanded");
        }});
        updateCommentAlignments();
    }}
    function toggleSingleAction(el, actType) {{
        if (!el) return;
        const isDone = el.classList.contains("act-done");
        el.classList.toggle("act-done", !isDone);
        el.classList.toggle("act-missing", isDone);
        const iconSpan = el.querySelector(".act-icon");
        if (iconSpan) {{
            iconSpan.textContent = !isDone ? "✅ " : "❌ ";
        }}
        const ticketEl = el.closest(".ticket");
        if (ticketEl && actType) {{
            const attrName = actType === "like" ? "data-liked" : (actType === "comment" ? "data-commented" : "data-shared");
            ticketEl.setAttribute(attrName, !isDone ? "1" : "0");
            applyLiveFilters();
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
        el.classList.toggle("expanded");
        updateCommentAlignments();
    }}

    window.addEventListener("resize", function() {{
        updateCommentAlignments();
    }});

    window.addEventListener("DOMContentLoaded", function() {{
        const c = INITIAL_FILTER_CONFIG || {{}};
        if (typeof c.act_f1_on === "boolean") document.getElementById("actF1On").checked = c.act_f1_on;
        if (c.act_f1_val) document.getElementById("actF1Val").value = c.act_f1_val;
        if (c.act_op1) document.getElementById("actOp1").value = c.act_op1;
        if (typeof c.act_f2_on === "boolean") document.getElementById("actF2On").checked = c.act_f2_on;
        if (c.act_f2_val) document.getElementById("actF2Val").value = c.act_f2_val;
        if (c.act_op2) document.getElementById("actOp2").value = c.act_op2;
        if (typeof c.act_f3_on === "boolean") document.getElementById("actF3On").checked = c.act_f3_on;
        if (c.act_f3_val) document.getElementById("actF3Val").value = c.act_f3_val;
        if (typeof c.act_group_right === "boolean") document.getElementById("actGroupRight").checked = c.act_group_right;

        if (typeof c.kw_f1_on === "boolean") document.getElementById("kwF1On").checked = c.kw_f1_on;
        if (c.kw_f1_text) document.getElementById("kwF1Text").value = c.kw_f1_text;
        if (c.kw_op1) document.getElementById("kwOp1").value = c.kw_op1;
        if (typeof c.kw_f2_on === "boolean") document.getElementById("kwF2On").checked = c.kw_f2_on;
        if (c.kw_f2_text) document.getElementById("kwF2Text").value = c.kw_f2_text;
        if (c.kw_op2) document.getElementById("kwOp2").value = c.kw_op2;
        if (typeof c.kw_f3_on === "boolean") document.getElementById("kwF3On").checked = c.kw_f3_on;
        if (c.kw_f3_text) document.getElementById("kwF3Text").value = c.kw_f3_text;
        if (c.match_mode) document.getElementById("matchModeSelect").value = c.match_mode;
        if (c.min_chars) document.getElementById("minCharsInput").value = String(c.min_chars);
        if (c.min_words) document.getElementById("minWordsInput").value = String(c.min_words);
        if (typeof c.exclude_emoji === "boolean") document.getElementById("excludeEmojiChk").checked = c.exclude_emoji;
        if (typeof c.require_tag === "boolean") document.getElementById("requireTagChk").checked = c.require_tag;
        if (typeof c.include_share_text === "boolean") document.getElementById("includeShareTextChk").checked = c.include_share_text;

        // Apply user's preferred default layout preset on load
        setColumnsPerRow("2");
        setFontScale("xl");
        setCommentAlignMode("center");
        setIdSize("10px");
        applyLiveFilters();
    }});
</script>
</head>
<body class="border-solid id-center actions-all-icons comment-lines-2" data-scope="{default_scope}">
    <!-- Top Print & Layout Toolbar -->
    <div class="toolbar no-print">
        <div style="display:flex;align-items:center;gap:8px;">
            {get_sentra_logo_svg(size=28, bg_fill="#0b1120")}
            <span style="font-weight:800;letter-spacing:1px;font-size:15px;">SENTRA</span>
            <span style="opacity:0.65;">|</span>
            <strong id="toolbarTicketCount">Sentra Lottery Slips ({initial_visible_count} Tickets)</strong>
            <span id="pageEstimateBadge" style="background:#1e293b;color:#38bdf8;border:1px solid #334155;padding:3px 8px;border-radius:5px;font-size:11.5px;font-weight:700;">📄 10 cards/page</span>
            <span style="font-size:11.5px;opacity:0.8;">({generated_at})</span>
        </div>
        <div class="toolbar-controls">
            <label>Show:
                <select id="scopeSelect" onchange="setTicketScope(this.value)">
                    <option value="all" {sel_all}>All Participants ({total_count})</option>
                    <option value="qualified" {sel_qual}>Qualified Winners Only ({qual_count} ✅)</option>
                    <option value="correct">Correct Answer Only (✅)</option>
                    <option value="wrong">Wrong Answer Only (❌)</option>
                    <option value="invalid">Emoji-Only / Invalid (⚠️)</option>
                    <option value="no_comments">No Comments (📝)</option>
                    <option value="disqualified" {sel_disq}>Disqualified / Incomplete ({disq_count} ❌)</option>
                </select>
            </label>
            <label style="color:#38bdf8;">Cards / Row:
                <select id="colsSelect" onchange="setColumnsPerRow(this.value)">
                    <option value="1">1 Card / Row (XL Jumbo Card)</option>
                    <option value="2" selected>2 Cards / Row (Large Card & Big Text)</option>
                    <option value="3">3 Cards / Row (Standard Grid)</option>
                    <option value="4">4 Cards / Row (Compact Grid)</option>
                </select>
            </label>
            <label style="color:#fbbf24;">Cards / Page:
                <select id="cardsPerPageSelect" onchange="setCardsPerPage(this.value)">
                    <option value="0">Auto (Continuous)</option>
                    <option value="2">2 Cards / Page</option>
                    <option value="4">4 Cards / Page</option>
                    <option value="6">6 Cards / Page</option>
                    <option value="8">8 Cards / Page</option>
                    <option value="9">9 Cards / Page</option>
                    <option value="10" selected>10 Cards / Page</option>
                    <option value="12">12 Cards / Page</option>
                    <option value="15">15 Cards / Page</option>
                    <option value="18">18 Cards / Page</option>
                    <option value="24">24 Cards / Page</option>
                </select>
            </label>
            <label style="color:#4ade80;">Font Size:
                <select id="fontScaleSelect" onchange="setFontScale(this.value)">
                    <option value="auto">Auto (Scales with Columns)</option>
                    <option value="md">Medium+ (14.5px Comment)</option>
                    <option value="lg">Large (16.5px Comment)</option>
                    <option value="xl" selected>Extra Large (19px Comment)</option>
                    <option value="jumbo">Jumbo (22px Comment)</option>
                </select>
            </label>
            <label>Comment Lines:
                <select onchange="setCommentLines(this.value)">
                    <option value="1">1 Line (...)</option>
                    <option value="2" selected>2 Lines (Default / 3 when FB Link Hidden)</option>
                    <option value="3">3 Lines (...)</option>
                    <option value="4">4 Lines (...)</option>
                    <option value="5">5 Lines (...)</option>
                    <option value="6">6 Lines (...)</option>
                    <option value="full">Full Comment</option>
                    <option value="hide">Hide Comment</option>
                </select>
            </label>
            <label>Comment Align:
                <select id="commentAlignSelect" onchange="setCommentAlignMode(this.value)">
                    <option value="auto">Auto (Short=Center, Big=Left)</option>
                    <option value="center" selected>Center All Comments</option>
                    <option value="left">Left All Comments</option>
                </select>
            </label>
            <label>Card Design / Cut Line:
                <select onchange="setBorderStyle(this.value)">
                    <option value="cut-solid">✂️ Easy-Cut Grid (Continuous Black Line)</option>
                    <option value="cut-dashed">✂️ Easy-Cut Grid (Dashed Black Line)</option>
                    <option value="solid" selected>Card Box (Solid Black Border)</option>
                    <option value="dashed">Card Box (Dashed Black Border)</option>
                    <option value="none">No Border</option>
                </select>
            </label>
            <label>ID (#0001):
                <select onchange="setIdPosition(this.value)">
                    <option value="center" selected>Row 1: ID + Profile + Name (Center)</option>
                    <option value="after-name">Row 1: Profile + Name + ID (Center)</option>
                    <option value="corner-left">Row 1: ID Left Corner + Profile Center</option>
                    <option value="left">Row 1: Left Align All</option>
                    <option value="hide">Hide ID</option>
                </select>
            </label>
            <label>ID Size:
                <select id="idSizeSelect" onchange="setIdSize(this.value)">
                    <option value="auto">Auto Small (13px)</option>
                    <option value="10px" selected>10px (Micro)</option>
                    <option value="11px">11px (Tiny)</option>
                    <option value="12px">12px (Extra Small)</option>
                    <option value="13px">13px (Compact)</option>
                    <option value="14px">14px (Small)</option>
                    <option value="16px">16px (Medium)</option>
                    <option value="18px">18px (Large)</option>
                    <option value="20px">20px (XL)</option>
                </select>
            </label>
            <label>FB Link:
                <select id="fbLinkSelect" onchange="setFbLinkMode(this.value)">
                    <option value="center" selected>Center FB Link</option>
                    <option value="left">Left FB Link</option>
                    <option value="hide">Hide FB Link (+More Comment Space)</option>
                </select>
            </label>
            <label>Actions:
                <select onchange="setActionStyle(this.value)">
                    <option value="all-icons" selected>✅ / ❌ All 3</option>
                    <option value="done-icons">✅ Completed Only</option>
                    <option value="done-text">Plain Text</option>
                    <option value="hide">Hide Actions</option>
                </select>
            </label>
            <label title="Uncheck to hide bottom FB Link and give extra space to comments"><input type="checkbox" id="showFbLinkChk" checked onchange="toggleFbLinkCheckbox(this.checked)"> FB Link</label>
            <label><input type="checkbox" checked onchange="toggleActionItemVisibility('like', this.checked)"> Reaction</label>
            <label><input type="checkbox" checked onchange="toggleActionItemVisibility('comment', this.checked)"> Comment</label>
            <label><input type="checkbox" checked onchange="toggleActionItemVisibility('share', this.checked)"> Share</label>
            <label><input type="checkbox" onchange="toggleStatusBadge(this.checked)"> Status Badge</label>
            <label><input type="checkbox" onchange="toggleJudgeSheet(this.checked)"> Judge Table</label>
            <button type="button" class="btn-toggle-filter" onclick="toggleFilterPanel()">🎯 Toggle Filter & Answer Picker</button>
            <button type="button" class="btn-print" onclick="window.print()">🖨️ Print Tickets</button>
        </div>
    </div>

    <!-- Embedded Live Advanced Filtering & Correct Answer Picker Panel -->
    <div id="advancedFilterPanel" class="filter-panel no-print">
        <!-- Row 1: 3-Slot Action Rule Chain -->
        <div class="filter-row">
            <span class="filter-row-label">⚡ Action Rule:</span>
            <span class="slot-pill">
                <input type="checkbox" id="actF1On" checked onchange="applyLiveFilters()">
                <select id="actF1Val" onchange="applyLiveFilters()">
                    <option value="none">— None —</option>
                    <option value="like" selected>✅ Reaction</option>
                    <option value="comment">✅ Comment</option>
                    <option value="share">✅ Share</option>
                </select>
            </span>
            <select id="actOp1" class="op-select" onchange="applyLiveFilters()">
                <option value="AND" selected>AND (&amp;)</option>
                <option value="OR">OR (|)</option>
                <option value="NOT">NOT (&amp; !)</option>
                <option value="OR_NOT">OR NOT (| !)</option>
            </select>
            <span class="slot-pill">
                <input type="checkbox" id="actF2On" checked onchange="applyLiveFilters()">
                <select id="actF2Val" onchange="applyLiveFilters()">
                    <option value="none">— None —</option>
                    <option value="like">✅ Reaction</option>
                    <option value="comment" selected>✅ Comment</option>
                    <option value="share">✅ Share</option>
                </select>
            </span>
            <select id="actOp2" class="op-select" onchange="applyLiveFilters()">
                <option value="AND" selected>AND (&amp;)</option>
                <option value="OR">OR (|)</option>
                <option value="NOT">NOT (&amp; !)</option>
                <option value="OR_NOT">OR NOT (| !)</option>
            </select>
            <span class="slot-pill">
                <input type="checkbox" id="actF3On" checked onchange="applyLiveFilters()">
                <select id="actF3Val" onchange="applyLiveFilters()">
                    <option value="none">— None —</option>
                    <option value="like">✅ Reaction</option>
                    <option value="comment">✅ Comment</option>
                    <option value="share" selected>✅ Share</option>
                </select>
            </span>
            <label style="margin-left:4px;color:#94a3b8;"><input type="checkbox" id="actGroupRight" onchange="applyLiveFilters()"> F1 op (F2 op F3)</label>
        </div>

        <!-- Row 2: 3-Slot Keyword & Correct Answer Picker Chain -->
        <div class="filter-row">
            <span class="filter-row-label">🔑 Correct Answer:</span>
            <span class="slot-pill"><input type="checkbox" id="kwF1On" checked onchange="applyLiveFilters()"> K1</span>
            <input type="text" id="kwF1Text" class="kw-input" placeholder="Right Answer Keywords (comma-separated OR, e.g. থাই চিনা বাদাম, 4, চার)" oninput="applyLiveFilters()">
            <select id="kwOp1" class="op-select" onchange="applyLiveFilters()">
                <option value="AND" selected>AND (&amp;)</option>
                <option value="OR">OR (|)</option>
                <option value="NOT">NOT (&amp; !)</option>
                <option value="OR_NOT">OR NOT (| !)</option>
            </select>
            <span class="slot-pill"><input type="checkbox" id="kwF2On" checked onchange="applyLiveFilters()"> K2</span>
            <input type="text" id="kwF2Text" class="kw-input" placeholder="Field 2 Keywords (optional — e.g. #VejalNai, done, ডান)" oninput="applyLiveFilters()">
            <select id="kwOp2" class="op-select" onchange="applyLiveFilters()">
                <option value="AND">AND (&amp;)</option>
                <option value="OR">OR (|)</option>
                <option value="NOT" selected>NOT (&amp; !)</option>
                <option value="OR_NOT">OR NOT (| !)</option>
            </select>
            <span class="slot-pill"><input type="checkbox" id="kwF3On" checked onchange="applyLiveFilters()"> K3</span>
            <input type="text" id="kwF3Text" class="kw-input" placeholder="Field 3 Wrong / Exclude Keywords (optional — e.g. 14, ভুল)" oninput="applyLiveFilters()">
        </div>

        <!-- Row 3: Match Mode, Content Quality & Instant Search -->
        <div class="filter-row">
            <span class="filter-row-label">⚙️ Match &amp; Quality:</span>
            <label>Mode:
                <select id="matchModeSelect" onchange="applyLiveFilters()">
                    <option value="whole_word" selected>Whole Word (Bangla + English Boundary)</option>
                    <option value="contains">Partial (Contains Substring)</option>
                    <option value="exact">Exact Comment Match</option>
                    <option value="regex">Regex Pattern</option>
                </select>
            </label>
            <label>Min Chars: <input type="number" id="minCharsInput" value="0" min="0" max="500" style="width:58px;" oninput="applyLiveFilters()"></label>
            <label>Min Words: <input type="number" id="minWordsInput" value="0" min="0" max="100" style="width:58px;" oninput="applyLiveFilters()"></label>
            <label><input type="checkbox" id="excludeEmojiChk" onchange="applyLiveFilters()"> No Emoji-Only</label>
            <label><input type="checkbox" id="requireTagChk" onchange="applyLiveFilters()"> @Mention/#Hashtag</label>
            <label><input type="checkbox" id="includeShareTextChk" checked onchange="applyLiveFilters()"> Check Shared Captions Too</label>
            <input type="text" id="liveSearchInput" placeholder="🔍 Search #Serial, Name, or Comment text..." style="min-width:220px;flex:1;" oninput="applyLiveFilters()">
            <button type="button" onclick="resetAllFilterRules()" style="background:#334155;color:#f8fafc;border:1px solid #64748b;padding:5px 10px;border-radius:6px;cursor:pointer;font-weight:700;">↺ Reset</button>
        </div>

        <!-- Row 4: Quick Category Filter Pills -->
        <div class="formula-bar">
            <div class="category-pills">
                <button type="button" id="pillAll" data-cat="all" class="cat-pill {'active' if default_scope == 'all' else ''}" onclick="setTicketScope('all')">📋 All: {total_count}</button>
                <button type="button" id="pillQual" data-cat="qualified" class="cat-pill pill-qual {'active' if default_scope == 'qualified' else ''}" onclick="setTicketScope('qualified')">🏆 Qualified Winners: {qual_count}</button>
                <button type="button" id="pillCorrect" data-cat="correct" class="cat-pill pill-qual" onclick="setTicketScope('correct')">✅ Correct Answer: 0</button>
                <button type="button" id="pillWrong" data-cat="wrong" class="cat-pill pill-wrong" onclick="setTicketScope('wrong')">❌ Wrong Answer: 0</button>
                <button type="button" id="pillInvalid" data-cat="invalid" class="cat-pill pill-invalid" onclick="setTicketScope('invalid')">⚠️ Invalid / Emoji: 0</button>
                <button type="button" id="pillNoComm" data-cat="no_comments" class="cat-pill" onclick="setTicketScope('no_comments')">📝 No Comments: 0</button>
                <button type="button" id="pillDisq" data-cat="disqualified" class="cat-pill pill-wrong {'active' if default_scope == 'disqualified' else ''}" onclick="setTicketScope('disqualified')">⛔ Disqualified: {disq_count}</button>
            </div>
            <span style="color:#94a3b8;font-size:11.5px;">💡 Tip: Select <b>2 Cards / Row</b> above for larger cards &amp; bigger comment text!</span>
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
