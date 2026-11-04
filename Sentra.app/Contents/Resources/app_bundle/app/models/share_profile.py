from dataclasses import dataclass, field
import datetime
import uuid
from typing import Optional, List

@dataclass
class ShareProfile:
    name: str
    source: str
    confidence: float
    session_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    profile_url: Optional[str] = None
    share_url: Optional[str] = None
    content: Optional[str] = None
    reactions: Optional[str] = None
    comments: Optional[str] = None
    action_type: str = "share"  # "like", "comment", or "share"
    shared_post_url: Optional[str] = None
    avatar_hash: Optional[str] = None
    avatar_path: Optional[str] = None
    avatar_bounds: Optional[str] = None
    name_bounds: Optional[str] = None
    first_seen_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    last_seen_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    scroll_index: int = 0

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "profile_url": self.profile_url,
            "share_url": self.share_url,
            "shared_post_url": self.shared_post_url,
            "content": self.content,
            "reactions": self.reactions,
            "comments": self.comments,
            "action_type": self.action_type,
            "avatar_hash": self.avatar_hash,
            "avatar_path": self.avatar_path,
            "source": self.source,
            "confidence": self.confidence,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "session_id": self.session_id,
            "scroll_index": self.scroll_index,
        }


REACTION_EMOJI_MAP = {
    "like": "👍 Like",
    "love": "❤️ Love",
    "care": "🥰 Care",
    "haha": "😆 Haha",
    "wow": "😮 Wow",
    "sad": "😢 Sad",
    "angry": "😡 Angry",
}


def normalize_reaction_type(raw_val: Optional[str]) -> str:
    """
    Normalizes any raw reaction string, emoji, or localized label into one of:
    'Like', 'Love', 'Care', 'Haha', 'Wow', 'Sad', 'Angry', or '' if unknown/numeric.
    """
    if not raw_val:
        return ""
    s = str(raw_val).strip()
    if not s or s.isdigit():
        return ""
    low = s.lower().strip(".,!?:;()[]{}\"'·• ")
    if low in ("like", "liked", "👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "লাইক", "👍 like"):
        return "Like"
    if low in ("love", "loved", "❤️", "❤", "♥️", "♥", "💕", "💖", "💗", "💓", "লাভ", "ভালোবাসা", "❤️ love", "❤ love"):
        return "Love"
    if low in ("care", "cared", "🥰", "🤗", "কেয়ার", "কেয়ার", "যত্ন", "🥰 care"):
        return "Care"
    if low in ("haha", "😆", "😂", "🤣", "😄", "হাহা", "😆 haha"):
        return "Haha"
    if low in ("wow", "😮", "😲", "😯", "ওয়াও", "ওয়াও", "অবাক", "😮 wow"):
        return "Wow"
    if low in ("sad", "😢", "😭", "😥", "স্যাড", "দুঃখিত", "😢 sad"):
        return "Sad"
    if low in ("angry", "😡", "😠", "🤬", "অ্যাংরি", "রাগান্বিত", "রাগ", "😡 angry"):
        return "Angry"

    # Substring / prefix check for phrases like "Reacted: Love", "Love reaction", "Liked by ..."
    for key, canonical in (
        ("love", "Love"),
        ("care", "Care"),
        ("haha", "Haha"),
        ("wow", "Wow"),
        ("sad", "Sad"),
        ("angry", "Angry"),
        ("like", "Like"),
        ("লাভ", "Love"),
        ("ভালোবাসা", "Love"),
        ("কেয়ার", "Care"),
        ("কেয়ার", "Care"),
        ("হাহা", "Haha"),
        ("ওয়াও", "Wow"),
        ("ওয়াও", "Wow"),
        ("স্যাড", "Sad"),
        ("অ্যাংরি", "Angry"),
        ("লাইক", "Like"),
    ):
        if key in low:
            return canonical
    return ""


def format_reaction_with_emoji(reaction_type: Optional[str]) -> str:
    norm = normalize_reaction_type(reaction_type)
    if not norm:
        return ""
    return REACTION_EMOJI_MAP.get(norm.lower(), norm)


@dataclass
class ContestParticipant:
    name: str
    normalized_key: str
    profile_url: Optional[str] = None
    avatar_hash: Optional[str] = None
    avatar_path: Optional[str] = None
    liked: bool = False
    commented: bool = False
    shared: bool = False
    reaction_types: List[str] = field(default_factory=list)
    comment_texts: List[str] = field(default_factory=list)
    share_contents: List[str] = field(default_factory=list)
    shared_post_urls: List[str] = field(default_factory=list)
    first_seen_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    scroll_index: int = 0
    serial_number: Optional[int] = None
    disambiguator: str = ""

    @property
    def serial_code(self) -> str:
        if self.serial_number is not None:
            return f"#{self.serial_number:04d}"
        return "-"

    @property
    def display_name(self) -> str:
        if self.disambiguator:
            return f"{self.name} ({self.disambiguator})"
        return self.name

    @property
    def actions_completed(self) -> int:
        return int(self.liked) + int(self.commented) + int(self.shared)

    @property
    def is_eligible(self) -> bool:
        return self.liked and self.commented and self.shared

    @property
    def missing_actions(self) -> List[str]:
        missing = []
        if not self.liked:
            missing.append("Like")
        if not self.commented:
            missing.append("Comment")
        if not self.shared:
            missing.append("Share")
        return missing

    @property
    def status_label(self) -> str:
        if self.is_eligible:
            return "ELIGIBLE (3/3)"
        missing_str = ", ".join(self.missing_actions)
        return f"INCOMPLETE ({self.actions_completed}/3 - Missing: {missing_str})"

    @property
    def combined_reactions(self) -> str:
        if self.reaction_types:
            return " | ".join(self.reaction_types)
        return "Reaction" if self.liked else ""

    @property
    def reaction_badge(self) -> str:
        if not self.liked:
            return "❌ Reaction"
        if self.reaction_types:
            badges = [format_reaction_with_emoji(r) or r for r in self.reaction_types if r]
            if badges:
                return f"✅ {' / '.join(badges)}"
        return "✅ Reaction"

    @property
    def combined_notes(self) -> str:
        parts = []
        if self.reaction_types:
            parts.append(f"Reaction: {' | '.join(self.reaction_types)}")
        if self.comment_texts:
            parts.append(f"Comment ({len(self.comment_texts)}): {' | '.join(self.comment_texts)}")
        if self.share_contents:
            parts.append(f"Share ({len(self.share_contents)}): {' | '.join(self.share_contents)}")
        return " ; ".join(parts)

    @property
    def combined_comments(self) -> str:
        return " | ".join(self.comment_texts)

    @property
    def combined_share_captions(self) -> str:
        return " | ".join(self.share_contents)

    @property
    def primary_shared_post_url(self) -> str:
        return self.shared_post_urls[0] if self.shared_post_urls else ""

    def to_dict(self):
        return {
            "serial_code": self.serial_code,
            "name": self.display_name,
            "raw_name": self.name,
            "profile_url": self.profile_url or "",
            "shared_post_url": " | ".join(self.shared_post_urls),
            "avatar_hash": self.avatar_hash or "",
            "avatar_path": self.avatar_path or "",
            "liked": self.liked,
            "reaction_type": self.combined_reactions,
            "commented": self.commented,
            "shared": self.shared,
            "actions_completed": f"{self.actions_completed}/3",
            "is_eligible": self.is_eligible,
            "status": self.status_label,
            "comments_count": len(self.comment_texts),
            "comments": " | ".join(self.comment_texts),
            "share_content": " | ".join(self.share_contents),
            "first_seen_at": self.first_seen_at,
        }

