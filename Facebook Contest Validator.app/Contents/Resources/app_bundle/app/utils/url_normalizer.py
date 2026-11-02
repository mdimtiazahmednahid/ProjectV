import re
from urllib.parse import urlparse, urlunparse, parse_qs

def normalize_url(url: str) -> str:
    if not url:
        return ""
        
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        
    try:
        parsed = urlparse(url)
        # Force https and normalize netloc (e.g., m.facebook.com to www.facebook.com)
        netloc = parsed.netloc.lower()
        if netloc in ('m.facebook.com', 'mbasic.facebook.com', 'web.facebook.com', 'facebook.com'):
            netloc = 'www.facebook.com'
            
        path = parsed.path
        if path.endswith('/') and len(path) > 1:
            path = path[:-1]

        # Preserve ?id=... for profile.php?id=<uid>, strip all tracking params
        query = ''
        if path.lower() == '/profile.php' and parsed.query:
            qs = parse_qs(parsed.query)
            if 'id' in qs and qs['id']:
                query = f"id={qs['id'][0]}"
            
        return urlunparse(('https', netloc, path, '', query, ''))
    except Exception:
        return url
