import os
import tempfile
from app.models.share_profile import ShareProfile
from app.utils.contest_validator import ContestValidator
from app.automation.profile_extractor import ProfileExtractor
from app.automation.browser_dom_extractor import (
    clean_facebook_profile_url,
    BrowserDOMExtractor,
    BackgroundHTMLExtractor,
)
from app.exporters.lottery_print_exporter import LotteryPrintExporter


def test_three_action_contest_validation():
    profiles = [
        # Alice completes all 3 actions (Like + Comment + Share)
        ShareProfile(name="Alice Rahman", source="ui", confidence=0.9, session_id="s1", action_type="like"),
        ShareProfile(name="Alice Rahman ", source="ui", confidence=0.9, session_id="s1", action_type="comment", content="Awesome work!"),
        ShareProfile(name="Alice Rahman", source="ui", confidence=0.9, session_id="s1", action_type="share", content="Must watch"),

        # Bob only likes and comments (missing share -> ineligible)
        ShareProfile(name="Bob Karim", source="ui", confidence=0.9, session_id="s1", action_type="like"),
        ShareProfile(name="Bob Karim", source="ui", confidence=0.9, session_id="s1", action_type="comment", content="Great post"),

        # Charlie only shares (missing like & comment -> ineligible)
        ShareProfile(name="Charlie Hasan", source="ui", confidence=0.9, session_id="s1", action_type="share"),
    ]

    participants = ContestValidator.validate_participants(profiles)
    counts = ContestValidator.compute_counts(profiles)

    assert counts["total_participants"] == 3
    assert counts["likes"] == 2
    assert counts["comments"] == 2
    assert counts["shares"] == 2
    assert counts["eligible"] == 1

    # Alice should be first, eligible, and assigned Serial #0001
    alice = participants[0]
    assert alice.name == "Alice Rahman"
    assert alice.serial_code == "#0001"
    assert alice.liked is True
    assert alice.commented is True
    assert alice.shared is True
    assert alice.actions_completed == 3
    assert alice.is_eligible is True
    assert alice.status_label == "ELIGIBLE (3/3)"
    assert "Awesome work!" in alice.comment_texts
    assert "Must watch" in alice.share_contents

    # Bob has 2/3 actions and no lottery serial number
    bob = next(p for p in participants if p.name == "Bob Karim")
    assert bob.is_eligible is False
    assert bob.serial_code == "-"
    assert bob.actions_completed == 2
    assert bob.missing_actions == ["Share"]


def test_same_name_disambiguation_by_avatar_and_url():
    """
    Verifies that two different users with the exact same name ('Md Rahim')
    who have different profile photos (avatar_hash) or URLs are NEVER merged into a fake winner,
    while the same user with a matching avatar hash (Hamming distance <= 8) IS matched across all 3 actions.
    """
    profiles = [
        # Md Rahim #1 (Avatar hash all 0s) only Likes and Comments
        ShareProfile(name="Md Rahim", source="ui", confidence=0.9, session_id="s1", action_type="like", avatar_hash="0000000000000000"),
        ShareProfile(name="Md Rahim", source="ui", confidence=0.9, session_id="s1", action_type="comment", content="First Rahim comment", avatar_hash="0000000000000001"),

        # Md Rahim #2 (Completely different Avatar hash all Fs, non-adjacent scroll) only Shares
        ShareProfile(name="Md Rahim", source="ui", confidence=0.9, session_id="s1", action_type="share", content="Second Rahim share", avatar_hash="ffffffffffffffff", scroll_index=15),

        # Md Rahim #3 (Different URL, completes all 3 actions!)
        ShareProfile(name="Md Rahim", profile_url="https://facebook.com/rahim.three", source="ui", confidence=0.9, session_id="s1", action_type="like"),
        ShareProfile(name="Md Rahim", profile_url="https://facebook.com/rahim.three", source="ui", confidence=0.9, session_id="s1", action_type="comment", content="Done all 3!"),
        ShareProfile(name="Md Rahim", profile_url="https://facebook.com/rahim.three", source="ui", confidence=0.9, session_id="s1", action_type="share"),
    ]

    participants = ContestValidator.validate_participants(profiles)
    # Must be 3 distinct 'Md Rahim' participants!
    assert len(participants) == 3

    eligible_rahims = [p for p in participants if p.is_eligible]
    assert len(eligible_rahims) == 1
    assert eligible_rahims[0].profile_url == "https://facebook.com/rahim.three"
    assert eligible_rahims[0].serial_code == "#0001"
    assert "User #3" in eligible_rahims[0].display_name


def test_printable_lottery_tickets_export():
    long_comment = "থাই চিনা বাদাম (Peanuts) এটা অত্যন্ত পুষ্টিকর এবং সুস্বাদু খাবার যা সবাই পছন্দ করে!"
    profiles = [
        ShareProfile(name="Winner One", profile_url="https://www.facebook.com/profile.php?id=100078091213712", source="ui", confidence=0.9, session_id="s1", action_type="like", avatar_hash="1234567890abcdef"),
        ShareProfile(name="Winner One", profile_url="https://www.facebook.com/profile.php?id=100078091213712", source="ui", confidence=0.9, session_id="s1", action_type="comment", content=long_comment, avatar_hash="1234567890abcdef"),
        ShareProfile(name="Winner One", profile_url="https://www.facebook.com/profile.php?id=100078091213712", source="ui", confidence=0.9, session_id="s1", action_type="share", avatar_hash="1234567890abcdef"),
        # Second user missing Like (❌ Like · ✅ Comment · ✅ Share) so admin can print/show why they were disqualified
        ShareProfile(name="Disqualified NoLike", profile_url="https://www.facebook.com/nolike.user", source="ui", confidence=0.9, session_id="s1", action_type="comment", content="Answered but forgot to like"),
        ShareProfile(name="Disqualified NoLike", profile_url="https://www.facebook.com/nolike.user", source="ui", confidence=0.9, session_id="s1", action_type="share"),
    ]
    participants = ContestValidator.validate_participants(profiles)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_html = os.path.join(tmpdir, "lottery.html")
        ok = LotteryPrintExporter.export_printable_tickets(participants, out_html)
        assert ok is True
        assert os.path.isfile(out_html)
        html_text = open(out_html, encoding="utf-8").read()
        assert "#0001" in html_text
        assert "#0002" in html_text
        assert "Winner One" in html_text
        assert "Disqualified NoLike" in html_text
        # 1. Default solid border ("border-solid"), centered serial ID ("id-center"), 2-line default ("comment-lines-2"), and 3-column grid
        assert 'class="border-solid id-center actions-all-icons comment-lines-2"' in html_text
        assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in html_text
        assert "setTicketScope(this.value)" in html_text
        assert "setBorderStyle(this.value)" in html_text
        assert "setIdPosition(this.value)" in html_text
        assert "setCommentLines(this.value)" in html_text
        # 2. Action row stays on a single row (flex-wrap: nowrap; white-space: nowrap) and shows ✅ / ❌ status per action (Reaction · Comment · Share)
        assert "flex-wrap: nowrap" in html_text
        assert '<span class="act-icon">✅ </span>Reaction' in html_text
        assert '<span class="act-icon">❌ </span>Reaction' in html_text
        assert '<span class="act-icon">✅ </span>Comment' in html_text
        assert '<span class="act-icon">✅ </span>Share' in html_text
        assert 'data-status="qualified"' in html_text
        assert 'data-status="disqualified"' in html_text
        assert "DISQUALIFIED (No Reaction) ✗" in html_text
        assert "👍" not in html_text and "💬" not in html_text and "🔄" not in html_text
        # 3. Long comment has click-to-expand toggleCommentText(this) with full comment in data-full
        assert 'onclick="toggleCommentText(this)"' in html_text
        assert long_comment in html_text
        # 4. Profile link in footer is a clickable <a href="..." target="_blank"> redirecting to the profile
        assert 'href="https://www.facebook.com/profile.php?id=100078091213712"' in html_text
        assert 'target="_blank"' in html_text
        # 5. No unnecessary Part 1 heading clutter above the ticket grid
        assert "Part 1: Cut-Out Live Lottery Slips" not in html_text


def test_extract_likes_and_comments_xml():
    likes_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
      <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true">
        <node class="android.view.ViewGroup" content-desc="All 120" />
        <node class="android.view.ViewGroup">
          <node class="android.widget.Button" text="Nusrat Jahan" clickable="true" />
          <node class="android.widget.Button" text="Add friend" clickable="true" />
        </node>
        <node class="android.view.ViewGroup">
          <node class="android.view.ViewGroup" content-desc="Tanvir Hasan, Follow" clickable="true" />
        </node>
      </node>
    </hierarchy>
    """
    extractor = ProfileExtractor(min_confidence=0.6)
    like_profiles = extractor.extract(likes_xml, session_id="s1", action_type="like")
    like_names = [p.name for p in like_profiles]
    assert "Nusrat Jahan" in like_names
    assert "Tanvir Hasan" in like_names
    assert all(p.action_type == "like" for p in like_profiles)

    comments_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
      <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,240][1080,2280]">
        <!-- Cut-off fragment at top of screen (no profile picture node, has Reply to / comment button) -> MUST BE IGNORED -->
        <node class="android.view.ViewGroup">
          <node class="android.view.ViewGroup" text="💓💓" />
          <node class="android.widget.Button" content-desc="Reply to Asfia's comment" />
          <node class="android.widget.Button" content-desc="Like Asfia's comment button. Double tap and hold to show reaction tray." />
          <node class="android.widget.Button" content-desc="Downvote Asfia's comment" />
        </node>
        <!-- Real Facebook Android Comment #1 -->
        <node class="android.view.ViewGroup">
          <node class="android.widget.Button" content-desc="Mohammad Sharif profile picture, unseen story" bounds="[36,400][136,500]" />
          <node class="android.view.ViewGroup" text="Mohammad Sharif&#10;· Follow&#10;Ready&#10;See original" />
          <node class="android.widget.Button" content-desc="Reply to Mohammad's comment" />
          <node class="android.widget.Button" content-desc="Like Mohammad's comment button. Double tap and hold to show reaction tray." />
          <node class="android.widget.Button" content-desc="Downvote Mohammad's comment" />
        </node>
        <!-- Real Facebook Android Comment #2 -->
        <node class="android.view.ViewGroup">
          <node class="android.view.ViewGroup" text="Top fan" />
          <node class="android.widget.Button" content-desc="Nusrat Jahan profile picture" bounds="[36,600][136,700]" />
          <node class="android.widget.Button" text="Nusrat Jahan" clickable="true" />
          <node class="android.view.ViewGroup" text="Loved by author" />
          <node class="android.view.ViewGroup" text="Loved this project so much!" />
          <node class="android.view.ViewGroup" text="See original" />
          <node class="android.view.ViewGroup" text="2h" />
          <node class="android.widget.Button" text="Like" />
          <node class="android.widget.Button" text="Reply" />
        </node>
      </node>
    </hierarchy>
    """
    comment_profiles = extractor.extract(comments_xml, session_id="s1", action_type="comment")
    assert len(comment_profiles) == 2
    assert comment_profiles[0].name == "Mohammad Sharif"
    assert comment_profiles[0].content == "Ready"
    assert comment_profiles[1].name == "Nusrat Jahan"
    assert comment_profiles[1].action_type == "comment"
    assert comment_profiles[1].content == "Loved this project so much!"


