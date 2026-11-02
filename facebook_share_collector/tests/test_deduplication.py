import pytest
from app.utils.deduplicator import Deduplicator
from app.models.share_profile import ShareProfile

def test_deduplicate_by_url():
    dedup = Deduplicator()
    
    p1 = ShareProfile(name="John Doe", profile_url="https://facebook.com/john", source="ui", confidence=0.9, session_id="1")
    p2 = ShareProfile(name="John Doe", profile_url="https://m.facebook.com/john", source="ui", confidence=0.9, session_id="1")
    
    assert not dedup.is_duplicate(p1)
    dedup.add(p1)
    assert dedup.is_duplicate(p2) # URLs normalize to same string

def test_same_name_different_url():
    dedup = Deduplicator()
    
    p1 = ShareProfile(name="John Doe", profile_url="https://facebook.com/john1", source="ui", confidence=0.9, session_id="1")
    p2 = ShareProfile(name="John Doe", profile_url="https://facebook.com/john2", source="ui", confidence=0.9, session_id="1")
    
    assert not dedup.is_duplicate(p1)
    dedup.add(p1)
    assert not dedup.is_duplicate(p2) # Same name, different URL -> different person

def test_fallback_to_name():
    dedup = Deduplicator()
    
    p1 = ShareProfile(name="John Doe", profile_url=None, source="ui", confidence=0.9, session_id="1")
    p2 = ShareProfile(name="John Doe ", profile_url=None, source="ui", confidence=0.9, session_id="1")
    
    assert not dedup.is_duplicate(p1)
    dedup.add(p1)
    assert dedup.is_duplicate(p2) # Both lack URL, name normalizes to same
