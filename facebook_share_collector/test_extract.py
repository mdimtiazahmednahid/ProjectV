import sys
import os

# Add project to path
sys.path.append(os.path.abspath("facebook_share_collector"))

from app.automation.profile_extractor import ProfileExtractor

def run():
    with open("/tmp/window_dump.xml", "r", encoding="utf-8") as f:
        xml = f.read()

    extractor = ProfileExtractor(min_confidence=0.5)
    profiles = extractor.extract(xml, session_id="test")

    print(f"Found {len(profiles)} profiles:")
    for i, p in enumerate(profiles):
        print(f"{i+1}. Name: {p.name}, Profile URL: {p.profile_url}, Confidence: {p.confidence}")

if __name__ == "__main__":
    run()