def test_browser_dom_extractor_and_canonical_profile_links():
    # 1. URL cleaning & canonicalization
    assert clean_facebook_profile_url("https://www.facebook.com/nusrat.jahan.99?__cft__[0]=AZX&__tn__=-UC") == "https://www.facebook.com/nusrat.jahan.99"
    assert clean_facebook_profile_url("/profile.php?id=10008877665544&__cft__[0]=AZ") == "https://www.facebook.com/profile.php?id=10008877665544"
    assert clean_facebook_profile_url("/people/Md-Rahim/100011223344/") == "https://www.facebook.com/profile.php?id=100011223344"
    assert clean_facebook_profile_url("https://www.facebook.com/groups/12345/user/1000998877/") == "https://www.facebook.com/profile.php?id=1000998877"
    # Non-profile links must return None
    assert clean_facebook_profile_url("https://www.facebook.com/post/123?comment_id=987654") is None
    assert clean_facebook_profile_url("https://www.facebook.com/hashtag/contest") is None

    # 2. BrowserDOMExtractor parsing + 3-action cross-matching by exact profile_url
    likes = BrowserDOMExtractor.parse_dom_items(
        [{"name": "Md Rahim", "url": "https://www.facebook.com/profile.php?id=1000111", "content": ""}],
        session_id="s_web", action_type="like"
    )
    comments = BrowserDOMExtractor.parse_dom_items(
        [{"name": "Md Rahim", "url": "/profile.php?id=1000111&__cft__=1", "content": "Joined the lottery!"}],
        session_id="s_web", action_type="comment"
    )
    shares = BrowserDOMExtractor.parse_dom_items(
        [
            {"name": "Md Rahim", "url": "https://www.facebook.com/profile.php?id=1000111", "content": ""},
            {"name": "Md Rahim", "url": "https://www.facebook.com/profile.php?id=1000222", "content": ""},
        ],
        session_id="s_web", action_type="share"
    )

    participants = ContestValidator.validate_participants(likes + comments + shares)
    assert len(participants) == 2
    assert participants[0].is_eligible is True
    assert participants[0].serial_code == "#0001"
    assert participants[0].profile_url == "https://www.facebook.com/profile.php?id=1000111"
    assert participants[1].is_eligible is False
    assert participants[1].profile_url == "https://www.facebook.com/profile.php?id=1000222"


def test_background_html_extractor_dialog_comments_and_json():
    # 1. Likes dialog HTML (with avatar aria-label link + span text link, plus background feed link to ignore)
    likes_html = """
    <html><body>
      <a href="https://www.facebook.com/sidebar.friend">Sidebar Friend</a>
      <div role="dialog" aria-label="People who reacted">
        <div>
          <a href="https://www.facebook.com/hasmot.ali?__cft__[0]=AZ" aria-label="Hasmot Ali's profile picture"></a>
          <a href="https://www.facebook.com/hasmot.ali?__cft__[0]=AZ"><span>Hasmot Ali</span></a>
        </div>
        <div>
          <a href="/profile.php?id=1000998877&amp;__tn__=-UC" aria-label="Md Shipon"></a>
        </div>
      </div>
    </body></html>
    """
    like_profiles = BackgroundHTMLExtractor.extract_from_html(likes_html, session_id="s1", action_type="like")
    assert len(like_profiles) == 2
    assert like_profiles[0].name == "Hasmot Ali"
    assert like_profiles[0].profile_url == "https://www.facebook.com/hasmot.ali"
    assert like_profiles[1].name == "Md Shipon"
    assert like_profiles[1].profile_url == "https://www.facebook.com/profile.php?id=1000998877"

    # 2. Comments HTML (<div role="article" aria-label="Comment by ...">)
    comments_html = """
    <html><body>
      <div role="article" aria-label="Comment by Hasmot Ali 3 hours ago">
        <a href="https://www.facebook.com/hasmot.ali?__cft__[0]=AZ" aria-label="Hasmot Ali"></a>
        <div dir="auto">Hasmot Ali</div>
        <div dir="auto">Alhamdulillah done!</div>
        <a href="https://www.facebook.com/post/1?comment_id=123">3h</a>
      </div>
      <div role="article" aria-label="Comment by Md Shipon yesterday">
        <a href="/profile.php?id=1000998877">Md Shipon</a>
        <img alt="💓" />
        <img alt="🔥" />
      </div>
    </body></html>
    """
    comment_profiles = BackgroundHTMLExtractor.extract_from_html(comments_html, session_id="s1", action_type="comment")
    assert len(comment_profiles) == 2
    assert comment_profiles[0].name == "Hasmot Ali"
    assert comment_profiles[0].profile_url == "https://www.facebook.com/hasmot.ali"
    assert comment_profiles[0].content == "Alhamdulillah done!"
    assert comment_profiles[1].name == "Md Shipon"
    assert comment_profiles[1].profile_url == "https://www.facebook.com/profile.php?id=1000998877"
    assert comment_profiles[1].content == "💓🔥"

    # 3. Embedded Relay JSON fallback
    json_html = """
    <html><body><script type="application/json">
    {"data":{"reactors":{"edges":[{"node":{"actor":{"id":"1000555","name":"Tanvir Hasan","url":"https:\\/\\/www.facebook.com\\/tanvir.hasan"}}}]}}}
    </script></body></html>
    """
    json_profiles = BackgroundHTMLExtractor.extract_from_html(json_html, session_id="s1", action_type="share")
    assert len(json_profiles) == 1
    assert json_profiles[0].name == "Tanvir Hasan"
    assert json_profiles[0].profile_url == "https://www.facebook.com/tanvir.hasan"


def test_extension_clipboard_batch_bridge():
    batch_payload = (
        'FB_CONTEST_BATCH_V1:{"batch_id":"b_101","action_type":"all","items":['
        '{"name":"Hasmot Ali","url":"https://www.facebook.com/hasmot.ali?__cft__=1","content":"","action_type":"like"},'
        '{"name":"Hasmot Ali","url":"https://www.facebook.com/hasmot.ali","content":"Done all 3!","action_type":"comment"},'
        '{"name":"Hasmot Ali","url":"https://www.facebook.com/hasmot.ali","content":"","action_type":"share"}'
        ']}'
    )
    parsed = BrowserDOMExtractor.parse_clipboard_batch(batch_payload, session_id="s_ext")
    assert parsed is not None
    batch_id, profiles = parsed
    assert batch_id == "b_101"
    assert len(profiles) == 3

    participants = ContestValidator.validate_participants(profiles)
    assert len(participants) == 1
    assert participants[0].is_eligible is True
    assert participants[0].serial_code == "#0001"
    assert participants[0].profile_url == "https://www.facebook.com/hasmot.ali"
    assert participants[0].comment_texts == ["Done all 3!"]


def test_nested_reply_comments_and_sharer_post_card_urls():
    # 1. Sharer post card URLs (/username/posts/... and /permalink.php?story_fbid=...&id=...)
    assert clean_facebook_profile_url("https://www.facebook.com/a2ein3d/posts/pfbid02xyz?__cft__[0]=AZ") == "https://www.facebook.com/a2ein3d"
    assert clean_facebook_profile_url("https://www.facebook.com/permalink.php?story_fbid=pfbid01&id=100037037439374") == "https://www.facebook.com/profile.php?id=100037037439374"

    # 2. Nested reply inside parent comment article must NOT cause parent comment to be skipped or mixed
    nested_comments_html = """
    <html><body>
      <div role="article" aria-label="Comment by Imtiaz Ahmed Nahid 2 hours ago">
        <a href="https://www.facebook.com/a2ein3d"><span>Imtiaz Ahmed Nahid</span></a>
        <div dir="auto">Joined the contest!</div>
        <div role="article" aria-label="Reply by Vejal Nai 1 hour ago">
          <a href="https://www.facebook.com/vejalnaibd"><span>Vejal Nai</span></a>
          <div dir="auto">Thank you!</div>
        </div>
      </div>
    </body></html>
    """
    extracted_comments = BackgroundHTMLExtractor.extract_from_html(
        nested_comments_html, session_id="s_nested", action_type="comment"
    )
    by_name = {c.name: c for c in extracted_comments}
    assert "Imtiaz Ahmed Nahid" in by_name
    assert by_name["Imtiaz Ahmed Nahid"].profile_url == "https://www.facebook.com/a2ein3d"
    assert by_name["Imtiaz Ahmed Nahid"].content == "Joined the contest!"

    # 3. Reaction-suffixed Like ("Imtiaz Ahmed Nahid Loved") + Nested Comment + Share Card URL -> Eligible 3/3!
    like_batch = BrowserDOMExtractor.parse_dom_items(
        [{"name": "Imtiaz Ahmed Nahid Loved", "url": "https://www.facebook.com/a2ein3d", "action_type": "like"}],
        session_id="s_nested", action_type="like"
    )
    share_batch = BrowserDOMExtractor.parse_dom_items(
        [{"name": "Imtiaz Ahmed Nahid", "url": "https://www.facebook.com/a2ein3d/posts/pfbid0999", "action_type": "share"}],
        session_id="s_nested", action_type="share"
    )
    participants = ContestValidator.validate_participants(
        like_batch + [by_name["Imtiaz Ahmed Nahid"]] + share_batch
    )
    assert len(participants) == 1
    assert participants[0].name == "Imtiaz Ahmed Nahid"
    assert participants[0].is_eligible is True
    assert participants[0].serial_code == "#0001"


