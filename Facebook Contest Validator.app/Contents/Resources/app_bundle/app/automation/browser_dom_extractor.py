import html
import json
import logging
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs, unquote, quote
from typing import List, Optional, Dict, Any, Tuple
from app.models.share_profile import ShareProfile
from app.utils.text_normalizer import normalize_text

logger = logging.getLogger(__name__)

NON_PROFILE_PATH_PREFIXES = (
    "/hashtag/", "/photo", "/photos/", "/videos/", "/watch", "/reel/", "/reels/",
    "/events/", "/marketplace/", "/gaming/", "/bookmarks", "/notifications",
    "/messages", "/friends", "/settings", "/help", "/policies", "/privacy",
    "/login", "/recover", "/sharer", "/share.php", "/shares/", "/stories/",
    "/ajax/", "/dialog/", "/ads/", "/business/", "/memories", "/saved", "/feeds",
    "/onthisday", "/climatescienceinfo", "/votinginformationcenter", "/fundraisers"
)

IGNORE_UI_LABELS = {
    "like", "reply", "share", "follow", "following", "add friend", "message",
    "most relevant", "all comments", "newest", "author", "top fan", "edited",
    "see more", "view more comments", "view previous comments", "write a comment…",
    "write a comment...", "people who reacted", "people who shared this", "all",
    "close", "back", "facebook", "home", "watch", "marketplace", "groups", "gaming",
    "menu", "notifications", "messenger", "account", "find friends", "see all",
    "cancel", "send", "shared with public", "public", "original audio", "see translation",
    "see original", "hide", "report", "copy link"
}

COMMENT_ARIA_RE = re.compile(
    r"^(?:Comment|Reply)\s+by\s+(.+?)(?:\s+(?:just now|yesterday|about\s+an?\s+.+?\s+ago|a\s+few\s+seconds\s+ago|\d+\s*(?:second|minute|hour|day|week|month|year|s|m|h|d|w|y)s?(?:\s+ago)?))?$",
    re.IGNORECASE,
)

TIME_ONLY_RE = re.compile(
    r"^(\d+\s*(?:s|m|h|d|w|y|sec|min|hr|hrs|day|days|wk|wks|yr|yrs)|just now|yesterday|\d+[KMB]?\s*shares?|\d+[KMB]?)$",
    re.IGNORECASE,
)


