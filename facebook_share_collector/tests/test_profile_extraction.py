import pytest
from app.automation.profile_extractor import ProfileExtractor

# Mock XML simulating Facebook Share list
MOCK_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy index="0" class="hierarchy" rotation="0" width="1080" height="2400">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.facebook.katana" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[0,0][1080,2400]">
    <node index="1" text="" resource-id="" class="androidx.recyclerview.widget.RecyclerView" package="com.facebook.katana" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="true" focused="false" scrollable="true" long-clickable="false" password="false" selected="false" bounds="[0,200][1080,2400]">
      <!-- Profile 1: Normal profile -->
      <node index="0" text="Rahim Ahmed" resource-id="" class="android.widget.TextView" package="com.facebook.katana" content-desc="" checkable="false" checked="false" clickable="true" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[200,300][800,400]" />
      
      <!-- Profile 2: Hidden URL in content desc -->
      <node index="1" text="" resource-id="" class="android.view.ViewGroup" package="com.facebook.katana" content-desc="John Doe, https://facebook.com/john.doe" checkable="false" checked="false" clickable="true" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[200,500][800,600]" />
      
      <!-- UI Element to ignore -->
      <node index="2" text="Share" resource-id="" class="android.widget.Button" package="com.facebook.katana" content-desc="" checkable="false" checked="false" clickable="true" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[200,700][800,800]" />
    </node>
  </node>
</hierarchy>
"""

def test_extract_profiles():
    extractor = ProfileExtractor(min_confidence=0.6)
    profiles = extractor.extract(MOCK_XML, session_id="test_session")
    
    assert len(profiles) == 2
    
    names = [p.name for p in profiles]
    assert "Rahim Ahmed" in names
    
    # Second profile has hidden URL in content-desc
    p2 = next(p for p in profiles if "John Doe" in p.name)
    assert p2.profile_url == "John Doe, https://facebook.com/john.doe"