def test_android_single_window_lock_and_comment_expand_coords():
    """
    Verifies that when both a background Post/Comments RecyclerView AND a foreground
    Likes popup RecyclerView exist in the Android XML dump, ProfileExtractor locks
    strictly onto the single foreground window matching action_type (never mixing both!).
    """
    overlapping_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <hierarchy rotation="0">
      <!-- Background Post/Comments RecyclerView -->
      <androidx.recyclerview.widget.RecyclerView bounds="[0,200][1080,2200]" scrollable="true">
        <android.view.ViewGroup bounds="[0,250][1080,450]">
          <android.view.View content-desc="Background Commenter profile picture" bounds="[30,260][110,340]" />
          <android.widget.TextView text="Background Commenter" heading="true" bounds="[130,260][500,310]" />
          <android.widget.TextView text="Great post!" bounds="[130,320][500,370]" />
          <android.view.View content-desc="Comment button" bounds="[130,380][250,420]" />
        </android.view.ViewGroup>
        <android.view.ViewGroup bounds="[0,460][1080,540]">
          <android.widget.TextView text="View more comments" bounds="[40,470][440,530]" />
        </android.view.ViewGroup>
      </androidx.recyclerview.widget.RecyclerView>

      <!-- Foreground Likes Bottom-Sheet Popup RecyclerView -->
      <androidx.recyclerview.widget.RecyclerView bounds="[0,700][1080,2200]" scrollable="true">
        <android.view.ViewGroup bounds="[0,720][1080,860]">
          <android.view.View content-desc="Foreground Reactor profile picture" bounds="[40,730][120,810]" />
          <android.widget.TextView text="Foreground Reactor Liked" heading="true" bounds="[140,740][600,800]" />
          <android.widget.Button text="Add friend" bounds="[800,740][1020,800]" />
        </android.view.ViewGroup>
      </androidx.recyclerview.widget.RecyclerView>
    </hierarchy>
    """
    extractor = ProfileExtractor(min_confidence=0.6)

    # 1. Extracting Likes must ONLY return "Foreground Reactor" (with "Liked" suffix stripped) and lock to [0,700][1080,2200]
    likes = extractor.extract(overlapping_xml, session_id="s_and", action_type="like")
    assert len(likes) == 1
    assert likes[0].name == "Foreground Reactor"
    assert extractor.last_detected_window_type == "like"
    assert extractor.last_active_bounds == (0, 700, 1080, 1500)

    # 2. Extracting Comments must ONLY return "Background Commenter" and lock to [0,200][1080,2200]
    comments = extractor.extract(overlapping_xml, session_id="s_and", action_type="comment")
    assert len(comments) == 1
    assert comments[0].name == "Background Commenter"
    assert comments[0].content == "Great post!"
    assert extractor.last_detected_window_type == "comment"
    assert extractor.last_active_bounds == (0, 200, 1080, 2000)

    # 3. Verify 'View more comments' tap coordinate detection
    tap_xy = ProfileExtractor.find_expand_comments_tap_coords(overlapping_xml)
    assert tap_xy == (240, 500)


def test_comment_author_links_with_comment_id_and_inline_timestamps():
    """
    Verifies that commenter profile links containing ?comment_id=... and inline
    timestamp/badge suffixes ('Ayatullah Mushkan Maryam · 4h', 'Moni Mreedha · 6h · Top fan')
    are normalized into canonical profile URLs and clean author names.
    """
    # 1. Comment author URLs with ?comment_id= must be preserved as profile URLs
    assert (
        clean_facebook_profile_url("https://www.facebook.com/ayatullah.maryam?comment_id=Y29tbWVudDoxMjM=&__cft__[0]=AZ")
        == "https://www.facebook.com/ayatullah.maryam"
    )
    assert (
        clean_facebook_profile_url("https://www.facebook.com/profile.php?id=1000888999&comment_id=Y29tbWVudDoxMjM=")
        == "https://www.facebook.com/profile.php?id=1000888999"
    )
    assert (
        clean_facebook_profile_url("https://www.facebook.com/people/Ayatullah-Mushkan-Maryam/pfbid02xyz?comment_id=123")
        == "https://www.facebook.com/people/Ayatullah-Mushkan-Maryam/pfbid02xyz"
    )
    # Whereas post permalink timestamp links (/vejalnaibd/posts/pfbid...?comment_id=123) must still return None
    assert (
        clean_facebook_profile_url("https://www.facebook.com/vejalnaibd/posts/pfbid0k45Y7MQJ?comment_id=123")
        is None
    )

    # 2. Inline timestamps ('· 4h', '· 6h · Top fan') stripped from author names
    parsed = BrowserDOMExtractor.parse_dom_items(
        [
            {
                "name": "Ayatullah Mushkan Maryam · 4h",
                "url": "https://www.facebook.com/ayatullah.maryam?comment_id=Y29tbWVudDoxMjM=",
                "content": "Redy",
                "action_type": "comment",
            },
            {
                "name": "Moni Mreedha · 6h · Top fan",
                "url": "https://www.facebook.com/profile.php?id=1000888999&comment_id=Y29tbWVudDoxMjM=",
                "content": "Insha'Allah",
                "action_type": "comment",
            },
        ],
        session_id="s_inline",
        action_type="comment",
    )
    assert len(parsed) == 2
    assert parsed[0].name == "Ayatullah Mushkan Maryam"
    assert parsed[0].profile_url == "https://www.facebook.com/ayatullah.maryam"
    assert parsed[0].content == "Redy"
    assert parsed[1].name == "Moni Mreedha"
    assert parsed[1].profile_url == "https://www.facebook.com/profile.php?id=1000888999"
    assert parsed[1].content == "Insha'Allah"


def test_hybrid_profile_sync_engine_three_layers():
    """
    Tests the separate Hybrid Phone + Web ProfileSyncEngine:
      1. Unique Name Phone (Share + Comment without URL) + Web (Like with URL) -> 3/3 Eligible with URL applied.
      2. Same-Name Collision ('Md Shipon' #1 and 'Md Shipon' #2) disambiguated accurately via 64-bit Avatar dHash.
    """
    from app.utils.profile_sync_engine import ProfileSyncEngine

    raw_profiles = [
        # Person 1: Hasmot Ali (Liked on Web with URL, Commented & Shared on Phone without URL)
        ShareProfile(
            name="Hasmot Ali",
            profile_url="https://www.facebook.com/hasmot.ali",
            action_type="like",
            source="facebook_browser_extension",
            confidence=1.0,
            session_id="s_hyb",
        ),
        ShareProfile(
            name="Hasmot Ali",
            profile_url=None,
            content="Alhamdulillah",
            action_type="comment",
            source="facebook_android_ui",
            confidence=0.95,
            session_id="s_hyb",
        ),
        ShareProfile(
            name="Hasmot Ali",
            profile_url=None,
            action_type="share",
            source="facebook_android_ui",
            confidence=0.95,
            session_id="s_hyb",
        ),
        # Person 2A & 2B: Two distinct people named "Md Shipon" disambiguated by Avatar pHash!
        ShareProfile(
            name="Md Shipon",
            profile_url=None,
            avatar_hash="1111222233334444",
            action_type="share",
            source="facebook_android_ui",
            confidence=0.95,
            session_id="s_hyb",
        ),
        ShareProfile(
            name="Md Shipon",
            profile_url=None,
            avatar_hash="ffffaaaabbbbcccc",
            action_type="share",
            source="facebook_android_ui",
            confidence=0.95,
            session_id="s_hyb",
        ),
        ShareProfile(
            name="Md Shipon",
            profile_url="https://www.facebook.com/shipon.one",
            avatar_hash="1111222233334440",  # Distance 1 from first Phone Shipon
            action_type="like",
            source="facebook_browser_extension",
            confidence=1.0,
            session_id="s_hyb",
        ),
        ShareProfile(
            name="Md Shipon",
            profile_url="https://www.facebook.com/shipon.two",
            avatar_hash="ffffaaaabbbbccc0",  # Distance 2 from second Phone Shipon
            action_type="like",
            source="facebook_browser_extension",
            confidence=1.0,
            session_id="s_hyb",
        ),
    ]

    engine = ProfileSyncEngine()
    rows = engine.build_sync_checklist(raw_profiles)
    assert len(rows) == 3

    # Verify Hasmot Ali is 3/3 Eligible and matched across Phone + Web
    hasmot_row = next(r for r in rows if r.name == "Hasmot Ali")
    assert hasmot_row.is_eligible is True
    assert hasmot_row.profile_url == "https://www.facebook.com/hasmot.ali"
    assert hasmot_row.sync_status == "VERIFIED_UNIQUE_NAME"

    # Verify the two "Md Shipon" rows matched their exact respective Web URLs via Layer 2 Avatar dHash!
    shipon_rows = {r.profile_url: r for r in rows if r.name == "Md Shipon"}
    assert "https://www.facebook.com/shipon.one" in shipon_rows
    assert "https://www.facebook.com/shipon.two" in shipon_rows
    assert shipon_rows["https://www.facebook.com/shipon.one"].sync_status == "VERIFIED_3_LAYER"
    assert shipon_rows["https://www.facebook.com/shipon.one"].phone_avatar_hash == "1111222233334444"
    assert shipon_rows["https://www.facebook.com/shipon.two"].sync_status == "VERIFIED_3_LAYER"
    assert shipon_rows["https://www.facebook.com/shipon.two"].phone_avatar_hash == "ffffaaaabbbbcccc"

    # Apply synced URLs back to raw_profiles and verify main ContestValidator
    updated = engine.apply_synced_urls_to_profiles(rows)
    assert updated == 4
    participants = ContestValidator.validate_participants(raw_profiles)
    eligible = [p for p in participants if p.is_eligible]
    assert len(eligible) == 1
    assert eligible[0].name == "Hasmot Ali"
    assert eligible[0].profile_url == "https://www.facebook.com/hasmot.ali"


def test_same_name_conflict_resolution_via_comment_bridge():
    """
    Tests Same-Name Conflict Avoidance when two users have the exact same name ('Md Sakib'),
    two different Web URLs ('sakib.real' and 'sakib.other'), and NO Web avatar hashes yet,
    by bridging Phone AvatarHash <-> Comment Text <-> Web Profile URL!
    """
    from app.utils.profile_sync_engine import ProfileSyncEngine

    profiles = [
        # Web records for two different "Md Sakib" users
        ShareProfile(name="Md Sakib", profile_url="https://www.facebook.com/sakib.real", action_type="like", source="facebook_browser_extension", confidence=1.0, session_id="s_col"),
        ShareProfile(name="Md Sakib", profile_url="https://www.facebook.com/sakib.real", content="রেডি আছি ইনশাআল্লাহ", action_type="comment", source="facebook_browser_extension", confidence=1.0, session_id="s_col"),
        ShareProfile(name="Md Sakib", profile_url="https://www.facebook.com/sakib.other", action_type="like", source="facebook_browser_extension", confidence=1.0, session_id="s_col"),
        ShareProfile(name="Md Sakib", profile_url="https://www.facebook.com/sakib.other", content="আমিও অংশ নিলাম", action_type="comment", source="facebook_browser_extension", confidence=1.0, session_id="s_col"),

        # Phone records for "Md Sakib" #1 (who commented "রেডি আছি ইনশাআল্লাহ" AND shared the post!)
        ShareProfile(name="Md Sakib", profile_url=None, avatar_hash="d8d8cae657d5cce0", content="রেডি আছি ইনশাআল্লাহ", action_type="comment", source="facebook_android_ui", confidence=0.95, session_id="s_col"),
        ShareProfile(name="Md Sakib", profile_url=None, avatar_hash="d8d8cae657d5cce1", action_type="share", source="facebook_android_ui", confidence=0.95, session_id="s_col"),
    ]

    engine = ProfileSyncEngine()
    rows = engine.build_sync_checklist(profiles)
    engine.apply_synced_urls_to_profiles(rows)

    participants = ContestValidator.validate_participants(profiles)
    assert len(participants) == 2

    by_url = {p.profile_url: p for p in participants}
    assert by_url["https://www.facebook.com/sakib.real"].is_eligible is True
    assert by_url["https://www.facebook.com/sakib.real"].shared is True
    assert by_url["https://www.facebook.com/sakib.other"].is_eligible is False
    assert by_url["https://www.facebook.com/sakib.other"].shared is False


def test_zero_data_inconsistency_between_validator_sync_and_exporters():
    """
    End-to-end consistency verification across:
      - Vertical-shift-invariant dHash matching (absorbing Android uiautomator/screencap jitter)
      - Corrupted screen-transition hash sanitization ('0100000000e0c285', 'e1c9b1cd00040800')
      - Tab 1 (ContestValidator) vs Tab 2 (ProfileSyncEngine) vs CSVExporter vs LotteryPrintExporter
    """
    import csv
    from app.utils.profile_sync_engine import ProfileSyncEngine
    from app.exporters.csv_exporter import CSVExporter

    profiles = [
        # User 1: Mohammad Forhad — Web Like + Comment (with URL), Phone Share + Vertically-Shifted Phone Comment Hash
        ShareProfile(name="Mohammad Forhad", profile_url="https://www.facebook.com/forhaduni", action_type="like", source="facebook_browser_extension", confidence=1.0, session_id="s_cons"),
        ShareProfile(name="Mohammad Forhad", profile_url=None, avatar_hash="f0f0ecc486ccb2d4", content="Waiting", action_type="comment", source="facebook_android_ui", confidence=0.95, session_id="s_cons", scroll_index=3),
        ShareProfile(name="Mohammad Forhad", profile_url=None, avatar_hash="e8b2f0e8ecc686cc", content="Waiting", action_type="comment", source="facebook_android_ui", confidence=0.95, session_id="s_cons", scroll_index=4),
        ShareProfile(name="Mohammad Forhad", profile_url=None, avatar_hash="f0ecac86a286c4f0", action_type="share", source="facebook_android_ui", confidence=0.95, session_id="s_cons", scroll_index=1),

        # User 2: Shafiqul Islam — Phone Share with valid hash + Phone Share during home-screen transition (corrupted hash)
        ShareProfile(name="Shafiqul Islam", profile_url=None, avatar_hash="d09682e39a8eb0b0", action_type="share", source="facebook_android_ui", confidence=0.95, session_id="s_cons", scroll_index=8),
        ShareProfile(name="Shafiqul Islam", profile_url=None, avatar_hash="e1c9b1cd00040800", action_type="share", source="facebook_android_ui", confidence=0.95, session_id="s_cons", scroll_index=11),

        # Legacy UI noise rows that must be ignored identically by both Tab 1 and Tab 2
        ShareProfile(name="Reply to Forhad's comment", profile_url=None, action_type="comment", source="facebook_android_ui", confidence=0.5, session_id="s_cons"),
        ShareProfile(name="Online status indicator active", profile_url=None, action_type="like", source="facebook_android_ui", confidence=0.5, session_id="s_cons"),
    ]

    engine = ProfileSyncEngine()
    sync_rows = engine.build_sync_checklist(profiles)
    engine.apply_synced_urls_to_profiles(sync_rows)
    sync_rows = engine.build_sync_checklist(profiles)
    participants = ContestValidator.validate_participants(profiles)

    # 1. Exact same participant count & eligibility between Tab 1 and Tab 2
    assert len(participants) == 2
    assert len(sync_rows) == 2
    assert [p.name for p in participants] == ["Mohammad Forhad", "Shafiqul Islam"]
    assert all(p.disambiguator == "" for p in participants)

    # 2. Mohammad Forhad is 3/3 Eligible with verified URL on all records
    forhad = participants[0]
    assert forhad.is_eligible is True
    assert forhad.serial_code == "#0001"
    assert forhad.profile_url == "https://www.facebook.com/forhaduni"

    # 3. Exported Contest CSV matches ContestValidator 1:1
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "contest.csv")
        assert CSVExporter.export_contest(participants, csv_path) is True
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[0]["Serial #"] == "#0001"
        assert rows[0]["Profile URL"] == "https://www.facebook.com/forhaduni"


def test_mass_load_20k_users_performance_and_consistency():
    """
    20,000-User Mass-Load Benchmark & Consistency Test:
    Simulates 20,000 unique users with 50,000 raw interactions (20k Likes + 18k Comments + 12k Shares)
    and verifies:
      1. IncrementalContestAggregator + O(1) get_counts() completes in < 3.5s.
      2. ProfileSyncEngine.build_sync_checklist + apply_synced_urls_to_profiles completes in < 3.5s.
      3. Zero data loss: all 20,000 users and 12,000 Eligible (3/3) winners (#0001..#12000) match 100%.
    """
    import time
    from app.utils.contest_validator import IncrementalContestAggregator
    from app.utils.profile_sync_engine import ProfileSyncEngine
    from app.exporters.csv_exporter import CSVExporter

    profiles = []
    for i in range(20000):
        name = f"Contestant {i}"
        url = f"https://www.facebook.com/contestant.{i}"
        h = f"a1b2c3d4{(i & 0xFFFFFFFF):08x}"
        profiles.append(
            ShareProfile(name=name, profile_url=url, action_type="like", source="web", confidence=1.0, session_id="s_20k", scroll_index=i // 10)
        )
        if i < 18000:
            profiles.append(
                ShareProfile(name=name, profile_url=None, avatar_hash=h, content=f"Done {i}", action_type="comment", source="phone", confidence=0.95, session_id="s_20k", scroll_index=i // 8)
            )
        if i < 12000:
            profiles.append(
                ShareProfile(name=name, profile_url=None, avatar_hash=h, action_type="share", source="phone", confidence=0.95, session_id="s_20k", scroll_index=i // 8)
            )

    assert len(profiles) == 50000

    t0 = time.perf_counter()
    engine = ProfileSyncEngine()
    sync_rows = engine.build_sync_checklist(profiles)
    enriched = engine.apply_synced_urls_to_profiles(sync_rows)
    t_sync = time.perf_counter() - t0

    assert len(sync_rows) == 20000
    assert enriched >= 30000  # All 30k phone records enriched with Web URLs + Web records enriched with avatar hashes!
    assert all(p.profile_url for p in profiles)
    assert t_sync < 3.5

    t1 = time.perf_counter()
    agg = IncrementalContestAggregator()
    for p in profiles:
        agg.add_profile(p)
    counts = agg.get_counts()
    participants = agg.get_sorted_participants()
    t_agg = time.perf_counter() - t1

    assert counts["total_participants"] == 20000
    assert counts["likes"] == 20000
    assert counts["comments"] == 18000
    assert counts["shares"] == 12000
    assert counts["eligible"] == 12000
    assert len(participants) == 20000
    assert participants[0].serial_code == "#0001"
    assert participants[11999].serial_code == "#12000"
    assert participants[12000].serial_code == "-"
    assert t_agg < 3.5

    with tempfile.TemporaryDirectory() as tmpdir:
        out_csv = os.path.join(tmpdir, "contest_20k.csv")
        assert CSVExporter.export_contest(participants, out_csv) is True
        assert os.path.getsize(out_csv) > 1_000_000


def test_windows_utf8_litho_multiline_and_local_http_bridge():
    """
    Verifies the Windows fixes:
      1. ProfileExtractor extracts Likes with ', 12 mutual friends, Add friend' and
         Comments from multiline Litho ViewGroups even when avatar content-desc is generic or missing.
      2. LocalBridgeServer receives POST /batch over localhost HTTP and queues batches cleanly.
    """
    import urllib.request
    from app.automation.local_bridge_server import LocalBridgeServer

    litho_comments_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <hierarchy rotation="0">
      <android.widget.ScrollView scrollable="true" bounds="[0,200][1080,2200]">
        <android.view.ViewGroup bounds="[0,200][1080,2200]">
          <!-- Comment 1: Generic 'Profile picture' + multiline Litho ViewGroup with Bangla & bullet -->
          <android.view.ViewGroup bounds="[0,250][1080,450]">
            <android.widget.ImageView content-desc="Profile picture" bounds="[36,260][126,350]" />
            <android.view.ViewGroup text="তৌহিদা ফাতেমা&#10;· Follow&#10;আলহামদুলিল্লাহ দারুণ আয়োজন!&#10;2h" bounds="[140,260][980,420]" />
            <android.widget.Button content-desc="Reply to তৌহিদা's comment" bounds="[140,420][300,450]" />
          </android.view.ViewGroup>
          <!-- Comment 2: 'Profile picture of <Name>' format -->
          <android.view.ViewGroup bounds="[0,460][1080,660]">
            <android.widget.ImageView content-desc="Profile picture of Tanjeeb Khan" bounds="[36,470][126,560]" />
            <android.view.ViewGroup text="Tanjeeb Khan&#10;লাগাও বৃক্ষ!" bounds="[140,470][980,620]" />
          </android.view.ViewGroup>
        </android.view.ViewGroup>
      </android.widget.ScrollView>
    </hierarchy>
    """
    extractor = ProfileExtractor(min_confidence=0.6)
    comments = extractor.extract(litho_comments_xml, session_id="s_win", action_type="comment")
    assert len(comments) == 2
    assert comments[0].name == "তৌহিদা ফাতেমা"
    assert comments[0].content == "আলহামদুলিল্লাহ দারুণ আয়োজন!"
    assert comments[1].name == "Tanjeeb Khan"
    assert comments[1].content == "লাগাও বৃক্ষ!"

    litho_likes_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <hierarchy rotation="0">
      <androidx.recyclerview.widget.RecyclerView scrollable="true" bounds="[0,200][1080,2200]">
        <android.view.ViewGroup content-desc="Md. Rakib Hasan, 12 mutual friends, Add friend" clickable="true" bounds="[0,250][1080,400]" />
        <android.view.ViewGroup text="Champa Akter&#10;5 mutual friends&#10;Add friend" clickable="true" bounds="[0,410][1080,560]" />
      </androidx.recyclerview.widget.RecyclerView>
    </hierarchy>
    """
    likes = extractor.extract(litho_likes_xml, session_id="s_win", action_type="like")
    assert len(likes) == 2
    assert likes[0].name == "Md. Rakib Hasan"
    assert likes[1].name == "Champa Akter"

    # Test LocalBridgeServer queue & HTTP POST handler
    bridge = LocalBridgeServer(port=19881)
    payload = 'FB_CONTEST_BATCH_V1:{"batch_id":"win_http_1","action_type":"like","items":[{"name":"তৌহিদা ফাতেমা","url":"https://www.facebook.com/touhida.fatema","action_type":"like"}]}'
    bridge.enqueue_batch_str(payload)
    batches = bridge.pop_batches()
    assert len(batches) == 1
    parsed = BrowserDOMExtractor.parse_clipboard_batch(batches[0], session_id="s_win")
    assert parsed is not None
    b_id, profs = parsed
    assert b_id == "win_http_1"
    assert len(profs) == 1
    assert profs[0].name == "তৌহিদা ফাতেমা"
    assert profs[0].profile_url == "https://www.facebook.com/touhida.fatema"


def test_advanced_filter_engine_boolean_and_or_not_and_bangla_boundaries():
    """
    Tests DrawSystem (FairDraw) Advanced Filtering & Boolean Logic (AND / OR / NOT):
      1. Whole-word boundary matching for English & Bangla ('4' vs '14', 'ভালো' vs 'ভালোবাসি', 'apple' vs 'pineapple').
      2. OR keywords (any right answer variation: '4, চার, four').
      3. AND keywords (must contain all required words).
      4. NOT keywords (wrong answer / spam exclusion takes priority).
      5. Inline Boolean Expression syntax: '(apple OR আপেল) AND fresh NOT rotten'.
      6. Emoji-only / Invalid comment detection & Category Pill counts ('qualified', 'correct', 'wrong', 'invalid', 'no_comments', 'duplicates', 'disqualified').
    """
    from app.utils.advanced_filter_engine import AdvancedFilterConfig, AdvancedFilterEngine

    # 1. Whole-Word Boundary Checks (DrawSystem test_regex.php parity)
    assert AdvancedFilterEngine.match_single_keyword("The answer is 4.", "4", "whole_word") is True
    assert AdvancedFilterEngine.match_single_keyword("The answer is 14.", "4", "whole_word") is False
    assert AdvancedFilterEngine.match_single_keyword("আমি ভালো আছি!", "ভালো", "whole_word") is True
    assert AdvancedFilterEngine.match_single_keyword("আমি তোমাকে ভালোবাসি", "ভালো", "whole_word") is False
    assert AdvancedFilterEngine.match_single_keyword("I like apple.", "apple", "whole_word") is True
    assert AdvancedFilterEngine.match_single_keyword("I like pineapple.", "apple", "whole_word") is False

    # Partial ("contains") mode should match substrings
    assert AdvancedFilterEngine.match_single_keyword("আমি তোমাকে ভালোবাসি", "ভালো", "contains") is True
    assert AdvancedFilterEngine.match_single_keyword("The answer is 14.", "4", "contains") is True

    # Exact mode should match only when the stripped comment equals the keyword
    assert AdvancedFilterEngine.match_single_keyword("  apple! ", "apple", "exact") is True
    assert AdvancedFilterEngine.match_single_keyword("I like apple", "apple", "exact") is False

    # Inline Boolean Expression parser
    assert AdvancedFilterEngine.evaluate_inline_boolean_query(
        ["তাজা আপেল খেতে মজা"], "(apple OR আপেল) AND তাজা NOT পচা", "whole_word"
    ) is True
    assert AdvancedFilterEngine.evaluate_inline_boolean_query(
        ["পচা আপেল খেতে মজা"], "(apple OR আপেল) AND তাজা NOT পচা", "whole_word"
    ) is False

    # 2. Full Participant Evaluation & Category Counts
    profiles = [
        # P1: Md Rakib (3/3 + Right answer "উত্তর ৪ এবং ডান" -> Qualified!)
        ShareProfile(name="Md Rakib", profile_url="https://facebook.com/rakib1", action_type="like", source="web", confidence=1.0, session_id="s_flt"),
        ShareProfile(name="Md Rakib", profile_url="https://facebook.com/rakib1", content="সঠিক উত্তর ৪ এবং ডান!", action_type="comment", source="web", confidence=1.0, session_id="s_flt"),
        ShareProfile(name="Md Rakib", profile_url="https://facebook.com/rakib1", action_type="share", source="web", confidence=1.0, session_id="s_flt"),

        # P2: Nusrat Jahan (3/3 + Right answer "Answer is 4 done" -> Qualified!)
        ShareProfile(name="Nusrat Jahan", profile_url="https://facebook.com/nusrat1", action_type="like", source="web", confidence=1.0, session_id="s_flt"),
        ShareProfile(name="Nusrat Jahan", profile_url="https://facebook.com/nusrat1", content="Answer is 4, done @friend", action_type="comment", source="web", confidence=1.0, session_id="s_flt"),
        ShareProfile(name="Nusrat Jahan", profile_url="https://facebook.com/nusrat1", action_type="share", source="web", confidence=1.0, session_id="s_flt"),

        # P3: Tanvir Ahmed (3/3 + Wrong answer "14 done" -> Excluded by whole-word & NOT keyword "14")
        ShareProfile(name="Tanvir Ahmed", profile_url="https://facebook.com/tanvir1", action_type="like", source="web", confidence=1.0, session_id="s_flt"),
        ShareProfile(name="Tanvir Ahmed", profile_url="https://facebook.com/tanvir1", content="Answer is 14 done", action_type="comment", source="web", confidence=1.0, session_id="s_flt"),
        ShareProfile(name="Tanvir Ahmed", profile_url="https://facebook.com/tanvir1", action_type="share", source="web", confidence=1.0, session_id="s_flt"),

        # P4: Emoji User (3/3 + Emoji-only comment "🔥🔥❤️❤️")
        ShareProfile(name="Fatema Akter", profile_url="https://facebook.com/fatema1", action_type="like", source="web", confidence=1.0, session_id="s_flt"),
        ShareProfile(name="Fatema Akter", profile_url="https://facebook.com/fatema1", content="🔥🔥❤️❤️", action_type="comment", source="web", confidence=1.0, session_id="s_flt"),
        ShareProfile(name="Fatema Akter", profile_url="https://facebook.com/fatema1", action_type="share", source="web", confidence=1.0, session_id="s_flt"),

        # P5: No Comment User (Likes + Shares only)
        ShareProfile(name="Sohel Rana", profile_url="https://facebook.com/sohel1", action_type="like", source="web", confidence=1.0, session_id="s_flt"),
        ShareProfile(name="Sohel Rana", profile_url="https://facebook.com/sohel1", action_type="share", source="web", confidence=1.0, session_id="s_flt"),
    ]

    participants = ContestValidator.validate_participants(profiles)
    assert len(participants) == 5

    cfg = AdvancedFilterConfig(
        or_keywords="4, ৪, চার",
        and_keywords="done, ডান",  # Wait: AND requires ALL keywords in `and_keywords`; let's test OR + NOT first
    )
    # Test OR = "4, ৪, চার", AND = "", NOT = "14, ভুল"
    cfg = AdvancedFilterConfig(
        or_keywords="4, ৪, চার",
        and_keywords="",
        not_keywords="14, ভুল",
        match_mode="whole_word",
        exclude_invalid_emoji=True,
        quick_category="qualified",
    )
    qualified_list, evals, counts = AdvancedFilterEngine.evaluate_all(participants, cfg)

    assert counts["all"] == 5
    assert counts["qualified"] == 2
    assert counts["correct"] == 2
    assert counts["wrong"] == 1      # Tanvir Ahmed ("14 done")
    assert counts["invalid"] == 1    # Fatema Akter ("🔥🔥❤️❤️")
    assert counts["no_comments"] == 1  # Sohel Rana

    # Qualified winners get re-numbered #0001 and #0002, while wrong/invalid get "-"
    assert [p.name for p in qualified_list] == ["Md Rakib", "Nusrat Jahan"]
    assert qualified_list[0].serial_code == "#0001"
    assert qualified_list[1].serial_code == "#0002"
    tanvir = next(p for p in participants if p.name == "Tanvir Ahmed")
    assert tanvir.serial_code == "-"

    # Now test combining OR ("4, ৪") + AND ("done") -> Only Nusrat Jahan has both ("4" OR "৪") AND "done"
    cfg_and = AdvancedFilterConfig(
        or_keywords="4, ৪",
        and_keywords="done",
        not_keywords="14",
        match_mode="whole_word",
        quick_category="qualified",
    )
    qual_and, _, counts_and = AdvancedFilterEngine.evaluate_all(participants, cfg_and)
    assert counts_and["qualified"] == 1
    assert qual_and[0].name == "Nusrat Jahan"
    assert qual_and[0].serial_code == "#0001"

    # Test Gender filter ("female")
    cfg_female = AdvancedFilterConfig(gender_filter="female", quick_category="all")
    female_list, _, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_female)
    assert {p.name for p in female_list} == {"Nusrat Jahan", "Fatema Akter"}


def test_action_toggle_bar_custom_rules_sentiment_and_one_entry_per_user():
    """
    Tests the Interactive Action Requirement Toggle Bar (Like, Comment, Share with
    AND / OR / Comment & (Like OR Share) / Like & (Comment OR Share) / Any 2 of 3),
    Custom Analysis Rules (DrawSystem Global Analyzer parity), Sentiment detection,
    and 1-Entry-Per-Person deduplication.
    """
    from app.utils.advanced_filter_engine import (
        AdvancedFilterConfig,
        AdvancedFilterEngine,
        CustomAnalysisRule,
    )

    profiles = [
        # User A: Full 3/3 (Like + Comment + Share) with positive comment & friend tag
        ShareProfile(name="Arif Hossain", profile_url="https://facebook.com/arif1", action_type="like", source="web", confidence=1.0, session_id="s_act"),
        ShareProfile(name="Arif Hossain", profile_url="https://facebook.com/arif1", content="Alhamdulillah awesome post @karim #giveaway", action_type="comment", source="web", confidence=1.0, session_id="s_act"),
        ShareProfile(name="Arif Hossain", profile_url="https://facebook.com/arif1", action_type="share", source="web", confidence=1.0, session_id="s_act"),

        # User B: Like + Comment ONLY (No Share)
        ShareProfile(name="Bithi Akter", profile_url="https://facebook.com/bithi1", action_type="like", source="web", confidence=1.0, session_id="s_act"),
        ShareProfile(name="Bithi Akter", profile_url="https://facebook.com/bithi1", content="ধন্যবাদ সুন্দর আয়োজন @rahim", action_type="comment", source="web", confidence=1.0, session_id="s_act"),

        # User C: Comment + Share ONLY (No Like)
        ShareProfile(name="Chanchal Chowdhury", profile_url="https://facebook.com/chanchal1", action_type="comment", content="Ready for the draw!", source="web", confidence=1.0, session_id="s_act"),
        ShareProfile(name="Chanchal Chowdhury", profile_url="https://facebook.com/chanchal1", action_type="share", source="web", confidence=1.0, session_id="s_act"),

        # User D: Share ONLY (No Like, No Comment)
        ShareProfile(name="Dipa Rani", profile_url="https://facebook.com/dipa1", action_type="share", source="web", confidence=1.0, session_id="s_act"),

        # User E: Duplicate same-name account for "Arif Hossain" (different URL, also 3/3)
        ShareProfile(name="Arif Hossain", profile_url="https://facebook.com/arif2", action_type="like", source="web", confidence=1.0, session_id="s_act"),
        ShareProfile(name="Arif Hossain", profile_url="https://facebook.com/arif2", content="Great work @friend", action_type="comment", source="web", confidence=1.0, session_id="s_act"),
        ShareProfile(name="Arif Hossain", profile_url="https://facebook.com/arif2", action_type="share", source="web", confidence=1.0, session_id="s_act"),
    ]

    participants = ContestValidator.validate_participants(profiles)
    assert len(participants) == 5

    # 1. Default 3/3 AND mode (Like AND Comment AND Share): only Arif #1 and Arif #2 qualify
    cfg_default = AdvancedFilterConfig(
        require_like=True,
        require_comment=True,
        require_share=True,
        action_operator="AND",
        one_entry_per_user=False,
        quick_category="qualified",
    )
    qual_default, _, counts_default = AdvancedFilterEngine.evaluate_all(participants, cfg_default)
    assert counts_default["qualified"] == 2

    # 2. 1 Entry / Person enabled: second "Arif Hossain" is marked duplicate and excluded from winner pool
    cfg_one_entry = AdvancedFilterConfig(
        require_like=True,
        require_comment=True,
        require_share=True,
        action_operator="AND",
        one_entry_per_user=True,
        quick_category="qualified",
    )
    qual_one, evals_one, counts_one = AdvancedFilterEngine.evaluate_all(participants, cfg_one_entry)
    assert counts_one["qualified"] == 1
    assert counts_one["duplicates"] == 2  # Both Arif accounts appear in 'Duplicates' view for side-by-side inspection/merge
    assert sum(1 for ev in evals_one.values() if ev.is_duplicate_name and not ev.is_qualified_winner) == 1  # Only the 2nd Arif is excluded from winning
    assert qual_one[0].name == "Arif Hossain"
    assert qual_one[0].serial_code == "#0001"

    # 3. Toggle OFF Share -> Require Like 👍 AND Comment 💬 only: Arif + Bithi qualify!
    cfg_like_comment = AdvancedFilterConfig(
        require_like=True,
        require_comment=True,
        require_share=False,
        action_operator="AND",
        one_entry_per_user=True,
        quick_category="qualified",
    )
    qual_lc, _, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_like_comment)
    assert {p.name for p in qual_lc} == {"Arif Hossain", "Bithi Akter"}
    assert [p.serial_code for p in qual_lc] == ["#0001", "#0002"]

    # Verify LotteryPrintExporter prints both #0001 and #0002 even though Bithi is 2/3
    with tempfile.TemporaryDirectory() as tmpdir:
        out_html = os.path.join(tmpdir, "tickets_lc.html")
        assert LotteryPrintExporter.export_printable_tickets(qual_lc, out_html) is True
        html_doc = open(out_html, encoding="utf-8").read()
        assert "Bithi Akter" in html_doc
        assert "#0002" in html_doc

    # 4. Action Operator = "COMMENT_AND_LIKE_OR_SHARE" -> Comment 💬 AND (Like 👍 OR Share 🔄)
    # Qualifies Arif (all 3), Bithi (Like + Comment), and Chanchal (Comment + Share), NOT Dipa (Share only)
    cfg_clos = AdvancedFilterConfig(
        require_like=True,
        require_comment=True,
        require_share=True,
        action_operator="COMMENT_AND_LIKE_OR_SHARE",
        one_entry_per_user=True,
        quick_category="qualified",
    )
    qual_clos, _, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_clos)
    assert {p.name for p in qual_clos} == {"Arif Hossain", "Bithi Akter", "Chanchal Chowdhury"}

    # 5. Action Operator = "OR" (Any selected action: Like OR Comment OR Share) -> All 4 unique people qualify!
    cfg_or = AdvancedFilterConfig(
        require_like=True,
        require_comment=True,
        require_share=True,
        action_operator="OR",
        one_entry_per_user=True,
        quick_category="qualified",
    )
    qual_or, _, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_or)
    assert {p.name for p in qual_or} == {"Arif Hossain", "Bithi Akter", "Chanchal Chowdhury", "Dipa Rani"}

    # 6. Custom Analysis Rule (must mention @friend) + Positive Sentiment filter
    rule_tag = CustomAnalysisRule(
        id="r1",
        name="Has Friend Mention",
        rule_type="has_tags",
        value="@",
        enforce_for_qualification=True,
    )
    cfg_custom = AdvancedFilterConfig(
        require_like=True,
        require_comment=True,
        require_share=False,
        action_operator="AND",
        sentiment_filter="positive",
        one_entry_per_user=True,
        custom_rules=[rule_tag],
        quick_category="qualified",
    )
    qual_custom, evals_custom, counts_custom = AdvancedFilterEngine.evaluate_all(participants, cfg_custom)
    assert {p.name for p in qual_custom} == {"Arif Hossain", "Bithi Akter"}
    assert counts_custom["positive"] >= 3

    # 7. Bi-directional Bangla <-> English digit matching ("4" <-> "৪", "14" <-> "১৪") with whole-word boundary
    assert AdvancedFilterEngine.match_single_keyword("সঠিক উত্তর ৪!", "4", "whole_word") is True
    assert AdvancedFilterEngine.match_single_keyword("The answer is 4!", "৪", "whole_word") is True
    assert AdvancedFilterEngine.match_single_keyword("সঠিক উত্তর ১৪!", "4", "whole_word") is False
    assert AdvancedFilterEngine.match_single_keyword("The answer is 14!", "৪", "whole_word") is False

    # 8. Custom Action Formula ('action_combo'): (like AND comment) OR share
    rule_act_combo = CustomAnalysisRule(
        id="r_act",
        name="Like+Comment OR Share",
        rule_type="action_combo",
        value="(like AND comment) OR share",
        enforce_for_qualification=True,
    )
    cfg_act_combo = AdvancedFilterConfig(
        require_like=False,
        require_comment=False,
        require_share=False,
        one_entry_per_user=True,
        custom_rules=[rule_act_combo],
        quick_category="qualified",
    )
    qual_combo, _, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_act_combo)
    assert {p.name for p in qual_combo} == {"Arif Hossain", "Bithi Akter", "Chanchal Chowdhury", "Dipa Rani"}

    # 9. CSVExporter.export_contest reflects active Action Toggle eligibility ("YES") even for 2/3 winners
    import csv
    from app.exporters.csv_exporter import CSVExporter
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_lc = os.path.join(tmpdir, "lc_winners.csv")
        qual_lc, _, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_like_comment)
        assert CSVExporter.export_contest(qual_lc, csv_lc) is True
        with open(csv_lc, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[0]["Serial #"] == "#0001"
        assert rows[0]["Eligible"] == "YES"
        assert rows[1]["Name"] == "Bithi Akter"
        assert rows[1]["Serial #"] == "#0002"
        assert rows[1]["Eligible"] == "YES"
        assert "QUALIFIED" in rows[1]["Status"]


def test_three_field_chained_toggle_bar_actions_and_keywords():
    """
    Tests the 3-Field Chained Toggle Bar layout:
      [Field 1] -> [Dropdown 1: AND / OR / NOT / OR NOT] -> [Field 2] -> [Dropdown 2: AND / OR / NOT / OR NOT] -> [Field 3]
    Specifically verifies:
      1. If Field 3 is NOT selected (toggled OFF or 'none' or empty), Field 3 and Dropdown 2 are NOT applied at all!
      2. If Field 2 is NOT selected, Field 2 and Dropdown 1 are NOT applied.
      3. Selecting AND, OR, NOT (AND NOT), and OR NOT in Dropdown 1 and Dropdown 2 works for both Actions and Keywords.
      4. Grouping toggle F1 op (F2 op F3) vs (F1 op F2) op F3 works accurately.
    """
    from app.utils.advanced_filter_engine import (
        AdvancedFilterConfig,
        AdvancedFilterEngine,
    )

    profiles = [
        # User 1: Like + Comment + Share, comment="apple fresh spam"
        ShareProfile(name="User AllThree", profile_url="https://facebook.com/u1", action_type="like", source="web", confidence=1.0, session_id="s_chain"),
        ShareProfile(name="User AllThree", profile_url="https://facebook.com/u1", content="apple fresh spam", action_type="comment", source="web", confidence=1.0, session_id="s_chain"),
        ShareProfile(name="User AllThree", profile_url="https://facebook.com/u1", action_type="share", source="web", confidence=1.0, session_id="s_chain"),

        # User 2: Like + Comment ONLY (NO Share), comment="apple fresh"
        ShareProfile(name="User LikeComment", profile_url="https://facebook.com/u2", action_type="like", source="web", confidence=1.0, session_id="s_chain"),
        ShareProfile(name="User LikeComment", profile_url="https://facebook.com/u2", content="apple fresh", action_type="comment", source="web", confidence=1.0, session_id="s_chain"),

        # User 3: Comment + Share ONLY (NO Like), comment="mango sweet"
        ShareProfile(name="User CommentShare", profile_url="https://facebook.com/u3", content="mango sweet", action_type="comment", source="web", confidence=1.0, session_id="s_chain"),
        ShareProfile(name="User CommentShare", profile_url="https://facebook.com/u3", action_type="share", source="web", confidence=1.0, session_id="s_chain"),

        # User 4: Share ONLY, no comment
        ShareProfile(name="User ShareOnly", profile_url="https://facebook.com/u4", action_type="share", source="web", confidence=1.0, session_id="s_chain"),
    ]
    participants = ContestValidator.validate_participants(profiles)

    # Case A: Field 1 = Like, Op1 = AND, Field 2 = Comment, Field 3 = NOT SELECTED (act_f3_enabled=False)
    # Even if Op2 is "AND" and F3 is "share", because Field 3 is NOT selected, Field 3 is NOT applied!
    # Both User AllThree and User LikeComment must qualify!
    cfg_f3_off = AdvancedFilterConfig(
        use_action_chain=True,
        act_f1_enabled=True, act_f1_val="like",
        act_op1="AND",
        act_f2_enabled=True, act_f2_val="comment",
        act_op2="AND",
        act_f3_enabled=False, act_f3_val="share",  # Third field NOT selected -> ignored!
        quick_category="qualified",
    )
    qual_a, _, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_f3_off)
    assert {p.name for p in qual_a} == {"User AllThree", "User LikeComment"}

    # Case B: Field 1 = Like, Op1 = AND, Field 2 = Comment, Op2 = NOT, Field 3 = Share (ALL 3 SELECTED)
    # Means: (Like AND Comment) AND NOT Share -> ONLY User LikeComment qualifies!
    cfg_not_share = AdvancedFilterConfig(
        use_action_chain=True,
        act_f1_enabled=True, act_f1_val="like",
        act_op1="AND",
        act_f2_enabled=True, act_f2_val="comment",
        act_op2="NOT",
        act_f3_enabled=True, act_f3_val="share",
        quick_category="qualified",
    )
    qual_b, _, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_not_share)
    assert {p.name for p in qual_b} == {"User LikeComment"}

    # Case C: Field 1 = Comment, Op1 = AND, Field 2 = Like, Op2 = OR, Field 3 = Share
    # With act_group_right=True: Comment AND (Like OR Share) -> User AllThree, User LikeComment, User CommentShare
    cfg_group_right = AdvancedFilterConfig(
        use_action_chain=True,
        act_f1_enabled=True, act_f1_val="comment",
        act_op1="AND",
        act_f2_enabled=True, act_f2_val="like",
        act_op2="OR",
        act_f3_enabled=True, act_f3_val="share",
        act_group_right=True,
        quick_category="qualified",
    )
    qual_c, _, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_group_right)
    assert {p.name for p in qual_c} == {"User AllThree", "User LikeComment", "User CommentShare"}

    # Case D: Keyword 3-Field Chain where Field 3 is NOT selected (kw_f3_enabled=False)
    # K1="apple", Op1="AND", K2="fresh", Op2="NOT", K3="spam" (but K3 is OFF -> not applied!)
    # Both User AllThree ("apple fresh spam") and User LikeComment ("apple fresh") must qualify!
    cfg_kw_f3_off = AdvancedFilterConfig(
        use_action_chain=True,
        act_f1_enabled=True, act_f1_val="comment",
        act_f2_enabled=False, act_f3_enabled=False,
        use_keyword_chain=True,
        kw_f1_enabled=True, kw_f1_text="apple",
        kw_op1="AND",
        kw_f2_enabled=True, kw_f2_text="fresh",
        kw_op2="NOT",
        kw_f3_enabled=False, kw_f3_text="spam",  # K3 unchecked -> NOT applied!
        quick_category="qualified",
    )
    qual_d, _, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_kw_f3_off)
    assert {p.name for p in qual_d} == {"User AllThree", "User LikeComment"}

    # Now enable K3 ("spam") with Op2="NOT" -> User AllThree is excluded as Wrong Answer, only User LikeComment qualifies!
    cfg_kw_f3_on = AdvancedFilterConfig(
        use_action_chain=True,
        act_f1_enabled=True, act_f1_val="comment",
        act_f2_enabled=False, act_f3_enabled=False,
        use_keyword_chain=True,
        kw_f1_enabled=True, kw_f1_text="apple",
        kw_op1="AND",
        kw_f2_enabled=True, kw_f2_text="fresh",
        kw_op2="NOT",
        kw_f3_enabled=True, kw_f3_text="spam",   # K3 checked -> applied!
        quick_category="qualified",
    )
    qual_e, evals_e, counts_e = AdvancedFilterEngine.evaluate_all(participants, cfg_kw_f3_on)
    assert {p.name for p in qual_e} == {"User LikeComment"}
    assert counts_e["wrong"] >= 1

    # Case E: Right-grouped (K1 OR (K2 NOT K3)) -> User AllThree matches K1 ("apple") so must NOT be falsely flagged as Wrong Answer!
    cfg_kw_group_right = AdvancedFilterConfig(
        use_action_chain=True,
        act_f1_enabled=True, act_f1_val="comment",
        act_f2_enabled=False, act_f3_enabled=False,
        use_keyword_chain=True,
        kw_f1_enabled=True, kw_f1_text="apple",
        kw_op1="OR",
        kw_f2_enabled=True, kw_f2_text="mango",
        kw_op2="NOT",
        kw_f3_enabled=True, kw_f3_text="spam",
        kw_group_right=True,  # apple OR (mango NOT spam)
        quick_category="qualified",
    )
    qual_f, evals_f, _ = AdvancedFilterEngine.evaluate_all(participants, cfg_kw_group_right)
    assert {p.name for p in qual_f} == {"User AllThree", "User LikeComment", "User CommentShare"}
    for p in qual_f:
        ev = evals_f[p.normalized_key]
        assert ev.is_qualified_winner is True
        assert ev.matches_not_excluded is False
        assert "WRONG ANSWER" not in ev.reason_badge


def test_original_comment_preserved_without_english_translation(tmp_path):
    """
    Verifies that:
    1. When an initial auto-translated English comment is followed by the original Bangla comment
       (after clicking 'See original' / 'মূলটি দেখুন'), IncrementalContestAggregator replaces
       the English translation with the exact original Bangla comment.
    2. Android ProfileExtractor.find_see_original_tap_coords detects 'See original' and 'মূলটি দেখুন'
       buttons while ignoring 'See translation'.
    3. LotteryPrintExporter outputs translate='no' and class='notranslate' so browsers never
       translate original comments into English.
    """
    from app.utils.contest_validator import IncrementalContestAggregator
    from app.exporters.lottery_print_exporter import LotteryPrintExporter

    agg = IncrementalContestAggregator()
    # Pass 1: Auto-translated English text before 'See original' resolved
    agg.add_profile(
        ShareProfile(
            name="Mst Ambea Akhter",
            profile_url="https://www.facebook.com/profile.php?id=100078091213712",
            content="Peanuts are very nutritious food",
            action_type="comment",
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="s_orig",
        )
    )
    # Pass 2: Original Bangla comment after 'See original' resolved
    original_bangla = "খাই চিনা বাদাম (Peanuts) এটা অত্যন্ত পুষ্টিকর এবং সুস্বাদু খাবার"
    agg.add_profile(
        ShareProfile(
            name="Mst Ambea Akhter",
            profile_url="https://www.facebook.com/profile.php?id=100078091213712",
            content=original_bangla,
            action_type="comment",
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="s_orig",
        )
    )
    participants = agg.get_sorted_participants()
    assert len(participants) == 1
    assert participants[0].comment_texts == [original_bangla]

    # Verify Android 'See original' tap coordinate finder
    xml_with_see_original = """<?xml version="1.0" encoding="UTF-8"?>
    <hierarchy rotation="0">
      <androidx.recyclerview.widget.RecyclerView bounds="[0,200][1080,2100]" scrollable="true">
        <android.view.ViewGroup bounds="[0,250][1080,500]">
          <android.widget.TextView text="See original" bounds="[140,420][340,470]" />
          <android.widget.TextView text="মূলটি দেখুন" bounds="[140,520][340,570]" />
          <android.widget.TextView text="See translation" bounds="[140,620][340,670]" />
        </android.view.ViewGroup>
      </androidx.recyclerview.widget.RecyclerView>
    </hierarchy>
    """
    coords = ProfileExtractor.find_see_original_tap_coords(xml_with_see_original)
    assert coords == [(240, 445), (240, 545)]

    # Verify HTML exporter preserves exact Bangla comment and blocks browser auto-translation
    out_html = tmp_path / "tickets.html"
    assert LotteryPrintExporter.export_printable_tickets(participants, str(out_html)) is True
    html_text = out_html.read_text(encoding="utf-8")
    assert 'translate="no"' in html_text
    assert 'content="notranslate"' in html_text
    assert original_bangla in html_text
    assert "Peanuts are very nutritious food" not in html_text


def test_multi_day_daily_scraping_upsert_and_conflict_resolution():
    """
    Simulates a 4-day daily scraping schedule (Nov 2 -> Nov 3 -> Nov 4 -> Nov 5)
    and verifies the Upsert Rule ("If Found -> Auto-Update; If Not Found -> Create New"):
      1. Canonical Profile Link Supremacy across URL variants (/people/Name/UID vs /profile.php?id=UID),
         even when the user changes their profile photo or edits their display name across days.
      2. Photo Mismatch Tolerance when upgrading a unique-named Phone participant with a Web Profile URL.
      3. Strict Separation of Same-Name Users who have different Profile Links (or blank silhouette avatars).
      4. Multi-day CDN Avatar Asset Filename matching (when ?oh=...&oe=... rotates daily).
    """
    from app.utils.contest_validator import IncrementalContestAggregator
    from app.utils.url_normalizer import extract_canonical_identity_key, extract_avatar_asset_id

    assert extract_canonical_identity_key("https://www.facebook.com/people/Mst-Ambea-Akhter/100078091213712") == "uid:100078091213712"
    assert extract_canonical_identity_key("https://m.facebook.com/profile.php?id=100078091213712&comment_id=1") == "uid:100078091213712"
    assert extract_canonical_identity_key("https://www.facebook.com/people/Md-Rahim/pfbid02xyzABC") == "pfbid:pfbid02xyzabc"
    assert extract_canonical_identity_key("https://www.facebook.com/people/Md-Rahim-Updated/pfbid02xyzABC") == "pfbid:pfbid02xyzabc"
    assert extract_avatar_asset_id("https://scontent.fdac1-1.fna.fbcdn.net/v/t39.30808-1/432109876_123456789_987654321_n.jpg?oh=day1&oe=111") == "432109876_123456789_987654321_n.jpg"
    assert extract_avatar_asset_id("https://scontent.fdac1-1.fna.fbcdn.net/v/t39.30808-1/432109876_123456789_987654321_n.jpg?oh=day4&oe=999") == "432109876_123456789_987654321_n.jpg"

    agg = IncrementalContestAggregator()

    # Day 1 (Nov 2): Mst Ambea Akhter likes & comments (with /people/... URL and Photo Hash A)
    agg.add_profile(
        ShareProfile(
            name="Mst Ambea Akhter",
            profile_url="https://www.facebook.com/people/Mst-Ambea-Akhter/100078091213712",
            action_type="like",
            avatar_hash="1122334455667788",
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="nov2",
        )
    )
    agg.add_profile(
        ShareProfile(
            name="Mst Ambea Akhter",
            profile_url="https://www.facebook.com/people/Mst-Ambea-Akhter/100078091213712",
            content="খাই চিনা বাদাম...",
            action_type="comment",
            avatar_hash="1122334455667788",
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="nov2",
        )
    )

    # Day 2 (Nov 3): Tanvir Hasan scraped on Phone (no URL yet, Photo Hash X)
    agg.add_profile(
        ShareProfile(
            name="Tanvir Hasan",
            profile_url=None,
            action_type="share",
            avatar_hash="123456789abcdef0",
            source="facebook_android_ui",
            confidence=0.9,
            session_id="nov3",
        )
    )

    # Day 3 (Nov 4):
    # - Mst Ambea Akhter re-scraped with /profile.php?id=... URL, CHANGED avatar photo, and full expanded comment
    # - Tanvir Hasan scraped on Web WITH URL, but his photo changed/mismatched (Photo Hash Y)
    agg.add_profile(
        ShareProfile(
            name="Mst Ambea Akhter (Ambea)",
            profile_url="https://www.facebook.com/profile.php?id=100078091213712",
            content="খাই চিনা বাদাম (Peanuts) এটা অত্যন্ত পুষ্টিকর!",
            action_type="comment",
            avatar_hash="9988776655443322",  # Completely different photo on Nov 4!
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="nov4",
        )
    )
    agg.add_profile(
        ShareProfile(
            name="Tanvir Hasan",
            profile_url="https://www.facebook.com/tanvir.hasan.bd",
            action_type="like",
            avatar_hash="fedcba9876543210",  # Mismatched photo between Phone and Web!
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="nov4",
        )
    )

    # Day 4 (Nov 5):
    # - Mst Ambea Akhter shares the post -> becomes 3/3 Eligible!
    # - Two DIFFERENT people both named "Md Rahim" comment with different profile links & blank silhouette avatars
    agg.add_profile(
        ShareProfile(
            name="Mst Ambea Akhter",
            profile_url="https://www.facebook.com/profile.php?id=100078091213712",
            action_type="share",
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="nov5",
        )
    )
    agg.add_profile(
        ShareProfile(
            name="Md Rahim",
            profile_url="https://www.facebook.com/md.rahim.one",
            content="Contest entry 1",
            action_type="comment",
            avatar_hash="0000000000000000",
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="nov5",
        )
    )
    agg.add_profile(
        ShareProfile(
            name="Md Rahim",
            profile_url="https://www.facebook.com/md.rahim.two",
            content="Contest entry 2",
            action_type="comment",
            avatar_hash="0000000000000000",
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="nov5",
        )
    )

    participants = agg.get_sorted_participants()
    # Must be exactly 4 distinct participants: Mst Ambea Akhter (3/3), Tanvir Hasan (2/3), Md Rahim #1 (1/3), Md Rahim #2 (1/3)
    assert len(participants) == 4

    ambea = next(p for p in participants if "Ambea" in p.name)
    assert ambea.is_eligible is True
    assert ambea.profile_url == "https://www.facebook.com/profile.php?id=100078091213712"
    assert ambea.comment_texts == ["খাই চিনা বাদাম (Peanuts) এটা অত্যন্ত পুষ্টিকর!"]

    tanvir = next(p for p in participants if p.name == "Tanvir Hasan")
    assert tanvir.liked is True and tanvir.shared is True
    assert tanvir.profile_url == "https://www.facebook.com/tanvir.hasan.bd"

    rahims = [p for p in participants if p.name == "Md Rahim"]
    assert len(rahims) == 2
    assert {r.profile_url for r in rahims} == {
        "https://www.facebook.com/md.rahim.one",
        "https://www.facebook.com/md.rahim.two",
    }


def test_sync_profile_batch_worker_only_eligible_names_and_normalize_name():
    """
    Ensure ContestValidator._normalize_name, IncrementalContestAggregator._normalize_name,
    and ProfileSyncBatchWorker.run(only_eligible_names=...) work without AttributeError.
    """
    from app.gui.sync_profile_panel import ProfileSyncBatchWorker
    from app.utils.profile_sync_engine import ProfileSyncEngine
    from app.utils.contest_validator import IncrementalContestAggregator

    assert ContestValidator._normalize_name("  Mst Ambea Akhter profile picture  ") == "mst ambea akhter"
    assert IncrementalContestAggregator._normalize_name("  Tanvir Hasan Liked ") == "tanvir hasan"

    engine = ProfileSyncEngine()
    # Mock fetch_and_hash_web_avatar so no network call is made during test
    engine.fetch_and_hash_web_avatar = lambda url, timeout=6.0: ("123456789abcdef0", "/tmp/mock_avatar.png")

    profiles = [
        ShareProfile(
            name="Mst Ambea Akhter",
            profile_url="https://www.facebook.com/profile.php?id=100078091213712",
            share_url="https://scontent.fdac14-1.fna.fbcdn.net/v/t39.30808-1/458123456_10123456789012345_7890123456789012345_n.jpg",
            action_type="comment",
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="test",
        ),
        ShareProfile(
            name="Unqualified User",
            profile_url="https://www.facebook.com/unqualified.user",
            share_url="https://scontent.fdac14-1.fna.fbcdn.net/v/t39.30808-1/999999999_11111111111111111_2222222222222222222_n.jpg",
            action_type="comment",
            source="facebook_browser_extension",
            confidence=0.98,
            session_id="test",
        ),
    ]

    worker = ProfileSyncBatchWorker(
        sync_engine=engine,
        profiles=profiles,
        only_eligible_names={"mst ambea akhter"},
    )
    worker.run()

    assert profiles[0].avatar_hash == "123456789abcdef0"
    assert profiles[1].avatar_hash is None

















