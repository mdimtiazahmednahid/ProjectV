import html
import json
import logging
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs, unquote, quote
from typing import List, Optional, Dict, Any, Tuple
from app.models.share_profile import ShareProfile, normalize_reaction_type
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

    # Case 3b: /p/<Name-or-Slug>-<uid> or /p/<slug> (Facebook professional / numeric-slug profiles)
    m_p_profile = re.match(r"^/p/([^/?#]+)", path, re.IGNORECASE)
    if m_p_profile:
        slug = unquote(m_p_profile.group(1)).strip()
        if slug.isdigit() and len(slug) >= 5:
            return f"https://www.facebook.com/profile.php?id={slug}"
        m_tail_uid = re.search(r"-(\d{8,})$", slug)
        if m_tail_uid:
            return f"https://www.facebook.com/profile.php?id={m_tail_uid.group(1)}"
        return f"https://www.facebook.com/p/{slug}"

    # Case 3c: /profile/<uid_or_username> or /user/<uid_or_username>
    m_direct_prof = re.match(r"^/(?:profile|user)/([^/?#]+)", path, re.IGNORECASE)
    if m_direct_prof:
        tok = unquote(m_direct_prof.group(1)).strip()
        if tok.isdigit() and len(tok) >= 5:
            return f"https://www.facebook.com/profile.php?id={tok}"
        return f"https://www.facebook.com/{tok}"

    # Case 3d: /pages/<Name>/<uid> or /pages/category/<cat>/<Name>/<uid>
    m_pages = re.match(r"^/pages/(?:category/[^/]+/)?([^/]+)/(\d{5,})", path, re.IGNORECASE)
    if m_pages:
        return f"https://www.facebook.com/profile.php?id={m_pages.group(2)}"

    # Case 4: /<username> or /<username>/posts/... (sharer card links)
    segments = [seg for seg in path.split("/") if seg]
    if not segments:
        return None

    if len(segments) >= 2:
        if segments[1].lower() in (
            "posts", "videos", "photos", "about", "reels",
            "friends", "followers", "following", "map", "mentions"
        ):
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

    if username.isdigit() and len(username) >= 5:
        return f"https://www.facebook.com/profile.php?id={username}"

    return f"https://www.facebook.com/{username}"


