import re
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs

FB_ASSET_FILENAME_RE = re.compile(r"/(\d+_\d+_\d+_[a-z]\.(?:jpg|png|webp))", re.IGNORECASE)


def normalize_url(url: str) -> str:
    if not url:
        return ""

    url = url.strip()
    if url.startswith("/"):
        url = "https://www.facebook.com" + url
    elif not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc in ("m.facebook.com", "mbasic.facebook.com", "web.facebook.com", "facebook.com", "touch.facebook.com"):
            netloc = "www.facebook.com"

        path = parsed.path or ""
        if path.endswith("/") and len(path) > 1:
            path = path.rstrip("/")

        qs = parse_qs(parsed.query or "")
        lower_path = path.lower()

        # 1. /profile.php?id=<uid> or /user.php?id=<uid>
        if lower_path in ("/profile.php", "/user.php", "/permalink.php", "/story.php"):
            if "id" in qs and qs["id"] and qs["id"][0].isdigit():
                return f"https://{netloc}/profile.php?id={qs['id'][0]}"
            return urlunparse(("https", netloc, path, "", "", ""))

        # 2. /people/<Name>/<uid_or_pfbid> -> if numeric uid, canonicalize to /profile.php?id=<uid>
        m_people = re.match(r"^/people/([^/]+)/([^/?#]+)", path, re.IGNORECASE)
        if m_people:
            token = m_people.group(2)
            if token.isdigit():
                return f"https://{netloc}/profile.php?id={token}"
            return f"https://{netloc}/people/{m_people.group(1)}/{token}"

        # 3. /groups/<gid>/user/<uid>
        m_group_user = re.match(r"^/groups/[^/]+/user/([^/?#]+)", path, re.IGNORECASE)
        if m_group_user:
            uid = m_group_user.group(1)
            if uid.isdigit():
                return f"https://{netloc}/profile.php?id={uid}"
            return f"https://{netloc}/{uid}"

        # 4. Pure numeric path /100078091213712 -> /profile.php?id=100078091213712
        segments = [seg for seg in path.split("/") if seg]
        if len(segments) == 1 and segments[0].isdigit() and len(segments[0]) >= 5:
            return f"https://{netloc}/profile.php?id={segments[0]}"

        # 5. /<username>/posts/... or /<username>/videos/... or /<username>/about -> /<username>
        if len(segments) >= 2 and segments[0].lower() not in ("people", "groups", "pages", "profile.php"):
            sub = segments[1].lower()
            if sub in ("posts", "videos", "about", "friends", "photos", "reels", "map", "mentions", "followers", "following"):
                if segments[0].isdigit():
                    return f"https://{netloc}/profile.php?id={segments[0]}"
                return f"https://{netloc}/{segments[0]}"

        return urlunparse(("https", netloc, path, "", "", ""))
    except Exception:
        return url


def extract_canonical_identity_key(url: Optional[str]) -> Optional[str]:
    """
    Extracts an immutable canonical Facebook identity token from any profile URL variant:
      - 'uid:100078091213712' for /profile.php?id=..., /people/Name/1000..., /groups/.../user/1000..., /1000...
      - 'pfbid:pfbid02xyz...' for /people/Name/pfbid02xyz... (immune to display-name slug changes across days!)
      - 'user:username' for https://www.facebook.com/<username> (case-insensitive)
    """
    if not url:
        return None
    norm = normalize_url(url)
    if not norm:
        return None
    try:
        parsed = urlparse(norm)
        path = (parsed.path or "").rstrip("/")
        qs = parse_qs(parsed.query or "")
        if path.lower() == "/profile.php" and "id" in qs and qs["id"]:
            return f"uid:{qs['id'][0].strip()}"
        m_people = re.match(r"^/people/[^/]+/([^/?#]+)", path, re.IGNORECASE)
        if m_people:
            token = m_people.group(1).strip()
            if token.isdigit():
                return f"uid:{token}"
            return f"pfbid:{token.lower()}"
        segments = [seg for seg in path.split("/") if seg]
        if len(segments) == 1:
            tok = segments[0].strip()
            if tok.isdigit():
                return f"uid:{tok}"
            return f"user:{tok.lower()}"
        return norm.lower()
    except Exception:
        return norm.lower()


def extract_avatar_asset_id(avatar_url: Optional[str]) -> Optional[str]:
    """
    Extracts the immutable Facebook image asset filename (e.g. '432109876_123456789_987654321_n.jpg')
    from a Facebook CDN avatar URL so daily scrapes recognize the exact same avatar image even after
    signed CDN query parameters (?oh=...&oe=...) rotate on subsequent days.
    """
    if not avatar_url or not isinstance(avatar_url, str):
        return None
    m = FB_ASSET_FILENAME_RE.search(avatar_url)
    if m:
        return m.group(1).lower()
    return None

