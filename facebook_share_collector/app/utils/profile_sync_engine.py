import logging
import urllib.request
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
from app.models.share_profile import ShareProfile
from app.utils.contest_validator import IncrementalContestAggregator
from app.utils.avatar_fingerprint import AvatarFingerprinter, are_avatars_matching, hamming_distance
from app.utils.url_normalizer import normalize_url, extract_canonical_identity_key

logger = logging.getLogger(__name__)


@dataclass
class SyncCandidateRow:
    row_id: str
    name: str
    normalized_name: str
    liked: bool = False
    commented: bool = False
    shared: bool = False
    phone_actions: Set[str] = field(default_factory=set)
    web_actions: Set[str] = field(default_factory=set)
    avatar_path: Optional[str] = None
    phone_avatar_hash: Optional[str] = None
    web_avatar_hash: Optional[str] = None
    web_avatar_url: Optional[str] = None
    profile_url: Optional[str] = None
    sync_status: str = "PHONE_ONLY_NEEDS_URL"
    confidence_pct: int = 50
    hamming_dist: Optional[int] = None
    comment_preview: str = ""
    source_profiles: List[ShareProfile] = field(default_factory=list)

    @property
    def is_eligible(self) -> bool:
        return self.liked and self.commented and self.shared

    @property
    def actions_score_str(self) -> str:
        score = int(self.liked) + int(self.commented) + int(self.shared)
        return f"{score}/3 {'✅' if score == 3 else ''}".strip()

    @property
    def source_badge(self) -> str:
        has_phone = bool(self.phone_actions)
        has_web = bool(self.web_actions)
        if has_phone and has_web:
            return "📱+🌐 Hybrid"
        if has_phone:
            return "📱 Phone"
        if has_web:
            return "🌐 Web"
        return "Unknown"

    @property
    def status_display(self) -> str:
        if self.sync_status == "VERIFIED_3_LAYER":
            dist_note = f" [dHash Δ={self.hamming_dist}]" if self.hamming_dist is not None else ""
            return f"✅ 3-Layer Verified (Name + Avatar + URL){dist_note} ({self.confidence_pct}%)"
        if self.sync_status == "VERIFIED_UNIQUE_NAME":
            return f"✅ 2-Layer Synced (Exact Unique Name Phone↔Web) ({self.confidence_pct}%)"
        if self.sync_status == "VERIFIED_WEB_DIRECT":
            return f"✅ Web Direct URL ({self.confidence_pct}%)"
        if self.sync_status == "NEEDS_AVATAR_DISAMBIGUATION":
            return "🟡 Same-Name Collision (Click 'Run Batch Sync' for Avatar Match)"
        return "⏳ Phone Only (Needs Web Sync or Manual URL)"