def clean_facebook_profile_url(raw_url: str) -> Optional[str]:
    """
    Normalizes a raw Facebook DOM href into a clean, canonical profile URL:
      - https://www.facebook.com/profile.php?id=1000...
      - https://www.facebook.com/<username>
    Returns None if the href is a comment permalink, hashtag, photo, or non-profile link.
    """
    if not raw_url:
        return None

    raw_url = html.unescape(raw_url).strip().replace("\\/", "/")
    if raw_url.startswith("/"):
        raw_url = "https://www.facebook.com" + raw_url

    if "facebook.com" not in raw_url.lower():
        return None

    try:
        parsed = urlparse(raw_url)
    except Exception:
        return None

    path = parsed.path or "/"
    lower_path = path.lower()

    if lower_path in ("/", "/home.php", "/index.php"):
        return None

    if any(lower_path.startswith(prefix) for prefix in NON_PROFILE_PATH_PREFIXES):
        return None

    qs = parse_qs(parsed.query or "")
    has_comment_id = "comment_id" in qs or "reply_comment_id" in qs
    clean_lower_path = lower_path.rstrip("/")

    # Case 1a: /profile.php?id=1000... (Always a user profile, even if Facebook appended &comment_id=...)
    if clean_lower_path == "/profile.php":
        uid_list = qs.get("id", [])
        if uid_list and uid_list[0].isdigit():
            return f"https://www.facebook.com/profile.php?id={uid_list[0]}"
        return None

    # Case 1b: /permalink.php?story_fbid=...&id=1000... or /story.php (Valid on Share cards, but reject comment_id timestamps)
    if clean_lower_path in ("/permalink.php", "/story.php"):
        if has_comment_id:
            return None
        uid_list = qs.get("id", [])
        if uid_list and uid_list[0].isdigit():
            return f"https://www.facebook.com/profile.php?id={uid_list[0]}"
        return None

    if "story_fbid" in qs or "fbid" in qs:
        return None

    # Case 2: /people/<Name>/<id_or_pfbid>
    m_people = re.match(r"^/people/([^/]+)/([^/?#]+)", path, re.IGNORECASE)
    if m_people:
        token = m_people.group(2)
        if token.isdigit():
            return f"https://www.facebook.com/profile.php?id={token}"
        return f"https://www.facebook.com/people/{m_people.group(1)}/{token}"

    # Case 3: /groups/<gid>/user/<uid>
    m_group_user = re.match(r"^/groups/[^/]+/user/([^/?#]+)", path, re.IGNORECASE)
    if m_group_user:
        uid = m_group_user.group(1)
        if uid.isdigit():
            return f"https://www.facebook.com/profile.php?id={uid}"
        return f"https://www.facebook.com/{uid}"

    # Case 4: /<username> or /<username>/posts/... (sharer card links)
    segments = [seg for seg in path.split("/") if seg]
    if not segments:
        return None

    if len(segments) >= 2:
        if segments[1].lower() in ("posts", "videos", "photos", "about"):
            if has_comment_id:
                return None
            segments = [segments[0]]
        else:
            return None

    username = unquote(segments[0]).strip()
    if username.lower() in (
        "groups", "pages", "watch", "marketplace", "friends", "memories",
        "saved", "feeds", "events", "gaming", "notifications", "messages",
        "bookmarks", "post", "posts", "photo", "photos", "video", "videos",
        "reel", "reels", "story", "stories", "share", "shares", "sharer"
    ):
        return None

    if username.endswith(".php"):
        return None

    return f"https://www.facebook.com/{username}"


def _is_valid_person_name(name: str) -> bool:
    if not name:
        return False
    cleaned = normalize_text(name)
    if len(cleaned) < 2 or len(cleaned) > 70:
        return False
    low = cleaned.lower()
    if low in IGNORE_UI_LABELS or "online status indicator" in low:
        return False
    if TIME_ONLY_RE.match(low):
        return False
    if low.startswith(("view more", "view previous", "reply to ", "like ", "shared with", "people who", "profile photo of", "profile picture of")):
        return False
    if sum(1 for ch in cleaned if ch.isalpha()) < 2:
        return False
    return True


