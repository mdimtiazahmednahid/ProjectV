import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from app.models.share_profile import ShareProfile
from app.automation.ui_inspector import UIInspector
from app.utils.text_normalizer import normalize_text
from app.utils.avatar_fingerprint import AvatarFingerprinter, parse_bounds

logger = logging.getLogger(__name__)


class ProfileExtractor:
    # Matches "<Author Name> profile picture", "<Author Name>'s profile picture", or "Profile picture of <Author Name>"
    PROFILE_PIC_DESC_RE = re.compile(
        r"^(?:profile\s+(?:picture|photo)\s+of\s+(.+?)|(.+?)(?:'s|\u2019s)?\s+profile\s+(?:picture|photo)(?:,\s*.*)?)$",
        re.IGNORECASE,
    )
    REACTION_SUFFIX_RE = re.compile(
        r"(?:\s*[,·•]\s*|\s+)(?:Liked|Loved|Cared|Haha|Wow|Sad|Angry)\.?$",
        re.IGNORECASE,
    )
    INLINE_ACTION_META_RE = re.compile(
        r"(?:\s*[,·•]\s*|\s+•\s+)(?:Add friend|Cancel request|Follow|Following|Friends|Message|Invite|Invited|\d+\s*mutual\s+friends?|\d+\s*[smhdwy]\b(?:\s+ago)?|just now|yesterday|author|top fan|admin|moderator|rising contributor|top contributor|edited).*$",
        re.IGNORECASE,
    )

    def __init__(self, min_confidence=0.60):
        self.min_confidence = min_confidence
        self.fingerprinter = AvatarFingerprinter()
        self.last_active_bounds: Optional[Tuple[int, int, int, int]] = None
        self.last_detected_window_type: str = "unknown"

    @staticmethod
    def _has_letters(text: str) -> bool:
        """
        Returns True if text contains at least 2 alphabetic/Bangla letters
        (prevents pure emoji strings like '💓💓' or '·' from being mistaken for a person's name).
        """
        if not text:
            return False
        letter_count = sum(1 for ch in text if ch.isalpha())
        return letter_count >= 2

    @classmethod
    def classify_container_window(cls, container, root=None) -> str:
        """
        Classifies an Android scrollable container (`RecyclerView` / `ListView` / `ScrollView`)
        into one of: "like", "comment", "share", or "unknown".
        """
        blob_parts = []
        for el in container.iter():
            td = (el.attrib.get("text", "") + " " + el.attrib.get("content-desc", "")).strip().lower()
            if td:
                blob_parts.append(td)
        blob = " | ".join(blob_parts)

        # Also check root headers outside the RecyclerView if available
        root_blob = ""
        if root is not None:
            r_parts = []
            for el in root.iter():
                td = (el.attrib.get("text", "") + " " + el.attrib.get("content-desc", "")).strip().lower()
                if td in ("people who reacted", "people who shared this", "reactions", "shares", "comments"):
                    r_parts.append(td)
            root_blob = " | ".join(r_parts)

        # 1. Explicit Modal Screen Titles take top precedence
        if "people who shared this" in blob or "people who shared this" in root_blob:
            return "share"
        if "people who reacted" in blob or "people who reacted" in root_blob:
            return "like"

        # 2. Strong Comment indicators inside the container
        if (
            "comment button" in blob
            or "reply to " in blob
            or "write a comment" in blob
            or "most relevant" in blob
            or "all comments" in blob
            or "downvote " in blob
            or "upvote " in blob
        ):
            return "comment"

        # 3. Secondary Share indicators
        if (
            "shared with: public" in blob
            or "shared with public" in blob
            or "send in messenger" in blob
        ):
            return "share"

        # 4. Secondary Like / Reaction list indicators
        if "add friend" in blob and "comment" not in blob and "shared with" not in blob:
            return "like"

        return "unknown"

    @classmethod
    def _select_single_active_container(
        cls,
        raw_containers: list,
        action_type: str,
        root=None,
    ) -> Tuple[list, Optional[Tuple[int, int, int, int]], str]:
        """
        1. Excludes tiny horizontal tab bar RecyclerViews (e.g. Reaction tabs with height < 280px or width > height * 2.5).
        2. Classifies each valid scrollable container into 'like', 'comment', 'share', or 'unknown'.
        3. Always returns AT MOST ONE foreground container (`[chosen]`) so we NEVER scrape or scroll
           both a foreground bottom-sheet popup and a background feed at the same time!
        """
        valid = []
        for c in raw_containers:
            b = parse_bounds(c.attrib.get("bounds", ""))
            if b:
                _, _, w, h = b
                if h < 280 or (w > h * 2.5):
                    continue
            valid.append((c, b, cls.classify_container_window(c, root=root)))

        if not valid:
            fallback = raw_containers[-1:] if raw_containers else []
            fb_bounds = parse_bounds(fallback[0].attrib.get("bounds", "")) if fallback else None
            return fallback, fb_bounds, "unknown"

        # First priority: container whose classified type matches the requested action_type (pick topmost/last in XML tree)
        matching = [item for item in valid if item[2] == action_type]
        if matching:
            chosen_c, chosen_b, chosen_kind = matching[-1]
            return [chosen_c], chosen_b, chosen_kind

        # Second priority: if top container is 'unknown', allow it
        unknowns = [item for item in valid if item[2] == "unknown"]
        if unknowns:
            chosen_c, chosen_b, chosen_kind = unknowns[-1]
            return [chosen_c], chosen_b, chosen_kind

        # Otherwise return the topmost valid container along with its actual detected kind
        chosen_c, chosen_b, chosen_kind = valid[-1]
        return [chosen_c], chosen_b, chosen_kind

    @staticmethod
    def find_expand_comments_tap_coords(xml_source: str) -> Optional[Tuple[int, int]]:
        """
        Finds the screen center `(x, y)` of a 'View more comments' / 'View previous comments' /
        'See more replies' button in Android XML so CollectorEngine can tap it automatically.
        """
        if not xml_source:
            return None
        try:
            root = ET.fromstring(xml_source)
        except Exception:
            return None

        for el in root.iter():
            t = (el.attrib.get("text") or "").strip().lower()
            c = (el.attrib.get("content-desc") or "").strip().lower()
            label = t or c
            if not label:
                continue
            if (
                label.startswith("view more comments")
                or label.startswith("view previous comments")
                or re.match(r"^view\s+\d+\s+more\s+(?:comments?|replies)", label)
                or re.match(r"^\d+\s+replies$", label)
            ):
                b = parse_bounds(el.attrib.get("bounds", ""))
                if b:
                    x, y, w, h = b
                    if w > 20 and h > 15:
                        return (x + w // 2, y + h // 2)
        return None

    def extract(
        self,
        xml_source: str,
        session_id: str,
        action_type: str = "share",
        screenshot_png: Optional[bytes] = None,
    ) -> List[ShareProfile]:
        profiles = []
        if not xml_source:
            return profiles

        try:
            root = ET.fromstring(xml_source)
        except Exception as e:
            logger.error(f"Failed to parse XML: {e}")
            return profiles

        target_classes = {
            "androidx.recyclerview.widget.RecyclerView",
            "android.widget.ListView",
            "android.widget.ScrollView",
            "androidx.core.widget.NestedScrollView",
            "androidx.viewpager.widget.ViewPager",
            "androidx.viewpager2.widget.ViewPager2",
        }
        list_containers = []
        seen_elems = set()
        for el in root.iter():
            if (
                el.tag in target_classes
                or el.attrib.get("class") in target_classes
                or el.attrib.get("scrollable") == "true"
            ):
                if id(el) not in seen_elems:
                    seen_elems.add(id(el))
                    list_containers.append(el)

        if not list_containers:
            logger.warning("No list container found in XML. Returning empty.")
            return profiles

        list_containers, active_bounds, detected_kind = self._select_single_active_container(
            list_containers, action_type, root=root
        )
        self.last_active_bounds = active_bounds
        self.last_detected_window_type = detected_kind

        ignore_exact = {
            "share", "like", "comment", "reply", "follow", "following", "friends",
            "add friend", "cancel request", "message", "invite", "invited",
            "see more", "back", "close", "search", "menu", "profile photo",
            "profile picture", "see translation", "hide translation", "see original",
            "rate this translation", "media", "photo", "video", "reel",
            "create your avatar", "reactions", "comments", "shares",
            "people who reacted", "people who shared this", "most relevant",
            "all comments", "newest", "top fan", "author", "admin", "moderator",
            "rising contributor", "top contributor", "edited", "all", "love",
            "care", "haha", "wow", "sad", "angry", "send", "copy", "report",
            "block", "loved by author", "liked by author", "all posts",
            "contact info", "website", "hidden by facebook", "pinned post",
            "·", "•", "· follow", "• follow",
        }
        ignore_starts = (
            "like button", "love button", "comment button", "share button",
            "people who shared this", "people who reacted", "send in messenger",
            "write a comment", "write a reply", "comment as ", "view ", "hide ",
            "see previous", "see more", "most relevant", "all comments",
            "replied to ", "reply to ", "react to ", "reacted:", "double tap",
            "like ", "downvote ", "upvote ", "more options for ", "shared with:",
            "pinned post", "profile photo of", "profile picture of",
        )
        ignore_contains = (
            "comment button", "show reaction tray", "downvote ", "upvote ",
            "change reaction", "unseen story", "seen story", "shared with: public",
        )

        counter_pattern = re.compile(
            r"^(?:all\s+)?[0-9KMB,.]+\s*(?:shares?|comments?|reactions?|likes?|views?|replies|mutual\s+friends?|of\s+\d+)?$",
            re.IGNORECASE,
        )
        timestamp_pattern = re.compile(
            r"^(?:[·•\s]*)?(\d+\s*(?:[smhdwy]|sec|min|hr|hrs|day|days|wk|wks|yr|yrs)(?:\s+ago)?|just now|yesterday.*|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d+(?:,\s+\d{4})?.*)$",
            re.IGNORECASE,
        )

        def _is_noise_line(ln_str: str) -> bool:
            if not ln_str:
                return True
            low = ln_str.lower().strip()
            if (
                low in ignore_exact
                or any(low.startswith(p) for p in ignore_starts)
                or any(sub in low for sub in ignore_contains)
            ):
                return True
            if counter_pattern.match(ln_str) or timestamp_pattern.match(ln_str):
                return True
            return False

        def _clean_candidate_name(raw_str: str) -> str:
            cand = self.INLINE_ACTION_META_RE.sub("", raw_str).strip()
            cand = self.REACTION_SUFFIX_RE.sub("", cand).strip()
            cand = self.INLINE_ACTION_META_RE.sub("", cand).strip()
            return cand

        for container in list_containers:
            rows = container.findall("./*")
            # If ScrollView or wrapped RecyclerView has a single child wrapper holding the rows, unwrap it
            while len(rows) == 1 and len(rows[0].findall("./*")) >= 2:
                rows = rows[0].findall("./*")

            for item in rows:
                all_strings = []
                has_clickable_or_heading = False
                has_multiline_block = False
                for el in item.iter():
                    if el.attrib.get("heading") == "true" or el.attrib.get("clickable") == "true":
                        t_check = (el.attrib.get("text") or el.attrib.get("content-desc") or "").strip()
                        if t_check and not _is_noise_line(t_check):
                            has_clickable_or_heading = True
                    for attr in ("text", "content-desc"):
                        v = (el.attrib.get(attr) or "").strip()
                        if v:
                            all_strings.append(v)
                            if "\n" in v:
                                has_multiline_block = True

                joined_lower = " | ".join(all_strings).lower()

                # Skip original post/reel media preview cards or page bio cards
                if "pinned post" in joined_lower or "more options for " in joined_lower or "contact info" in joined_lower:
                    continue

                if action_type == "share":
                    descs = {(el.attrib.get("content-desc") or "").strip().lower() for el in item.iter()}
                    if "media" in descs and "profile photo" not in descs and "profile picture" not in descs:
                        continue

                name = None
                name_bounds = None
                avatar_bounds = None
                has_explicit_profile_pic_node = False
                content_parts = []
                reactions = None
                comments = None
                url = None
                confidence = 0.8

                # First pass on item: check if there's an explicit "<Name> profile picture" or "Profile picture of <Name>" node
                for elem in item.iter():
                    c = (elem.attrib.get("content-desc") or "").strip()
                    t = (elem.attrib.get("text") or "").strip()
                    bounds = (elem.attrib.get("bounds") or "").strip()
                    cls_name = elem.attrib.get("class", "") or elem.tag

                    for candidate_str in (c, t):
                        if not candidate_str:
                            continue
                        m_pic = self.PROFILE_PIC_DESC_RE.match(candidate_str)
                        if m_pic:
                            raw_author = (m_pic.group(1) or m_pic.group(2) or "").strip()
                            extracted_author = _clean_candidate_name(raw_author)
                            if self._has_letters(extracted_author):
                                name = extracted_author
                                avatar_bounds = bounds
                                has_explicit_profile_pic_node = True
                                confidence = 0.95
                                break
                    if has_explicit_profile_pic_node:
                        break

                    if not avatar_bounds and bounds:
                        if c.lower() in ("profile photo", "profile picture") or "ImageView" in cls_name:
                            avatar_bounds = bounds

                # If collecting comments on a real Facebook screen and the top of the comment
                # was scrolled off-screen (so only "Reply to X's comment" / "Like X's comment" is visible
                # with NO avatar, NO heading/clickable name, and NO multiline author+comment block),
                # skip this cut-off fragment so comment text or buttons aren't mistaken for a user name!
                if (
                    action_type == "comment"
                    and not has_explicit_profile_pic_node
                    and not avatar_bounds
                    and not has_clickable_or_heading
                    and not has_multiline_block
                ):
                    if "reply to " in joined_lower or "comment button" in joined_lower or "downvote " in joined_lower:
                        continue

                for elem in item.iter():
                    t = elem.attrib.get("text", "").strip()
                    c = elem.attrib.get("content-desc", "").strip()
                    h = elem.attrib.get("heading", "false") == "true"
                    clickable = elem.attrib.get("clickable", "false") == "true"
                    bounds = elem.attrib.get("bounds", "").strip()

                    val = t if t else c
                    if not val:
                        continue

                    cleaned_val = val.replace("\ufffc", "").strip()
                    if not cleaned_val:
                        continue

                    # Skip "<Name> profile picture..." nodes during text scan
                    if self.PROFILE_PIC_DESC_RE.match(cleaned_val):
                        continue

                    lower_val = cleaned_val.lower()

                    # 1. Skip explicit single-line UI noise
                    if "\n" not in cleaned_val and _is_noise_line(cleaned_val):
                        continue

                    # 2. Extract Profile URL if available
                    if "facebook.com/" in lower_val:
                        url = c if c else t
                        if not name and "," in cleaned_val:
                            possible_name = _clean_candidate_name(cleaned_val.split(",", 1)[0].strip())
                            if self._has_letters(possible_name):
                                name = possible_name
                                name_bounds = bounds
                                confidence = 0.9
                        continue

                    # 3. Extract Reactions and Comments counts
                    reaction_match = re.search(r"([0-9KMB,.]+)\s*reaction", cleaned_val, re.IGNORECASE)
                    comment_match = re.search(r"([0-9KMB,.]+)\s*comment", cleaned_val, re.IGNORECASE)
                    if reaction_match or comment_match:
                        if reaction_match:
                            reactions = reaction_match.group(1).strip()
                        if comment_match:
                            comments = comment_match.group(1).strip()
                        continue

                    # 4. Extract Name (supports both single-line nodes and multiline Litho blocks)
                    if not name:
                        valid_lines = [
                            ln.strip()
                            for ln in cleaned_val.splitlines()
                            if ln.strip() and not _is_noise_line(ln.strip())
                        ]
                        if not valid_lines:
                            continue

                        first_line = valid_lines[0]
                        candidate_name = _clean_candidate_name(first_line)
                        if not self._has_letters(candidate_name) or _is_noise_line(candidate_name):
                            continue

                        if len(candidate_name) < 60 and not candidate_name.startswith(("#", "@")) and "http" not in candidate_name.lower() and ".com" not in candidate_name.lower():
                            name = candidate_name
                            name_bounds = bounds
                            if h:
                                confidence = 1.0
                            elif clickable or len(valid_lines) > 1:
                                confidence = 0.85
                            else:
                                confidence = 0.65

                            # If this was a multiline Litho block (e.g. "Author Name\n· Follow\nComment body"),
                            # capture the remaining clean lines as comment/share content immediately!
                            if action_type in ("comment", "share") and len(valid_lines) > 1:
                                rem_lines = [
                                    ln for ln in valid_lines[1:]
                                    if normalize_text(ln).lower() != normalize_text(name).lower()
                                ]
                                rem_block = "\n".join(rem_lines).strip()
                                if rem_block and rem_block not in content_parts:
                                    content_parts.append(rem_block)
                    else:
                        # 5. Extract clean Content (for comments & shares)
                        if action_type in ("comment", "share"):
                            if normalize_text(cleaned_val).lower() != normalize_text(name).lower():
                                clean_lines = []
                                for line in cleaned_val.splitlines():
                                    ln = line.strip()
                                    if not ln:
                                        continue
                                    if normalize_text(ln).lower() == normalize_text(name).lower():
                                        continue
                                    if _is_noise_line(ln):
                                        continue
                                    clean_lines.append(ln)

                                cleaned_block = "\n".join(clean_lines).strip()
                                if cleaned_block and cleaned_block not in content_parts:
                                    content_parts.append(cleaned_block)

                if name and confidence >= self.min_confidence:
                    # On Android Likes/Comments (Litho single-ViewGroup rows), infer left-side circular avatar bounds if ImageView was omitted
                    if not avatar_bounds:
                        row_rect = parse_bounds(item.attrib.get("bounds", ""))
                        if row_rect:
                            rx1, ry1, rw, rh = row_rect
                            if rx1 <= 80 and 90 <= rh <= 340 and rw >= 500:
                                cy = ry1 + min(rh // 2, 75)
                                avatar_bounds = f"[{rx1 + 36},{cy - 50}][{rx1 + 136},{cy + 50}]"

                    avatar_hash, avatar_path = None, None
                    if screenshot_png and avatar_bounds:
                        avatar_hash, avatar_path = self.fingerprinter.crop_and_hash(screenshot_png, avatar_bounds)

                    profiles.append(
                        ShareProfile(
                            name=normalize_text(name),
                            profile_url=url,
                            share_url=None,
                            content="\n".join(content_parts) if content_parts else "",
                            reactions=reactions,
                            comments=comments,
                            action_type=action_type,
                            avatar_hash=avatar_hash,
                            avatar_path=avatar_path,
                            avatar_bounds=avatar_bounds,
                            name_bounds=name_bounds,
                            confidence=confidence,
                            source="facebook_android_ui",
                            session_id=session_id,
                        )
                    )

        # Deduplicate within this single screen pass by (normalized_name, action_type, profile_url, avatar_hash)
        unique_profiles = {}
        for p in profiles:
            key = (p.name.lower(), p.action_type, p.profile_url or "", p.avatar_hash or "")
            if key not in unique_profiles:
                unique_profiles[key] = p
            else:
                existing = unique_profiles[key]
                if p.content and not existing.content:
                    existing.content = p.content
                elif p.content and p.content not in existing.content:
                    existing.content += f" | {p.content}"
                if not existing.avatar_path and p.avatar_path:
                    existing.avatar_path = p.avatar_path
                    existing.avatar_hash = p.avatar_hash
                if p.reactions and not existing.reactions:
                    existing.reactions = p.reactions
                if p.comments and not existing.comments:
                    existing.comments = p.comments

        final_profiles = list(unique_profiles.values())
        logger.debug(
            f"Extracted {len(final_profiles)} '{action_type}' candidates from source (window={self.last_detected_window_type})."
        )
        return final_profiles