class ProfileSyncEngine:
    """
    Multi-Layer Hybrid Profile Sync Engine (Phone ↔ Web):
    Matches Phone records (which have Shares/Comments/Likes + cropped Avatar pHash, but no URL)
    with Web records (which have canonical Profile URLs + Web Avatar URLs + Names)
    using a 3-layer validation pipeline:
      Layer 1: Exact Canonical URL Identity
      Layer 2: Perceptual Avatar Image Hash (`dHash` Hamming distance) for Same-Name Disambiguation
      Layer 3: Exact Normalized Name + Action Checklist Merging
    Designed to run in small, non-blocking batches so 10,000–100,000+ rows remain fast and responsive.
    """

    def __init__(self, avatar_dir: str = "data/avatars"):
        self.fingerprinter = AvatarFingerprinter(avatar_dir=avatar_dir)
        self._url_hash_cache: Dict[str, Tuple[Optional[str], Optional[str]]] = {}

    def fetch_and_hash_web_avatar(self, avatar_url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Downloads a Web avatar thumbnail (cached in memory & disk) and returns `(dhash_hex, local_path)`.
        """
        if not avatar_url or not avatar_url.startswith("http"):
            return None, None
        if avatar_url in self._url_hash_cache:
            return self._url_hash_cache[avatar_url]

        try:
            req = urllib.request.Request(
                avatar_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    )
                },
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                img_bytes = resp.read()
            dhash, path = self.fingerprinter.hash_image_bytes(img_bytes)
            self._url_hash_cache[avatar_url] = (dhash, path)
            return dhash, path
        except Exception as e:
            logger.debug(f"Web avatar download skipped for {avatar_url[:50]}: {e}")
            self._url_hash_cache[avatar_url] = (None, None)
            return None, None

    def build_sync_checklist(self, profiles: List[ShareProfile]) -> List[SyncCandidateRow]:
        """
        Builds the structured Pre-Sync / Post-Sync Checklist from raw Phone + Web `ShareProfile`s.
        Fast O(N) pass that does NOT perform network I/O (network avatar hashing happens in chunked batches).
        """
        by_norm_name: Dict[str, List[ShareProfile]] = {}
        id_key_to_primary_name: Dict[str, str] = {}
        for p in profiles:
            clean_name = IncrementalContestAggregator._clean_author_name(p.name or "")
            if IncrementalContestAggregator.is_ui_noise_name(clean_name, p.profile_url):
                continue
            norm_name = clean_name.lower()
            if not norm_name:
                continue
            id_key = extract_canonical_identity_key(p.profile_url) if p.profile_url else None
            if id_key:
                if id_key in id_key_to_primary_name:
                    norm_name = id_key_to_primary_name[id_key]
                else:
                    id_key_to_primary_name[id_key] = norm_name
            by_norm_name.setdefault(norm_name, []).append(p)

        rows: List[SyncCandidateRow] = []

        for norm_name, group in by_norm_name.items():
            # Separate into sub-clusters by distinct known URL or distinct Phone avatar hash
            web_clusters: Dict[str, List[ShareProfile]] = {}
            phone_clusters: List[List[ShareProfile]] = []

            for p in group:
                if p.avatar_hash:
                    clean_h = IncrementalContestAggregator._sanitize_avatar_hash(p.avatar_hash)
                    if not clean_h:
                        p.avatar_hash = None
                        p.avatar_path = None
                clean_u = normalize_url(p.profile_url) if p.profile_url else None
                if clean_u:
                    u_key = extract_canonical_identity_key(clean_u) or clean_u.lower()
                    web_clusters.setdefault(u_key, []).append(p)
                else:
                    # Phone or URL-less record: cluster using identical rules to IncrementalContestAggregator
                    placed = False
                    p_act = (getattr(p, "action_type", "share") or "share").lower().strip()
                    p_scroll = getattr(p, "scroll_index", 0)
                    for pc in phone_clusters:
                        hashes_in_pc = [x.avatar_hash for x in pc if x.avatar_hash]
                        if not p.avatar_hash or not hashes_in_pc:
                            pc.append(p)
                            placed = True
                            break
                        actions_in_pc = {
                            (getattr(x, "action_type", "share") or "share").lower().strip()
                            for x in pc
                        }
                        if any(
                            (getattr(x, "action_type", "share") or "share").lower().strip() == p_act
                            and (
                                1 <= abs(p_scroll - getattr(x, "scroll_index", -999)) <= 2
                                or (p_scroll >= 1 and p_scroll == getattr(x, "scroll_index", -999))
                            )
                            for x in pc
                        ):
                            pc.append(p)
                            placed = True
                            break
                        threshold = 24 if (p_act not in actions_in_pc and len(phone_clusters) == 1 and not web_clusters) else 20
                        if any(are_avatars_matching(p.avatar_hash, kh, threshold=threshold) for kh in hashes_in_pc):
                            pc.append(p)
                            placed = True
                            break
                    if not placed:
                        phone_clusters.append([p])

            # Case 1: Only 1 Web URL for this name and <= 1 Phone cluster -> Unique Identity across Phone & Web!
            if len(web_clusters) == 1 and len(phone_clusters) <= 1:
                u_key, w_list = next(iter(web_clusters.items()))
                p_list = phone_clusters[0] if phone_clusters else []
                combined = w_list + p_list
                row = self._create_row_from_cluster(
                    row_id=f"{norm_name}|{u_key}",
                    norm_name=norm_name,
                    cluster=combined,
                )
                if p_list and w_list:
                    if row.phone_avatar_hash and row.web_avatar_hash:
                        dist = hamming_distance(row.phone_avatar_hash, row.web_avatar_hash)
                        row.hamming_dist = dist
                        row.sync_status = "VERIFIED_3_LAYER"
                        row.confidence_pct = 100
                    elif row.phone_avatar_hash and row.profile_url:
                        row.sync_status = "VERIFIED_3_LAYER"
                        row.confidence_pct = 100
                    else:
                        row.sync_status = "VERIFIED_UNIQUE_NAME"
                        row.confidence_pct = 98
                else:
                    row.sync_status = "VERIFIED_WEB_DIRECT"
                    row.confidence_pct = 100
                rows.append(row)
                continue

            # Case 2: Multiple clusters share the same name (Same-Name Collision!) or Phone-Only clusters
            matched_web_keys: Set[str] = set()
            collision_rows: List[SyncCandidateRow] = []

            for idx, p_list in enumerate(phone_clusters):
                p_hash = next((x.avatar_hash for x in p_list if x.avatar_hash), None)
                p_texts = {
                    IncrementalContestAggregator._clean_comment_text(x.content, x.name or "").lower()
                    for x in p_list
                    if x.content and IncrementalContestAggregator._clean_comment_text(x.content, x.name or "")
                }

                best_u_key = None
                best_dist = 64

                # Layer 2A: Exact Comment/Share Text Fingerprint Bridge between Phone & Web
                if p_texts and web_clusters:
                    text_matching_keys = []
                    for u_key, w_list in web_clusters.items():
                        if u_key in matched_web_keys:
                            continue
                        w_texts = {
                            IncrementalContestAggregator._clean_comment_text(x.content, x.name or "").lower()
                            for x in w_list
                            if x.content and IncrementalContestAggregator._clean_comment_text(x.content, x.name or "")
                        }
                        if p_texts & w_texts:
                            text_matching_keys.append(u_key)
                    if len(text_matching_keys) == 1:
                        best_u_key = text_matching_keys[0]
                        best_dist = 0

                # Layer 2B: 64-bit Perceptual Avatar dHash Match
                if not best_u_key and p_hash and web_clusters:
                    for u_key, w_list in web_clusters.items():
                        if u_key in matched_web_keys:
                            continue
                        w_hash = next((x.avatar_hash for x in w_list if x.avatar_hash), None)
                        if w_hash:
                            d = hamming_distance(p_hash, w_hash)
                            if d < best_dist:
                                best_dist = d
                                best_u_key = u_key

                if best_u_key and best_dist <= 16:
                    matched_web_keys.add(best_u_key)
                    combined = web_clusters[best_u_key] + p_list
                    row = self._create_row_from_cluster(
                        row_id=f"{norm_name}|{best_u_key}",
                        norm_name=norm_name,
                        cluster=combined,
                    )
                    row.hamming_dist = best_dist
                    row.sync_status = "VERIFIED_3_LAYER"
                    row.confidence_pct = 100
                    collision_rows.append(row)
                else:
                    row = self._create_row_from_cluster(
                        row_id=f"{norm_name}|phone_{idx}",
                        norm_name=norm_name,
                        cluster=p_list,
                    )
                    if web_clusters:
                        row.sync_status = "NEEDS_AVATAR_DISAMBIGUATION"
                        row.confidence_pct = 70
                    else:
                        row.sync_status = "PHONE_ONLY_NEEDS_URL"
                        row.confidence_pct = 50
                    collision_rows.append(row)

            # Add any remaining unmatched Web clusters
            for u_key, w_list in web_clusters.items():
                if u_key in matched_web_keys:
                    continue
                row = self._create_row_from_cluster(
                    row_id=f"{norm_name}|{u_key}",
                    norm_name=norm_name,
                    cluster=w_list,
                )
                row.sync_status = "VERIFIED_WEB_DIRECT"
                row.confidence_pct = 100
                collision_rows.append(row)

            rows.extend(collision_rows)

        # Sort: Eligible (3/3) first, then by actions score descending, then by name
        rows.sort(
            key=lambda r: (
                not r.is_eligible,
                -(int(r.liked) + int(r.commented) + int(r.shared)),
                r.normalized_name,
            )
        )
        return rows

    @staticmethod
    def _create_row_from_cluster(
        row_id: str,
        norm_name: str,
        cluster: List[ShareProfile],
    ) -> SyncCandidateRow:
        display_name = IncrementalContestAggregator._clean_author_name(cluster[0].name or "")
        liked = False
        commented = False
        shared = False
        phone_actions: Set[str] = set()
        web_actions: Set[str] = set()
        avatar_path = None
        phone_avatar_hash = None
        web_avatar_hash = None
        web_avatar_url = None
        profile_url = None
        comments: List[str] = []

        for p in cluster:
            act = (p.action_type or "share").lower()
            is_web = "browser" in (p.source or "").lower()
            if act == "like":
                liked = True
            elif act == "comment":
                commented = True
            else:
                shared = True

            if is_web:
                web_actions.add(act)
            else:
                phone_actions.add(act)

            if p.profile_url and not profile_url:
                profile_url = normalize_url(p.profile_url)

            if p.avatar_path and not avatar_path:
                avatar_path = p.avatar_path

            if is_web:
                if p.avatar_hash and not web_avatar_hash:
                    web_avatar_hash = p.avatar_hash
                if p.share_url and p.share_url.startswith("http") and not web_avatar_url:
                    web_avatar_url = p.share_url
            else:
                if p.avatar_hash and not phone_avatar_hash:
                    phone_avatar_hash = p.avatar_hash

            if p.content and p.content not in comments:
                comments.append(p.content)

        return SyncCandidateRow(
            row_id=row_id,
            name=display_name,
            normalized_name=norm_name,
            liked=liked,
            commented=commented,
            shared=shared,
            phone_actions=phone_actions,
            web_actions=web_actions,
            avatar_path=avatar_path,
            phone_avatar_hash=phone_avatar_hash,
            web_avatar_hash=web_avatar_hash,
            web_avatar_url=web_avatar_url,
            profile_url=profile_url,
            comment_preview=" | ".join(comments)[:120],
            source_profiles=list(cluster),
        )

    def apply_synced_urls_to_profiles(self, rows: List[SyncCandidateRow]) -> int:
        """
        Propagates resolved `profile_url`, `avatar_hash`, and `avatar_path` from verified
        `SyncCandidateRow`s onto their underlying `ShareProfile` objects so the main
        Contest Validation table and database immediately reflect all matched URLs.
        Returns the number of `ShareProfile` records updated.
        """
        updated_count = 0
        for row in rows:
            if not row.profile_url:
                continue
            best_hash = row.phone_avatar_hash or row.web_avatar_hash
            for p in row.source_profiles:
                changed = False
                if not p.profile_url:
                    p.profile_url = row.profile_url
                    changed = True
                if best_hash and not p.avatar_hash:
                    p.avatar_hash = best_hash
                    changed = True
                if row.avatar_path and not p.avatar_path:
                    p.avatar_path = row.avatar_path
                    changed = True
                if changed:
                    updated_count += 1
        return updated_count