class _FacebookDOMTreeParser(HTMLParser):
    """
    Single-pass Python HTML parser that extracts:
      1. Links (`<a>`) inside `<div role="dialog">` vs outside dialogs
      2. Comment articles (`<div role="article">`) with `aria-label="Comment by ..."`
         plus nested `<a href="...">`, `dir="auto"` text blocks, and `<img alt="...">`.
    """

    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tag_stack: List[str] = []
        self.dialog_depths: List[int] = []
        self.article_stack: List[Dict[str, Any]] = []
        self.current_link: Optional[Dict[str, Any]] = None
        self.dir_auto_depths: List[Dict[str, Any]] = []

        self.dialog_links: List[Dict[str, Any]] = []
        self.page_links: List[Dict[str, Any]] = []
        self.articles: List[Dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag_low = tag.lower()
        if tag_low not in self.VOID_TAGS:
            self.tag_stack.append(tag_low)
        depth = len(self.tag_stack)
        attr_dict = {k.lower(): (v or "") for k, v in attrs if k}

        role = attr_dict.get("role", "").lower()
        aria_label = attr_dict.get("aria-label", "").strip()
        dir_val = attr_dict.get("dir", "").lower()

        if role == "dialog":
            self.dialog_depths.append(depth)

        if role == "article":
            self.article_stack.append({
                "depth": depth,
                "in_dialog": bool(self.dialog_depths),
                "aria_label": aria_label,
                "links": [],
                "texts": [],
                "emojis": [],
            })

        if tag_low == "a" and "href" in attr_dict:
            self.current_link = {
                "depth": depth,
                "href": attr_dict.get("href", ""),
                "aria_label": aria_label,
                "title": attr_dict.get("title", "").strip(),
                "text_parts": [],
                "in_dialog": bool(self.dialog_depths),
            }

        if dir_val == "auto" and self.article_stack:
            self.dir_auto_depths.append({
                "depth": depth,
                "parts": [],
            })

        # Capture <img alt="..."> or <svg aria-label="..."> inside links or comment articles
        if tag_low in ("img", "svg"):
            alt_text = (attr_dict.get("alt") or aria_label or "").strip()
            if alt_text:
                if self.current_link is not None and not self.current_link["aria_label"]:
                    self.current_link["aria_label"] = alt_text
                if self.article_stack and len(alt_text) <= 16 and "profile" not in alt_text.lower():
                    self.article_stack[-1]["emojis"].append(alt_text)

    def handle_data(self, data: str):
        if not data:
            return
        if self.current_link is not None:
            self.current_link["text_parts"].append(data)
        if self.dir_auto_depths:
            self.dir_auto_depths[-1]["parts"].append(data)

    def handle_endtag(self, tag: str):
        tag_low = tag.lower()
        if tag_low in self.VOID_TAGS:
            return
        depth = len(self.tag_stack)

        if self.current_link is not None and depth == self.current_link["depth"] and tag_low == "a":
            link_obj = self.current_link
            self.current_link = None
            text = normalize_text("".join(link_obj["text_parts"]))
            rec = {
                "href": link_obj["href"],
                "text": text,
                "aria_label": normalize_text(link_obj["aria_label"]),
                "title": normalize_text(link_obj["title"]),
                "in_dialog": link_obj["in_dialog"],
            }
            if link_obj["in_dialog"]:
                self.dialog_links.append(rec)
            else:
                self.page_links.append(rec)
            if self.article_stack:
                self.article_stack[-1]["links"].append(rec)

        if self.dir_auto_depths and depth == self.dir_auto_depths[-1]["depth"]:
            block = self.dir_auto_depths.pop()
            txt = normalize_text("".join(block["parts"]))
            if txt and self.article_stack:
                self.article_stack[-1]["texts"].append(txt)

        if self.article_stack and depth == self.article_stack[-1]["depth"] and tag_low == "div":
            art = self.article_stack.pop()
            self.articles.append(art)

        if self.dialog_depths and depth == self.dialog_depths[-1]:
            self.dialog_depths.pop()

        if self.tag_stack:
            self.tag_stack.pop()


class BackgroundHTMLExtractor:
    """
    Extracts Likes, Comments, and Shares (with canonical Profile URLs) directly
    from Facebook's rendered background HTML (`page().toHtml()`), bypassing JS CSP.
    """

    RELAY_NAME_URL_RE = re.compile(
        r'\{[^{}]{0,350}?"name"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"[^{}]{0,350}?"(?:url|uri|profile_url)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
        re.IGNORECASE,
    )
    RELAY_URL_NAME_RE = re.compile(
        r'\{[^{}]{0,350}?"(?:url|uri|profile_url)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"[^{}]{0,350}?"name"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
        re.IGNORECASE,
    )

    @classmethod
    def extract_from_html(
        cls,
        raw_html: str,
        session_id: str,
        action_type: str = "share",
        scroll_index: int = 0,
    ) -> List[ShareProfile]:
        if not raw_html:
            return []

        parser = _FacebookDOMTreeParser()
        try:
            parser.feed(raw_html)
        except Exception as e:
            logger.debug(f"HTMLParser warning: {e}")

        raw_items: List[Dict[str, str]] = []

        if action_type == "comment":
            raw_items.extend(cls._extract_comments_from_tree(parser))
        else:
            raw_items.extend(cls._extract_links_from_tree(parser))

        # Layer 2 Fallback: If tree links are empty, check embedded Relay JSON user blocks
        if not raw_items:
            raw_items.extend(cls._extract_from_embedded_json(raw_html))

        return BrowserDOMExtractor.parse_dom_items(
            raw_items=raw_items,
            session_id=session_id,
            action_type=action_type,
            scroll_index=scroll_index,
        )

    @classmethod
    def _extract_links_from_tree(cls, parser: _FacebookDOMTreeParser) -> List[Dict[str, str]]:
        """
        Extracts user profile links for Likes / Shares.
        Prioritizes links inside an open `<div role="dialog">` popup if it has profile links.
        Also merges avatar `<a href="..." aria-label="Name">` with adjacent `<a href="...">Name</a>`.
        """
        dialog_candidates = cls._resolve_links(parser.dialog_links)
        if dialog_candidates:
            return dialog_candidates
        return cls._resolve_links(parser.page_links)

    @classmethod
    def _resolve_links(cls, links: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        url_to_name: Dict[str, str] = {}
        ordered_urls: List[str] = []

        for lnk in links:
            clean_url = clean_facebook_profile_url(lnk.get("href", ""))
            if not clean_url:
                continue

            # Candidate name can come from link innerText, aria-label, or title
            candidates = [
                lnk.get("text", ""),
                lnk.get("aria_label", ""),
                lnk.get("title", ""),
            ]
            chosen_name = ""
            for cand in candidates:
                if not cand:
                    continue
                # Strip "'s profile picture" or "Profile picture of ..."
                cand_clean = re.sub(
                    r"(?:'s\s+profile\s+picture|\s+profile\s+picture.*|^profile\s+picture\s+of\s+)",
                    "",
                    cand,
                    flags=re.IGNORECASE,
                ).strip()
                if _is_valid_person_name(cand_clean):
                    chosen_name = cand_clean
                    break

            if clean_url not in url_to_name:
                ordered_urls.append(clean_url)
                url_to_name[clean_url] = chosen_name
            elif not url_to_name[clean_url] and chosen_name:
                url_to_name[clean_url] = chosen_name

        for url in ordered_urls:
            name = url_to_name.get(url, "")
            if name:
                results.append({"name": name, "url": url, "content": ""})
        return results

    @classmethod
    def _extract_comments_from_tree(cls, parser: _FacebookDOMTreeParser) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for art in parser.articles:
            aria = art.get("aria_label", "")
            author_name = ""
            m_aria = COMMENT_ARIA_RE.match(aria)
            if m_aria:
                cand_author = normalize_text(m_aria.group(1))
                if _is_valid_person_name(cand_author):
                    author_name = cand_author

            author_url = ""
            for lnk in art.get("links", []):
                clean_url = clean_facebook_profile_url(lnk.get("href", ""))
                if not clean_url:
                    continue
                if not author_url:
                    author_url = clean_url
                if not author_name:
                    for cand in (lnk.get("text", ""), lnk.get("aria_label", "")):
                        cand_clean = re.sub(r"\s+profile\s+picture.*$", "", cand, flags=re.IGNORECASE).strip()
                        if _is_valid_person_name(cand_clean):
                            author_name = cand_clean
                            break
                if author_name and author_url:
                    break

            if not author_name or not author_url:
                continue

            # Build comment body from dir="auto" blocks inside this article
            body_parts: List[str] = []
            for txt in art.get("texts", []):
                if txt.lower() == author_name.lower():
                    continue
                if txt.lower() in IGNORE_UI_LABELS or TIME_ONLY_RE.match(txt.lower()):
                    continue
                if txt not in body_parts:
                    body_parts.append(txt)

            if not body_parts and art.get("emojis"):
                body_parts.append("".join(art["emojis"]))

            results.append({
                "name": author_name,
                "url": author_url,
                "content": " ".join(body_parts).strip(),
            })

        # If a post layout doesn't use role="article" on comments, fall back to dialog links
        if not results and parser.dialog_links:
            return cls._resolve_links(parser.dialog_links)

        return results

    @classmethod
    def _extract_from_embedded_json(cls, raw_html: str) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for m in cls.RELAY_NAME_URL_RE.finditer(raw_html):
            try:
                raw_name = m.group(1).encode("utf-8").decode("unicode_escape")
            except Exception:
                raw_name = m.group(1)
            raw_url = m.group(2).replace("\\/", "/")
            clean_url = clean_facebook_profile_url(raw_url)
            if clean_url and _is_valid_person_name(raw_name):
                results.append({"name": raw_name, "url": clean_url, "content": ""})

        for m in cls.RELAY_URL_NAME_RE.finditer(raw_html):
            raw_url = m.group(1).replace("\\/", "/")
            try:
                raw_name = m.group(2).encode("utf-8").decode("unicode_escape")
            except Exception:
                raw_name = m.group(2)
            clean_url = clean_facebook_profile_url(raw_url)
            if clean_url and _is_valid_person_name(raw_name):
                results.append({"name": raw_name, "url": clean_url, "content": ""})

        return results


# Lightweight scroll & comment-expand helper run in ApplicationWorld (CSP-safe)
JS_SCROLL_AND_EXPAND = r"""
(function(actionType, autoExpand) {
    let scrolled = false;
    if (actionType === 'comment' && autoExpand) {
        const btns = document.querySelectorAll('div[role="button"], span[role="button"]');
        for (const b of btns) {
            const t = (b.innerText || '').trim().toLowerCase();
            if (t.startsWith('view more comments') || t.startsWith('view previous comments') || /^\d+\s+replies/.test(t)) {
                try { b.click(); scrolled = true; } catch (e) {}
            }
        }
    }

    // Find all scrollable containers in dialogs or page
    const candidates = [];
    const dialogs = document.querySelectorAll('div[role="dialog"]');
    const roots = dialogs.length > 0 ? Array.from(dialogs) : [document.body];
    for (const root of roots) {
        if (!root) continue;
        const divs = root.querySelectorAll('div');
        for (const d of divs) {
            if (d.scrollHeight > d.clientHeight + 15 && d.clientHeight > 100) {
                const st = window.getComputedStyle(d);
                if (st.overflowY === 'auto' || st.overflowY === 'scroll' || st.overflowY === ' overlay') {
                    candidates.push(d);
                }
            }
        }
    }

    if (candidates.length > 0) {
        candidates.sort((a, b) => (b.clientHeight * b.clientWidth) - (a.clientHeight * a.clientWidth));
        for (const target of candidates.slice(0, 2)) {
            const before = target.scrollTop;
            target.scrollTop += Math.max(480, Math.floor(target.clientHeight * 0.8));
            if (target.scrollTop !== before) {
                scrolled = true;
            }
        }
    }

    if (!scrolled) {
        const beforeY = window.scrollY;
        window.scrollBy(0, 650);
        if (window.scrollY !== beforeY) {
            scrolled = true;
        }
    }
    return scrolled;
})
"""

# Keep JS_EXTRACT_AND_SCROLL alias for backward compatibility
JS_EXTRACT_AND_SCROLL = JS_SCROLL_AND_EXPAND


CLIPBOARD_BATCH_PREFIX = "FB_CONTEST_BATCH_V1:"


class BrowserDOMExtractor:
    """
    Converts raw `{name, url, content}` records extracted from Facebook Web DOM / HTML
    or the Chrome Extension Clipboard Bridge into normalized `ShareProfile` objects
    with 100% canonical `profile_url`s.
    """

    @staticmethod
    def parse_dom_items(
        raw_items: List[Dict[str, Any]],
        session_id: str,
        action_type: str = "share",
        scroll_index: int = 0
    ) -> List[ShareProfile]:
        profiles: List[ShareProfile] = []
        seen_keys = set()

        for item in raw_items or []:
            raw_name = normalize_text(item.get("name") or "")
            raw_name = re.sub(
                r"\s*[·•]\s*(?:\d+\s*(?:s|m|h|d|w|y|sec|min|hr|hrs|day|days|wk|wks|yr|yrs)\b|just now|yesterday|follow|following|1st|2nd|3rd|author|top fan|admin|moderator|rising contributor|top contributor|edited).*$",
                "",
                raw_name,
                flags=re.IGNORECASE,
            ).strip()
            raw_name = re.sub(
                r"\s+(?:Liked|Loved|Cared|Haha|Wow|Sad|Angry)$",
                "",
                raw_name,
                flags=re.IGNORECASE,
            ).strip()
            raw_url = item.get("url") or ""
            avatar_url = (item.get("avatar_url") or "").strip()
            content = normalize_text(item.get("content") or "")
            item_action = (item.get("action_type") or action_type or "share").lower().strip()
            if item_action not in ("like", "comment", "share"):
                item_action = "share"

            clean_url = clean_facebook_profile_url(raw_url)
            if not raw_name:
                continue
            # For comments (or items with avatar_url/content), allow keeping the record even if Facebook didn't hydrate an href
            if not clean_url and item_action != "comment" and not avatar_url:
                continue

            if not _is_valid_person_name(raw_name):
                continue

            identity_key = (clean_url or raw_name).lower()
            key = (identity_key, item_action, content if item_action == "comment" else "")
            if key in seen_keys:
                continue
            seen_keys.add(key)

            profiles.append(
                ShareProfile(
                    name=raw_name,
                    profile_url=clean_url,
                    share_url=avatar_url if avatar_url.startswith("http") else None,
                    content=content,
                    action_type=item_action,
                    confidence=1.0 if clean_url else 0.9,
                    source="facebook_browser_extension",
                    session_id=session_id,
                    scroll_index=scroll_index,
                )
            )

        return profiles

    @classmethod
    def parse_clipboard_batch(
        cls,
        clipboard_text: str,
        session_id: str
    ) -> Optional[Tuple[str, List[ShareProfile]]]:
        """
        Parses a `FB_CONTEST_BATCH_V1:{...}` JSON batch placed on the system clipboard
        by the installable browser extension.
        Returns `(batch_id, List[ShareProfile])` or `None` if clipboard does not contain a batch.
        """
        if not clipboard_text:
            return None

        stripped = clipboard_text.strip()
        if not stripped.startswith(CLIPBOARD_BATCH_PREFIX):
            return None

        json_part = stripped[len(CLIPBOARD_BATCH_PREFIX):].strip()
        try:
            payload = json.loads(json_part)
        except Exception as e:
            logger.warning(f"Failed to parse extension clipboard JSON batch: {e}")
            return None

        if not isinstance(payload, dict):
            return None

        batch_id = str(payload.get("batch_id") or "")
        default_action = str(payload.get("action_type") or "share").lower()
        raw_items = payload.get("items") or []

        profiles = cls.parse_dom_items(
            raw_items=raw_items,
            session_id=session_id,
            action_type=default_action,
            scroll_index=0,
        )
        return batch_id, profiles

    @classmethod
    def generate_bookmarklet_page(cls) -> str:
        """
        Compiles `browser_extension/content.js` into a single-click `javascript:...`
        Bookmarklet and writes an interactive `browser_extension/bookmarklet.html`
        page that the user can drag onto their browser's Bookmarks Bar.
        """
        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "browser_extension")
        )
        os.makedirs(base_dir, exist_ok=True)
        content_js_path = os.path.join(base_dir, "content.js")
        out_html_path = os.path.join(base_dir, "bookmarklet.html")

        with open(content_js_path, "r", encoding="utf-8") as f:
            js_lines = f.readlines()

        # Strip full-line // comments so single-line bookmarklet conversion is safe
        cleaned_lines = []
        for ln in js_lines:
            s = ln.strip()
            if s.startswith("//"):
                continue
            cleaned_lines.append(ln)

        js_code = "".join(cleaned_lines).strip()
        bookmarklet_href = "javascript:" + quote(js_code, safe="();,/:@&=+$#-_.!~*'()")

        page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>FB Contest Scraper — 1-Click Bookmarklet & Extension Setup</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a;
      color: #f8fafc;
      max-width: 780px;
      margin: 40px auto;
      padding: 24px;
      line-height: 1.6;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 14px;
      padding: 24px 28px;
      margin-bottom: 24px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.35);
    }}
    h1 {{ color: #60a5fa; margin-top: 0; }}
    h2 {{ color: #93c5fd; margin-top: 0; font-size: 18px; }}
    .bookmarklet-btn {{
      display: inline-block;
      background: linear-gradient(135deg, #2563eb, #7c3aed);
      color: #ffffff;
      font-weight: 800;
      font-size: 17px;
      text-decoration: none;
      padding: 14px 28px;
      border-radius: 999px;
      border: 2px dashed #93c5fd;
      box-shadow: 0 8px 20px rgba(37, 99, 235, 0.45);
      cursor: grab;
      margin: 12px 0;
    }}
    .copy-btn {{
      background: #0284c7;
      color: white;
      border: none;
      border-radius: 8px;
      padding: 10px 18px;
      font-weight: 700;
      cursor: pointer;
      margin-left: 12px;
    }}
    code {{
      background: #0f172a;
      padding: 2px 6px;
      border-radius: 4px;
      color: #38bdf8;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>🔖 Option A: 1-Click Browser Bookmark (Zero Installation)</h1>
    <p>Works in <strong>Chrome, Safari, Edge, Brave, and Firefox</strong> without installing anything:</p>
    <ol>
      <li>Make sure your browser's <strong>Bookmarks Bar</strong> is visible (<code>Cmd+Shift+B</code> on Mac or <code>Ctrl+Shift+B</code> on Windows).</li>
      <li><strong>Drag the glowing button below</strong> up onto your Bookmarks Bar:</li>
    </ol>
    <p style="text-align:center;">
      <a class="bookmarklet-btn" href="{bookmarklet_href}" title="Drag me to your Bookmarks Bar!">🎯 FB Contest Scraper</a>
      <button class="copy-btn" onclick="navigator.clipboard.writeText(document.querySelector('.bookmarklet-btn').href);this.textContent='✅ Bookmarklet URL Copied!';">📋 Copy Bookmark URL</button>
    </p>
    <ol start="3">
      <li>Open your Facebook contest post in your browser and <strong>click the <code>🎯 FB Contest Scraper</code> bookmark</strong> on your Bookmarks Bar — the floating scraper panel will appear immediately!</li>
      <li>Click <strong>Step 1 (Likes)</strong>, <strong>Step 2 (Comments)</strong>, and <strong>Step 3 (Shares)</strong> — every batch is automatically sent to your Desktop App via the clipboard!</li>
    </ol>
  </div>

  <div class="card">
    <h2>🧩 Option B: Installable Chrome / Edge Extension (Auto-Loads on Facebook)</h2>
    <ol>
      <li>Open <code>chrome://extensions/</code> in Chrome (or <code>edge://extensions/</code> in Edge).</li>
      <li>Turn on <strong>Developer mode</strong> (top-right) and click <strong>Load unpacked</strong>.</li>
      <li>Select the folder:<br/><code>{base_dir}</code></li>
    </ol>
  </div>
</body>
</html>
"""
        with open(out_html_path, "w", encoding="utf-8") as f:
            f.write(page_html)
        return out_html_path
