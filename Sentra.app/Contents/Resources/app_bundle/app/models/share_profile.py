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
    comment_texts: List[str] = field(default_factory=list)
    share_contents: List[str] = field(default_factory=list)
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
    def combined_notes(self) -> str:
        parts = []
        if self.comment_texts:
            parts.append(f"Comment ({len(self.comment_texts)}): {' | '.join(self.comment_texts)}")
        if self.share_contents:
            parts.append(f"Share ({len(self.share_contents)}): {' | '.join(self.share_contents)}")
        return " ; ".join(parts)

    def to_dict(self):
        return {
            "serial_code": self.serial_code,
            "name": self.display_name,
            "raw_name": self.name,
            "profile_url": self.profile_url or "",
            "avatar_hash": self.avatar_hash or "",
            "avatar_path": self.avatar_path or "",
            "liked": self.liked,
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

