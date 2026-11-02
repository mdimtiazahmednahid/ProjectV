import logging
from dataclasses import dataclass
from app.automation.ui_inspector import UIInspector

logger = logging.getLogger(__name__)

@dataclass
class ShareListDetectionResult:
    detected: bool
    confidence: float

class ShareListDetector:
    # Multiple languages supported
    SHARE_TERMS = [
        "Shares", "Share", "Shared", "View shares", "See shares", 
        "People who shared", "Shared by", 
        "শেয়ার", "শেয়ার", "শেয়ার দেখুন", "শেয়ার দেখুন"
    ]

    def __init__(self):
        pass
        
    def detect(self, xml_source: str) -> ShareListDetectionResult:
        if not xml_source:
            return ShareListDetectionResult(False, 0.0)
            
        nodes = UIInspector.parse_xml_to_nodes(xml_source)
        if not nodes:
            return ShareListDetectionResult(False, 0.0)

        score = 0.0
        
        # Heuristic 1: Look for share-related text at the top or in typical header nodes
        for node in nodes:
            text = node.get("text", "")
            content_desc = node.get("content-desc", "")
            
            for term in self.SHARE_TERMS:
                if term.lower() == text.lower() or term.lower() == content_desc.lower():
                    score += 0.6
                    break
                elif term.lower() in text.lower() or term.lower() in content_desc.lower():
                    score += 0.3
                    break
        
        # Heuristic 2: Check for list-like structure (e.g. RecyclerView, ListView, ScrollView)
        scrollable_found = False
        for node in nodes:
            if node.get("scrollable"):
                scrollable_found = True
                break
                
        if scrollable_found:
            score += 0.3
            
        # Determine confidence
        confidence = min(score, 1.0)
        detected = confidence >= 0.6
        
        if detected:
            logger.info(f"Share list detected with confidence: {confidence}")
        
        return ShareListDetectionResult(detected, confidence)
