import re
import unicodedata

def normalize_text(text: str) -> str:
    if not text:
        return ""
    
    # Trim whitespace
    text = text.strip()
    
    # Collapse repeated spaces
    text = re.sub(r'\s+', ' ', text)
    
    # Normalize unicode to NFKC (compat normalization)
    # Be careful not to destroy Bangla characters
    # NFKC normalizes wide characters, combining marks appropriately.
    text = unicodedata.normalize('NFKC', text)
    
    return text
