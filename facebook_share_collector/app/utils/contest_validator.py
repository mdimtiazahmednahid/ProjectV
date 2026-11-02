import re
from typing import List, Dict, Optional
from app.models.share_profile import ShareProfile, ContestParticipant
from app.utils.text_normalizer import normalize_text
from app.utils.url_normalizer import normalize_url
from app.utils.avatar_fingerprint import hamming_distance

PROFILE_PIC_SUFFIX_RE = re.compile(
    r"(?:\s+profile\s+(?:picture|photo)(?:,\s*.*)?|^profile\s+(?:picture|photo)\s+of\s+|\s+(?:Liked|Loved|Cared|Haha|Wow|Sad|Angry)$)",
    re.IGNORECASE
)


class IncrementalContestAggregator:
    """
    O(1) incremental identity-disambiguating contest aggregator capable of handling
    100,000+ interactions without UI freezes while differentiating same-name users
    via Profile URL and 64-bit Perceptual Avatar Hash (dHash).
    """

    def __init__(self):
        self.participants: List[ContestParticipant] = []
        self._by_url: Dict[str, ContestParticipant] = {}
        self._by_name_buckets: Dict[str, List[ContestParticipant]] = {}
        self._likes_count: int = 0
        self._comments_count: int = 0
        self._shares_count: int = 0
        self._eligible_count: int = 0

    def clear(self):
        self.participants.clear()
        self._by_url.clear()
        self._by_name_buckets.clear()
        self._likes_count = 0
        self._comments_count = 0
        self._shares_count = 0
        self._eligible_count = 0

    @staticmethod
    def _clean_author_name(raw_name: str) -> str:
        cleaned = normalize_text(raw_name or "")
        cleaned = PROFILE_PIC_SUFFIX_RE.sub("", cleaned).strip()
        return cleaned

    @staticmethod
    def _clean_comment_text(raw_content: str, author_name: str) -> str:
        if not raw_content:
            return ""
        noise_exact = {
            "loved by author", "liked by author", "by author", "see original", "see translation",
            "hide translation", "·", "•", "· follow", "• follow", "follow",
            "create your avatar", "top fan", "author", "edited", "giphy"
        }
        noise_starts = (
            "reply to ", "like ", "downvote ", "upvote ", "reacted:", "love button"
        )
        noise_contains = (
            "comment button", "show reaction tray", "downvote ", "upvote ",
            "change reaction"
        )
        norm_author = normalize_text(author_name).lower()
        lines = []
        for line in raw_content.splitlines():
            ln = line.strip()
            if not ln:
                continue
            ln = re.sub(r"^(?:(?:liked|loved)\s+)?by\s+author\s+", "", ln, flags=re.IGNORECASE).strip()
            ln = re.sub(r"\s+GIPHY$", "", ln, flags=re.IGNORECASE).strip()
            if not ln:
                continue
            ln_low = ln.lower()
            if normalize_text(ln).lower() == norm_author:
                continue
            if (
                ln_low in noise_exact
                or any(ln_low.startswith(p) for p in noise_starts)
                or any(sub in ln_low for sub in noise_contains)
            ):
                continue
            lines.append(ln)
        return " ".join(lines).strip()

    def _find_matching_participant(
        self,
        norm_name: str,
        norm_url: Optional[str],
        avatar_hash: Optional[str],
        scroll_index: int = 0,
        action_type: str = "share",
        clean_text: str = ""
    ) -> Optional[ContestParticipant]:
        # 1. Exact Profile URL match (100% certainty)
        if norm_url and norm_url in self._by_url:
            return self._by_url[norm_url]

        # 2. Check existing candidates with the same normalized name
        candidates = self._by_name_buckets.get(norm_name, [])
        if not candidates:
            return None

        for cand in candidates:
            cand_url = normalize_url(cand.profile_url).lower() if cand.profile_url else None

            # Case A: Both have Profile URLs -> must match exactly
            if norm_url and cand_url:
                if norm_url == cand_url:
                    return cand
                continue

            # Case A2: Exact Comment/Share Text match for the same author name (without conflicting URL)
            if clean_text and (clean_text in cand.comment_texts or clean_text in cand.share_contents):
                return cand

            # Case B: Both have Avatar Hashes (and no conflicting URL)
            if avatar_hash and cand.avatar_hash:
                scroll_by_act = getattr(cand, "_scroll_by_action", {})
                if action_type in scroll_by_act:
                    prev_s = scroll_by_act[action_type]
                    if 1 <= abs(scroll_index - prev_s) <= 2 or (scroll_index >= 1 and scroll_index == prev_s):
                        return cand
                known_hashes = getattr(cand, "_known_hashes", {cand.avatar_hash})
                threshold = 24 if (action_type not in scroll_by_act and len(candidates) == 1) else 20
                if any(hamming_distance(avatar_hash, kh) <= threshold for kh in known_hashes):
                    return cand
                continue

            # Case C: Fallback to name match if at least one record has no explicit ID,
            # OR if this name has a single unique candidate (len(candidates) == 1) and one side is
            # Web (norm_url only) while the other side is Phone (avatar_hash only).
            incoming_has_id = bool(norm_url or avatar_hash)
            cand_has_id = bool(cand_url or cand.avatar_hash)
            if not incoming_has_id or not cand_has_id:
                return cand
            if len(candidates) == 1 and bool(norm_url) != bool(cand_url):
                return cand

        return None

    @staticmethod
    def _sanitize_avatar_hash(h: Optional[str]) -> Optional[str]:
        if not h:
            return None
        h_clean = h.strip().lower()
        if h_clean in ("0000000000000000", "0000000000000001", "ffffffffffffffff"):
            return h_clean
        # Reject corrupted Android screen-transition / status-bar / header-bar crops
        if (
            "000000" in h_clean
            or "ffffff" in h_clean
            or "00040800" in h_clean
            or "cccccc" in h_clean
        ):
            return None
        return h_clean

    @staticmethod
    def is_ui_noise_name(clean_name: str, profile_url: Optional[str] = None) -> bool:
        if not clean_name:
            return True
        norm_name = clean_name.lower().strip()
        if (
            norm_name in ("see original", "photo", "contact info", "website", "all posts", "hidden by facebook", "active")
            or "online status indicator" in norm_name
            or norm_name.startswith("reply to ")
            or norm_name.startswith("like ")
            or norm_name.startswith("downvote ")
            or (not profile_url and sum(1 for ch in clean_name if ch.isalpha()) < 2)
        ):
            return True
        return False

    def add_profile(self, p: ShareProfile) -> Optional[ContestParticipant]:
        if not p.name and not p.profile_url:
            return None

        clean_name = self._clean_author_name(p.name) or p.profile_url or "Unknown"
        norm_name = clean_name.lower()

        # Skip any legacy UI noise rows
        if self.is_ui_noise_name(clean_name, p.profile_url):
            return None
        norm_url = normalize_url(p.profile_url).lower() if p.profile_url else None
        avatar_hash = self._sanitize_avatar_hash(getattr(p, "avatar_hash", None))
        avatar_path = getattr(p, "avatar_path", None) if avatar_hash else None
        action = (getattr(p, "action_type", "share") or "share").lower().strip()
        clean_text = self._clean_comment_text(p.content, clean_name) if (p.content and p.content.strip()) else ""

        participant = self._find_matching_participant(
            norm_name, norm_url, avatar_hash, getattr(p, "scroll_index", 0), action, clean_text
        )

        if participant is None:
            bucket = self._by_name_buckets.setdefault(norm_name, [])
            key_suffix = norm_url or avatar_hash or str(len(bucket) + 1)
            participant = ContestParticipant(
                name=clean_name,
                normalized_key=f"id:{norm_name}:{key_suffix}",
                profile_url=p.profile_url,
                avatar_hash=avatar_hash,
                avatar_path=avatar_path,
                first_seen_at=p.first_seen_at,
                scroll_index=p.scroll_index,
            )
            participant._last_action = action
            participant._scroll_by_action = {action: getattr(p, "scroll_index", 0)}
            participant._known_hashes = {avatar_hash} if avatar_hash else set()
            bucket.append(participant)
            self.participants.append(participant)

            # If multiple distinct people share the same display name, assign disambiguators
            if len(bucket) > 1:
                for idx, same_name_p in enumerate(bucket, 1):
                    if same_name_p.profile_url:
                        slug = same_name_p.profile_url.rstrip("/").split("/")[-1][:16]
                        same_name_p.disambiguator = f"User #{idx} · {slug}"
                    elif same_name_p.avatar_hash:
                        same_name_p.disambiguator = f"User #{idx} · Avatar:{same_name_p.avatar_hash[:6]}"
                    else:
                        same_name_p.disambiguator = f"User #{idx}"
        else:
            participant.scroll_index = getattr(p, "scroll_index", participant.scroll_index)
            participant._last_action = action
            if not hasattr(participant, "_scroll_by_action"):
                participant._scroll_by_action = {}
            participant._scroll_by_action[action] = getattr(p, "scroll_index", 0)
            if not hasattr(participant, "_known_hashes"):
                participant._known_hashes = set()
            if avatar_hash:
                participant._known_hashes.add(avatar_hash)
            if not participant.profile_url and p.profile_url:
                participant.profile_url = p.profile_url
            if not participant.avatar_hash and avatar_hash:
                participant.avatar_hash = avatar_hash
            if not participant.avatar_path and avatar_path:
                participant.avatar_path = avatar_path

        if norm_url:
            self._by_url[norm_url] = participant

        was_eligible = participant.is_eligible
        if action == "like":
            if not participant.liked:
                participant.liked = True
                self._likes_count += 1
        elif action == "comment":
            if not participant.commented:
                participant.commented = True
                self._comments_count += 1
            if clean_text and clean_text not in participant.comment_texts:
                participant.comment_texts.append(clean_text)
        else:
            if not participant.shared:
                participant.shared = True
                self._shares_count += 1
            if p.content and p.content.strip():
                clean_share = p.content.strip()
                if clean_share not in participant.share_contents:
                    participant.share_contents.append(clean_share)

        if not was_eligible and participant.is_eligible:
            self._eligible_count += 1

        return participant

    def get_sorted_participants(self) -> List[ContestParticipant]:
        result = list(self.participants)
        result.sort(key=lambda item: (-item.actions_completed, item.name.lower(), item.disambiguator))

        # Assign sequential Contest Serial Numbers (#0001, #0002...) to all Eligible (3/3) winners
        serial = 1
        for item in result:
            if item.is_eligible:
                item.serial_number = serial
                serial += 1
            else:
                item.serial_number = None
        return result

    def get_counts(self) -> Dict[str, int]:
        return {
            "total_participants": len(self.participants),
            "likes": self._likes_count,
            "comments": self._comments_count,
            "shares": self._shares_count,
            "eligible": self._eligible_count,
        }


class ContestValidator:
    """
    Stateless facade wrapping IncrementalContestAggregator for batch validation.
    """

    @classmethod
    def validate_participants(cls, profiles: List[ShareProfile]) -> List[ContestParticipant]:
        agg = IncrementalContestAggregator()
        for p in profiles:
            agg.add_profile(p)
        return agg.get_sorted_participants()

    @classmethod
    def compute_counts(cls, profiles: List[ShareProfile]) -> Dict[str, int]:
        agg = IncrementalContestAggregator()
        for p in profiles:
            agg.add_profile(p)
        return agg.get_counts()