def clean_facebook_post_url(raw_url: str) -> Optional[str]:
    """
    Normalizes a raw Facebook post / share permalink into a clean canonical post URL.
    Supports:
      - https://www.facebook.com/<username>/posts/<post_id_or_pfbid>
      - https://www.facebook.com/permalink.php?story_fbid=...&id=...
      - https://www.facebook.com/story.php?story_fbid=...&id=...
      - https://www.facebook.com/groups/<gid>/posts/<post_id>
      - https://www.facebook.com/share/p/<token>
      - https://www.facebook.com/<username>/videos/<video_id>
      - https://www.facebook.com/photo.php?fbid=...
      - https://www.facebook.com/watch/?v=...
    Returns None if raw_url is a plain profile URL or comment link.
    """
    if not raw_url:
        return None

    url = raw_url.strip()
    if url.startswith("#") or url.startswith("javascript:"):
        return None
    if url.startswith("/"):
        url = "https://www.facebook.com" + url
    if "facebook.com" not in url.lower():
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    qs = parse_qs(parsed.query)
    if "comment_id" in qs or "reply_comment_id" in qs:
        return None

    path = parsed.path or "/"
    clean_lower_path = path.lower().rstrip("/")

    # 1. /permalink.php?story_fbid=...&id=... or /story.php?story_fbid=...&id=...
    if clean_lower_path in ("/permalink.php", "/story.php"):
        story_fbids = qs.get("story_fbid", [])
        uids = qs.get("id", [])
        if story_fbids and uids:
            return f"https://www.facebook.com/permalink.php?story_fbid={quote(story_fbids[0])}&id={quote(uids[0])}"
        if story_fbids:
            return f"https://www.facebook.com/permalink.php?story_fbid={quote(story_fbids[0])}"
        return None

    # 2. /<username>/(posts|videos|activity)/<post_id_or_pfbid>
    m_user_post = re.match(r"^/([^/]+)/(posts|videos|activity)/([^/?#]+)", path, re.IGNORECASE)
    if m_user_post:
        return f"https://www.facebook.com/{m_user_post.group(1)}/{m_user_post.group(2)}/{m_user_post.group(3)}"

    # 3. /groups/<gid>/(posts|permalink)/<post_id>
    m_group_post = re.match(r"^/groups/([^/]+)/(posts|permalink)/([^/?#]+)", path, re.IGNORECASE)
    if m_group_post:
        return f"https://www.facebook.com/groups/{m_group_post.group(1)}/{m_group_post.group(2)}/{m_group_post.group(3)}"

    # 4. /share/p/<token> or /share/v/<token> or /share/<token>
    m_share = re.match(r"^/share/(?:([pv])/)?([^/?#]+)", path, re.IGNORECASE)
    if m_share:
        kind_seg = f"{m_share.group(1)}/" if m_share.group(1) else ""
        return f"https://www.facebook.com/share/{kind_seg}{m_share.group(2)}"

    # 5. /photo.php?fbid=... or /photo/?fbid=...
    if clean_lower_path in ("/photo.php", "/photo"):
        fbids = qs.get("fbid", [])
        if fbids:
            return f"https://www.facebook.com/photo.php?fbid={quote(fbids[0])}"

    # 6. /watch/?v=...
    if clean_lower_path == "/watch":
        vs = qs.get("v", [])
        if vs:
            return f"https://www.facebook.com/watch/?v={quote(vs[0])}"

    return None


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
    letter_or_indic_count = sum(1 for ch in cleaned if ch.isalpha() or ("\u0980" <= ch <= "\u09FF"))
    if letter_or_indic_count < 2:
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
        self._article_seq: int = 0
        self._last_link_rec: Optional[Dict[str, Any]] = None

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
            self._article_seq += 1
            self.article_stack.append({
                "seq": self._article_seq,
                "depth": depth,
                "in_dialog": bool(self.dialog_depths),
                "aria_label": aria_label,
                "links": [],
                "texts": [],
                "emojis": [],
            })

        if tag_low == "a" and "href" in attr_dict:
            in_body_dir = any(d.get("tag") == "div" for d in self.dir_auto_depths)
            self.current_link = {
                "depth": depth,
                "href": attr_dict.get("href", ""),
                "aria_label": aria_label,
                "title": attr_dict.get("title", "").strip(),
                "reaction_type": normalize_reaction_type(aria_label),
                "text_parts": [],
                "in_dialog": bool(self.dialog_depths),
                "in_body_dir_auto": in_body_dir,
            }

        if dir_val == "auto":
            self.dir_auto_depths.append({
                "depth": depth,
                "tag": tag_low,
                "parts": [],
            })

        # Capture <img alt="..."> or <svg aria-label="..."> inside links or comment articles
        if tag_low in ("img", "svg"):
            alt_text = (attr_dict.get("alt") or aria_label or "").strip()
            if alt_text:
                react_norm = normalize_reaction_type(alt_text)
                if self.current_link is not None:
                    if react_norm and not self.current_link.get("reaction_type"):
                        self.current_link["reaction_type"] = react_norm
                    elif not react_norm and not self.current_link["aria_label"]:
                        self.current_link["aria_label"] = alt_text
                if self.article_stack and len(alt_text) <= 16 and "profile" not in alt_text.lower() and not react_norm:
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
                "reaction_type": link_obj.get("reaction_type") or "",
                "in_dialog": link_obj["in_dialog"],
                "in_body_dir_auto": bool(link_obj.get("in_body_dir_auto")),
                "following_texts": [],
            }
            if link_obj["in_dialog"]:
                self.dialog_links.append(rec)
            else:
                self.page_links.append(rec)
            if self.article_stack:
                self.article_stack[-1]["links"].append(rec)
            if not rec["in_body_dir_auto"] and clean_facebook_profile_url(rec["href"]):
                self._last_link_rec = rec

        if self.dir_auto_depths and depth == self.dir_auto_depths[-1]["depth"]:
            block = self.dir_auto_depths.pop()
            txt = normalize_text("".join(block["parts"]))
            if self.dir_auto_depths and block["parts"]:
                # Propagate text to outer dir="auto" container if nested (e.g. <div dir="auto">Hello <span>World</span></div>)
                self.dir_auto_depths[-1]["parts"].append(" " + " ".join(block["parts"]) + " ")
            if txt:
                if self.article_stack:
                    self.article_stack[-1]["texts"].append(txt)
                if self._last_link_rec is not None:
                    self._last_link_rec["following_texts"].append(txt)

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
        url_to_reaction: Dict[str, str] = {}
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
            react_hint = lnk.get("reaction_type") or ""
            for cand in candidates:
                if not cand:
                    continue
                if not react_hint:
                    m_rsuf = re.search(
                        r"(?:\s*[,·•]\s*|\s+)(Liked|Loved|Cared|Haha|Wow|Sad|Angry)\.?$",
                        cand,
                        flags=re.IGNORECASE,
                    )
                    if m_rsuf:
                        react_hint = normalize_reaction_type(m_rsuf.group(1))
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
                url_to_reaction[clean_url] = react_hint
            else:
                if not url_to_name[clean_url] and chosen_name:
                    url_to_name[clean_url] = chosen_name
                if not url_to_reaction.get(clean_url) and react_hint:
                    url_to_reaction[clean_url] = react_hint

        for url in ordered_urls:
            name = url_to_name.get(url, "")
            if name:
                r_type = url_to_reaction.get(url, "")
                results.append({
                    "name": name,
                    "url": url,
                    "content": r_type,
                    "reaction_type": r_type,
                })
        return results

    @classmethod
    def _extract_comments_from_tree(cls, parser: _FacebookDOMTreeParser) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        sorted_articles = sorted(parser.articles, key=lambda a: a.get("seq", 0))
        for art in sorted_articles:
            aria = art.get("aria_label", "")
            author_name = ""
            m_aria = COMMENT_ARIA_RE.match(aria)
            if m_aria:
                cand_author = normalize_text(m_aria.group(1))
                if _is_valid_person_name(cand_author):
                    author_name = cand_author

            author_url = ""
            for lnk in art.get("links", []):
                if lnk.get("in_body_dir_auto"):
                    continue
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

            # If author's link was an avatar-only link (or unlinked) and the name is in the first header text block
            if not author_name:
                for txt in art.get("texts", []):
                    cand_clean = re.sub(
                        r"\s*[·•]\s*(?:\d+\s*(?:s|m|h|d|w|y|sec|min|hr|hrs|day|days|wk|wks|yr|yrs)\b|just now|yesterday|follow|following).*$",
                        "",
                        txt,
                        flags=re.IGNORECASE,
                    ).strip()
                    if _is_valid_person_name(cand_clean):
                        author_name = cand_clean
                        break

            if not author_name:
                continue

            # Build comment body from dir="auto" blocks inside this article
            body_parts: List[str] = []
            for txt in art.get("texts", []):
                if txt.lower() == author_name.lower():
                    continue
                if txt.lower() in IGNORE_UI_LABELS or TIME_ONLY_RE.match(txt.lower()):
                    continue
                # Skip if a child span text is already contained inside a fuller parent div[dir="auto"] text
                if any(txt in existing for existing in body_parts):
                    continue
                body_parts = [existing for existing in body_parts if existing not in txt]
                if txt not in body_parts:
                    body_parts.append(txt)

            if not body_parts and art.get("emojis"):
                body_parts.append("".join(art["emojis"]))

            results.append({
                "name": author_name,
                "url": author_url,
                "content": " ".join(body_parts).strip(),
            })

        # If a post layout doesn't use role="article" on comments, fall back to dialog/page links + their following dir="auto" texts
        if not results:
            source_links = parser.dialog_links if parser.dialog_links else parser.page_links
            if source_links:
                resolved = cls._resolve_links(source_links)
                url_to_texts: Dict[str, List[str]] = {}
                for lnk in source_links:
                    if lnk.get("in_body_dir_auto"):
                        continue
                    c_url = clean_facebook_profile_url(lnk.get("href", ""))
                    if not c_url:
                        continue
                    bucket = url_to_texts.setdefault(c_url, [])
                    for ft in lnk.get("following_texts", []):
                        if ft.lower() in IGNORE_UI_LABELS or TIME_ONLY_RE.match(ft.lower()):
                            continue
                        if ft not in bucket:
                            bucket.append(ft)
                for item in resolved:
                    u = item.get("url", "")
                    nm_low = (item.get("name") or "").lower()
                    txts = [
                        t for t in url_to_texts.get(u, [])
                        if t.lower() != nm_low
                    ]
                    if txts:
                        item["content"] = " ".join(txts).strip()
                return resolved

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

            # Capture trailing reaction suffix on name (e.g. "Md Rahim Liked" or "Md Rahim, Loved") before stripping it
            name_reaction_hint = ""
            m_react_suffix = re.search(
                r"(?:\s*[,·•]\s*|\s+)(Liked|Loved|Cared|Haha|Wow|Sad|Angry)\.?$",
                raw_name,
                flags=re.IGNORECASE,
            )
            if m_react_suffix:
                name_reaction_hint = normalize_reaction_type(m_react_suffix.group(1))
                raw_name = raw_name[: m_react_suffix.start()].strip()

            raw_url = item.get("url") or ""
            raw_shared_post_url = item.get("shared_post_url") or ""
            avatar_url = (item.get("avatar_url") or "").strip()
            content = normalize_text(item.get("content") or "")
            item_action = (item.get("action_type") or action_type or "share").lower().strip()
            if item_action not in ("like", "comment", "share"):
                item_action = "share"

            reaction_type = (
                normalize_reaction_type(item.get("reaction_type"))
                or normalize_reaction_type(item.get("reactions"))
                or (normalize_reaction_type(content) if item_action == "like" else "")
                or name_reaction_hint
            )
            if item_action == "like" and reaction_type and not content:
                content = reaction_type

            clean_url = clean_facebook_profile_url(raw_url)
            clean_post_url = (
                clean_facebook_post_url(raw_shared_post_url)
                or (clean_facebook_post_url(raw_url) if item_action == "share" else None)
            )
            if not raw_name:
                continue

            if not _is_valid_person_name(raw_name):
                continue

            identity_key = (clean_url or raw_name).lower()
            key = (
                identity_key,
                item_action,
                content if item_action in ("comment", "share") else "",
                clean_post_url or "" if item_action == "share" else "",
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)

            profiles.append(
                ShareProfile(
                    name=raw_name,
                    profile_url=clean_url,
                    share_url=avatar_url if avatar_url.startswith("http") else None,
                    shared_post_url=clean_post_url,
                    content=content,
                    reactions=reaction_type or None,
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
    def parse_clipboard_batches_window(
        cls,
        clipboard_text: str,
        session_id: str,
        seen_batch_ids: Optional[set] = None,
    ) -> Optional[Tuple[List[str], List[ShareProfile], int]]:
        """
        Parses either a single `FB_CONTEST_BATCH_V1:{...}` batch or a rolling ring-buffer
        clipboard payload containing `batches: [{batch_id, action_type, items}, ...]`.
        Filters out any sub-batch already present in `seen_batch_ids` so only unseen
        batches are parsed and returned.
        Returns `(new_batch_ids, new_profiles, total_batches_in_window)` or `None`.
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

        seen = seen_batch_ids if seen_batch_ids is not None else set()
        sub_batches = payload.get("batches")
        if isinstance(sub_batches, list) and sub_batches:
            new_batch_ids: List[str] = []
            combined_profiles: List[ShareProfile] = []
            for sb in sub_batches:
                if not isinstance(sb, dict):
                    continue
                b_id = str(sb.get("batch_id") or "").strip()
                if not b_id or b_id in seen:
                    continue
                b_action = str(sb.get("action_type") or payload.get("action_type") or "share").lower()
                b_items = sb.get("items") or []
                profs = cls.parse_dom_items(
                    raw_items=b_items,
                    session_id=session_id,
                    action_type=b_action,
                    scroll_index=0,
                )
                new_batch_ids.append(b_id)
                combined_profiles.extend(profs)
            return new_batch_ids, combined_profiles, len(sub_batches)

        # Single-batch payload fallback
        batch_id = str(payload.get("batch_id") or "").strip()
        if not batch_id or batch_id in seen:
            return [], [], 1

        default_action = str(payload.get("action_type") or "share").lower()
        raw_items = payload.get("items") or []
        profiles = cls.parse_dom_items(
            raw_items=raw_items,
            session_id=session_id,
            action_type=default_action,
            scroll_index=0,
        )
        return [batch_id], profiles, 1

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

        from app.utils.sentra_brand import (
            APP_DESCRIPTION,
            APP_PILLARS,
            APP_TAGLINE,
            APP_UPPER,
            get_sentra_logo_svg,
        )

        page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>SENTRA — 1-Click Browser Bookmarklet & Extension Setup</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0b1120;
      color: #f8fafc;
      max-width: 780px;
      margin: 32px auto;
      padding: 24px;
      line-height: 1.6;
    }}
    .brand-hero {{
      background: #0d1526;
      border: 1px solid #1e293b;
      border-radius: 14px;
      padding: 22px 26px;
      margin-bottom: 24px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.45);
    }}
    .brand-top {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;
    }}
    .brand-title {{
      font-size: 24px;
      font-weight: 800;
      letter-spacing: 1.5px;
      color: #ffffff;
    }}
    .brand-tagline {{
      font-size: 18px;
      font-weight: 700;
      color: #f8fafc;
      margin: 4px 0 6px 0;
    }}
    .brand-desc {{
      font-size: 13.5px;
      color: #94a3b8;
      margin: 0 0 12px 0;
    }}
    .brand-pillars {{
      font-size: 11.5px;
      font-weight: 800;
      letter-spacing: 1.4px;
      color: #35c5f0;
      border-top: 1px solid #1e293b;
      padding-top: 10px;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 14px;
      padding: 24px 28px;
      margin-bottom: 24px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.35);
    }}
    h1 {{ color: #35c5f0; margin-top: 0; font-size: 21px; }}
    h2 {{ color: #93c5fd; margin-top: 0; font-size: 18px; }}
    .bookmarklet-btn {{
      display: inline-block;
      background: linear-gradient(135deg, #0284c7, #2563eb);
      color: #ffffff;
      font-weight: 800;
      font-size: 17px;
      text-decoration: none;
      padding: 14px 28px;
      border-radius: 999px;
      border: 2px dashed #35c5f0;
      box-shadow: 0 8px 20px rgba(53, 197, 240, 0.35);
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
  <div class="brand-hero">
    <div class="brand-top">
      {get_sentra_logo_svg(size=36, stroke_color="#35c5f0")}
      <span class="brand-title">{APP_UPPER}</span>
    </div>
    <div class="brand-tagline">{APP_TAGLINE}</div>
    <div class="brand-desc">{APP_DESCRIPTION}</div>
    <div class="brand-pillars">{APP_PILLARS}</div>
  </div>

  <div class="card">
    <h1>🔖 Option A: 1-Click Sentra Browser Bookmark (Zero Installation)</h1>
    <p>Works in <strong>Chrome, Safari, Edge, Brave, and Firefox</strong> without installing anything:</p>
    <ol>
      <li>Make sure your browser's <strong>Bookmarks Bar</strong> is visible (<code>Cmd+Shift+B</code> on Mac or <code>Ctrl+Shift+B</code> on Windows).</li>
      <li><strong>Drag the glowing Sentra button below</strong> up onto your Bookmarks Bar:</li>
    </ol>
    <p style="text-align:center;">
      <a class="bookmarklet-btn" href="{bookmarklet_href}" title="Drag me to your Bookmarks Bar!">🛰️ SENTRA Signal Collector</a>
      <button class="copy-btn" onclick="navigator.clipboard.writeText(document.querySelector('.bookmarklet-btn').href);this.textContent='✅ Sentra Bookmarklet Copied!';">📋 Copy Bookmark URL</button>
    </p>
    <ol start="3">
      <li>Open your Facebook contest post in your browser and <strong>click the <code>🛰️ SENTRA Signal Collector</code> bookmark</strong> on your Bookmarks Bar — the floating Sentra panel will appear immediately!</li>
      <li>Click <strong>Step 1 (Reactions)</strong>, <strong>Step 2 (Comments)</strong>, and <strong>Step 3 (Shares)</strong> — every batch is automatically streamed to your Sentra Desktop App!</li>
    </ol>
  </div>

  <div class="card">
    <h2>🧩 Option B: Installable Sentra Chrome / Edge Extension (Auto-Loads on Facebook)</h2>
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
