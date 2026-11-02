from dataclasses import dataclass, field
import datetime
import uuid
from typing import Optional

@dataclass
class CollectionSession:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_time: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    end_time: Optional[str] = None
    status: str = "IN_PROGRESS"
    total_profiles: int = 0
    total_scrolls: int = 0

    def to_dict(self):
        return {
            "id": self.id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
            "total_profiles": self.total_profiles,
            "total_scrolls": self.total_scrolls
        }
