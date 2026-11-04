import logging
from typing import Set, List
from app.models.share_profile import ShareProfile
from app.utils.text_normalizer import normalize_text
from app.utils.url_normalizer import normalize_url

logger = logging.getLogger(__name__)

class Deduplicator:
    def __init__(self):
        # We store keys to easily check if we've seen something
        self.seen_urls: Set[str] = set()
        self.seen_names: Set[str] = set()
        
    def generate_key(self, profile: ShareProfile) -> str:
        """
        Priority:
        1. profile URL
        2. share URL
        3. normalized name (fallback)
        """
        if profile.profile_url:
            return f"url:{normalize_url(profile.profile_url)}"
        if profile.share_url:
            return f"share:{normalize_url(profile.share_url)}"
            
        norm_name = normalize_text(profile.name)
        return f"name:{norm_name}"

    def is_duplicate(self, profile: ShareProfile) -> bool:
        """
        Checks if the profile is already seen based on URL or Name alone.
        Note: The prompt says "Do NOT merge two people solely because their names are identical if other identifying information differs."
        So if URL is different, they are different. If URL is missing, fallback to name.
        """
        if profile.profile_url:
            n_url = normalize_url(profile.profile_url)
            if n_url in self.seen_urls:
                return True
        
        if not profile.profile_url and not profile.share_url:
            n_name = normalize_text(profile.name)
            if n_name in self.seen_names:
                return True
                
        return False
        
    def add(self, profile: ShareProfile):
        if profile.profile_url:
            self.seen_urls.add(normalize_url(profile.profile_url))
        if not profile.profile_url and not profile.share_url:
            self.seen_names.add(normalize_text(profile.name))
            
    def load_existing(self, profiles: List[ShareProfile]):
        for p in profiles:
            self.add(p)
