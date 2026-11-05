(() => {
  if (typeof window.__FB_CONTEST_SCRAPER_TEARDOWN__ === "function") {
    try {
      window.__FB_CONTEST_SCRAPER_TEARDOWN__();
    } catch (e) {}
  }
  const stalePanel = document.getElementById("fb-contest-ext-panel");
  if (stalePanel) {
    stalePanel.remove();
  }
  window.__FB_CONTEST_SCRAPER_LOADED__ = true;

  function disableBrowserPageTranslation() {
    try {
      if (document.documentElement) {
        document.documentElement.setAttribute("translate", "no");
        document.documentElement.classList.add("notranslate");
      }
      if (document.body) {
        document.body.setAttribute("translate", "no");
        document.body.classList.add("notranslate");
      }
      if (document.head && !document.head.querySelector('meta[name="google"][content="notranslate"]')) {
        const meta = document.createElement("meta");
        meta.name = "google";
        meta.content = "notranslate";
        document.head.appendChild(meta);
      }
    } catch (e) {}
  }
  disableBrowserPageTranslation();

  const BATCH_PREFIX = "FB_CONTEST_BATCH_V1:";
  const BATCH_FLUSH_SIZE = 1;
  const MAX_CLIPBOARD_RING_BATCHES = 60;
  const MAX_CLIPBOARD_ITEMS = 5000;
  const MAX_CLIPBOARD_BYTES = 4500000;
  const MAX_HTTP_CHUNK_ITEMS = 120;

  let isRunning = false;
  let activeAction = "like";
  let stepTimeoutId = null;
  let emptyScrolls = 0;
  let scrollCount = 0;
  let batchesSent = 0;
  let clipboardBatchRing = [];
  let totalBatchesEvicted = 0;
  let lastExtractedElements = [];
  let lockedScrollEl = null;
  let lockedWindowRoot = null;
  let switchedToAllComments = false;
  let visitedReactionTabs = new Set();
  let speedProfile = "human";

  const SPEED_CONFIGS = {
    slow: {
      minWaitMs: 3800,
      maxWaitMs: 5200,
      scrollDurationMs: 900,
      viewportFraction: 0.36,
      minScrollPx: 160,
      maxScrollPx: 250,
      maxEmptyScrolls: 15
    },
    human: {
      minWaitMs: 2600,
      maxWaitMs: 3800,
      scrollDurationMs: 750,
      viewportFraction: 0.42,
      minScrollPx: 185,
      maxScrollPx: 285,
      maxEmptyScrolls: 12
    },
    normal: {
      minWaitMs: 1800,
      maxWaitMs: 2600,
      scrollDurationMs: 550,
      viewportFraction: 0.50,
      minScrollPx: 220,
      maxScrollPx: 340,
      maxEmptyScrolls: 11
    }
  };

  const store = {
    like: new Map(),
    comment: new Map(),
    share: new Map()
  };
  let unsentBatch = [];

  const NON_PROFILE_PREFIXES = [
    "/hashtag/", "/photo", "/photos/", "/videos/", "/watch", "/reel/", "/reels/",
    "/events/", "/marketplace/", "/gaming/", "/bookmarks", "/notifications",
    "/messages", "/friends", "/settings", "/help", "/policies", "/privacy",
    "/login", "/recover", "/sharer", "/share.php", "/shares/", "/stories/",
    "/ajax/", "/dialog/", "/ads/", "/business/", "/memories", "/saved", "/feeds",
    "/search", "/onthisday"
  ];

  const IGNORE_LABELS = new Set([
    "like", "liked", "love", "loved", "care", "cared", "haha", "wow", "sad", "angry",
    "reply", "share", "shared", "follow", "following", "add friend", "message",
    "most relevant", "all comments", "newest", "author", "top fan", "edited",
    "see more", "view more comments", "view previous comments", "write a comment…",
    "write a comment...", "people who reacted", "people who shared this", "all",
    "close", "back", "facebook", "home", "watch", "marketplace", "groups", "gaming",
    "menu", "notifications", "messenger", "account", "find friends", "see all",
    "cancel", "send", "shared with public", "public", "original audio", "see translation",
    "see original", "hide", "report", "copy link", "active", "online status indicator",
    "online status indicator active", "comment", "comments", "shares", "post", "posts",
    "photo", "photos", "video", "videos", "reel", "reels", "story", "stories", "sharer",
    "write an answer…", "write an answer...", "write a public comment…", "write a public comment...",
    "show attachment", "hide attachment", "অ্যাটাচমেন্ট দেখুন", "সবচেয়ে প্রাসঙ্গিক", "সব মন্তব্য",
    "সব কমেন্ট", "উত্তর দিন", "লাইক", "শেয়ার", "শেয়ার", "বন্ধু যোগ করুন", "ফলো করুন", "ফলো করছেন",
    "মেসেজ", "বন্ধু", "অনুরোধ বাতিল করুন", "লগ ইন", "লগ ইন করুন", "নতুন অ্যাকাউন্ট তৈরি করুন"
  ]);

  const UTILITY_DIALOG_ARIA_RE = /notification|messenger|chat|account|menu|your profile|settings|search facebook|create post|stories|reels|cookie|log in|sign up|login/i;
  const REACTION_SUFFIX_RE = /\s+(?:Liked|Loved|Cared|Haha|Wow|Sad|Angry)$/i;
  const PROFILE_PIC_NOISE_RE = /(?:'s\s+profile\s+(?:picture|photo)|\s+profile\s+(?:picture|photo).*|^profile\s+(?:picture|photo)\s+of\s+|^online\s+status\s+indicator\s*(?:active)?|-?এর\s+প্রোফাইল\s+(?:ছবি|ফটো)|^প্রোফাইল\s+(?:ছবি|ফটো)\s+)/i;
  const INLINE_META_SUFFIX_RE = /\s*[·•]\s*(?:\d+\s*(?:s|m|h|d|w|y|sec|min|hr|hrs|day|days|wk|wks|yr|yrs)\b|just now|yesterday|follow|following|1st|2nd|3rd|author|top fan|admin|moderator|rising contributor|top contributor|edited|ফলো করুন|ফলো করছেন|বন্ধু যোগ করুন|লেখক|টপ ফ্যান).*$/i;
  const TRAILING_TIME_RE = /\s+\d+\s*(?:s|m|h|d|w|y|sec|min|hr|hrs)\s*$/i;
  const COMMENT_ARIA_PREFIX_RE = /^(?:comment|reply)\s+by\s+(.+?)(?:\s+(?:about|almost|over|\d+|a\s+few|an?\s+|just\s+now|yesterday|on\s+|at\s+|\(|·|•).*)?$/i;
  const COMMENT_ARIA_BANGLA_RE = /^(.+?)(?:-এর\s+|\s+এর\s+)(?:মন্তব্য|উত্তর|কমেন্ট|রিপ্লাই)/i;

  function randomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function cleanText(s) {
    return (s || "").replace(/\u200b/g, "").replace(/\s+/g, " ").trim();
  }

  function cleanPersonName(rawName) {
    if (!rawName) return null;
    let s = cleanText(rawName);
    const mAriaEn = s.match(COMMENT_ARIA_PREFIX_RE);
    if (mAriaEn && mAriaEn[1]) {
      s = cleanText(mAriaEn[1]);
    } else {
      const mAriaBn = s.match(COMMENT_ARIA_BANGLA_RE);
      if (mAriaBn && mAriaBn[1]) {
        s = cleanText(mAriaBn[1]);
      }
    }
    s = s.replace(PROFILE_PIC_NOISE_RE, "").trim();
    s = s.replace(INLINE_META_SUFFIX_RE, "").trim();
    s = s.replace(REACTION_SUFFIX_RE, "").trim();
    s = s.replace(INLINE_META_SUFFIX_RE, "").trim();
    s = s.replace(TRAILING_TIME_RE, "").trim();
    if (s.endsWith("'s Post") || s.endsWith("’s Post") || s.endsWith("-এর পোস্ট")) return null;
    if (s.length < 2 || s.length > 70) return null;

    const low = s.toLowerCase();
    if (IGNORE_LABELS.has(low)) return null;
    if (
      low.includes("online status indicator") ||
      low.startsWith("profile photo of") ||
      low.startsWith("profile picture of") ||
      low.includes("mutual friend") ||
      low.includes("মিউচুয়াল ফ্রেন্ড") ||
      low.includes(" অভিন্ন বন্ধু") ||
      low.startsWith("works at ") ||
      low.startsWith("studied at ") ||
      low.startsWith("lives in ") ||
      low.startsWith("from ") ||
      low.startsWith("followed by ") ||
      low.startsWith("see original") ||
      low.startsWith("see translation") ||
      low.startsWith("comment as ") ||
      low.startsWith("reply to ") ||
      low.startsWith("log in") ||
      low.startsWith("sign up") ||
      low.startsWith("create new account") ||
      low.startsWith("forgot password")
    ) {
      return null;
    }
    if (/^(\d+\s*(?:s|m|h|d|w|y|sec|min|hr|hrs|day|days|wk|wks|yr|yrs)|just now|yesterday|\d+[KMB,.]?\s*(?:shares?|comments?|likes?|reactions?|views?|mutual.*)|\d+[KMB,.]?)$/i.test(low)) {
      return null;
    }
    if (
      low.startsWith("view more") ||
      low.startsWith("view previous") ||
      low.startsWith("people who") ||
      low.startsWith("shared with") ||
      low.startsWith("see all") ||
      low.startsWith("all reactions")
    ) {
      return null;
    }
    const letters = s.match(/[\p{L}\p{M}\u0980-\u09FF]/gu) || [];
    return letters.length >= 2 ? s : null;
  }

  function cleanProfileUrl(rawHref) {
    if (!rawHref) return null;
    let href = rawHref.trim();
    if (href.startsWith("#") || href.startsWith("javascript:")) return null;
    if (href.startsWith("/")) {
      href = "https://www.facebook.com" + href;
    }
    if (!href.toLowerCase().includes("facebook.com")) return null;

    let parsed;
    try {
      parsed = new URL(href);
    } catch (e) {
      return null;
    }

    const path = parsed.pathname || "/";
    const lowerPath = path.toLowerCase();
    if (lowerPath === "/" || lowerPath === "/home.php" || lowerPath === "/index.php") return null;
    for (const p of NON_PROFILE_PREFIXES) {
      if (lowerPath.startsWith(p)) return null;
    }

    const cleanLowerPath = lowerPath.replace(/\/+$/, "");
    const hasCommentId = parsed.searchParams.has("comment_id") || parsed.searchParams.has("reply_comment_id");

    /* Case 1a: /profile.php?id=1000... (Always a user profile, even if Facebook appended &comment_id=...) */
    if (cleanLowerPath === "/profile.php" || cleanLowerPath === "/user.php") {
      const uid = parsed.searchParams.get("id");
      if (uid && /^\d+$/.test(uid)) {
        return `https://www.facebook.com/profile.php?id=${uid}`;
      }
      return null;
    }

    /* Case 1b: /permalink.php?story_fbid=...&id=1000... or /story.php (Valid on Share cards, but reject if it's a comment_id timestamp) */
    if (cleanLowerPath === "/permalink.php" || cleanLowerPath === "/story.php") {
      if (hasCommentId) return null;
      const uid = parsed.searchParams.get("id");
      if (uid && /^\d+$/.test(uid)) {
        return `https://www.facebook.com/profile.php?id=${uid}`;
      }
      return null;
    }

    if (parsed.searchParams.has("story_fbid") || parsed.searchParams.has("fbid")) {
      return null;
    }

    /* Case 2: /people/<Name>/<id_or_pfbid> */
    const mPeople = path.match(/^\/people\/([^/]+)\/([^/?#]+)/i);
    if (mPeople) {
      const idOrToken = mPeople[2];
      if (/^\d+$/.test(idOrToken)) {
        return `https://www.facebook.com/profile.php?id=${idOrToken}`;
      }
      return `https://www.facebook.com/people/${mPeople[1]}/${idOrToken}`;
    }

    /* Case 2b: /p/<Name-or-Slug>-<uid> or /p/<slug> (Facebook professional / numeric-slug profiles) */
    const mPProfile = path.match(/^\/p\/([^/?#]+)/i);
    if (mPProfile) {
      const rawSlug = decodeURIComponent(mPProfile[1]).trim();
      if (/^\d{5,}$/.test(rawSlug)) {
        return `https://www.facebook.com/profile.php?id=${rawSlug}`;
      }
      const mTailUid = rawSlug.match(/-(\d{8,})$/);
      if (mTailUid) {
        return `https://www.facebook.com/profile.php?id=${mTailUid[1]}`;
      }
      return `https://www.facebook.com/p/${rawSlug}`;
    }

    /* Case 2c: /profile/<uid_or_username> or /user/<uid_or_username> */
    const mDirectProf = path.match(/^\/(?:profile|user)\/([^/?#]+)/i);
    if (mDirectProf) {
      const tok = decodeURIComponent(mDirectProf[1]).trim();
      if (/^\d{5,}$/.test(tok)) {
        return `https://www.facebook.com/profile.php?id=${tok}`;
      }
      return `https://www.facebook.com/${tok}`;
    }

    /* Case 2d: /pages/<Name>/<uid> or /pages/category/<cat>/<Name>/<uid> */
    const mPages = path.match(/^\/pages\/(?:category\/[^/]+\/)?([^/]+)\/(\d{5,})/i);
    if (mPages) {
      return `https://www.facebook.com/profile.php?id=${mPages[2]}`;
    }

    /* Case 3: /groups/<gid>/user/<uid> */
    const mGroupUser = path.match(/^\/groups\/[^/]+\/user\/([^/?#]+)/i);
    if (mGroupUser) {
      const uid = mGroupUser[1];
      if (/^\d+$/.test(uid)) {
        return `https://www.facebook.com/profile.php?id=${uid}`;
      }
      return `https://www.facebook.com/${uid}`;
    }

    /* Case 4: /<username> or /<username>/posts/... (sharer card links) */
    let segments = path.split("/").filter(Boolean);
    if (segments.length === 0) return null;

    if (segments.length >= 2) {
      const secondSeg = segments[1].toLowerCase();
      if (
        [
          "posts", "videos", "photos", "about", "reels",
          "friends", "followers", "following", "map", "mentions"
        ].includes(secondSeg)
      ) {
        if (hasCommentId) return null;
        segments = [segments[0]];
      } else {
        return null;
      }
    }

    const username = decodeURIComponent(segments[0]).trim();
    if (!username || username.endsWith(".php")) return null;
    if (IGNORE_LABELS.has(username.toLowerCase())) return null;
    if (/^\d{5,}$/.test(username)) {
      return `https://www.facebook.com/profile.php?id=${username}`;
    }

    return `https://www.facebook.com/${username}`;
  }

  function cleanSharedPostUrl(rawHref) {
    if (!rawHref) return null;
    let href = rawHref.trim();
    if (href.startsWith("#") || href.startsWith("javascript:")) return null;
    if (href.startsWith("/")) {
      href = "https://www.facebook.com" + href;
    }
    if (!href.toLowerCase().includes("facebook.com")) return null;

    let parsed;
    try {
      parsed = new URL(href);
    } catch (e) {
      return null;
    }

    if (parsed.searchParams.has("comment_id") || parsed.searchParams.has("reply_comment_id")) {
      return null;
    }

    const path = parsed.pathname || "/";
    const cleanLowerPath = path.toLowerCase().replace(/\/+$/, "");

    /* 1. /permalink.php?story_fbid=...&id=... or /story.php?story_fbid=...&id=... */
    if (cleanLowerPath === "/permalink.php" || cleanLowerPath === "/story.php") {
      const storyFbid = parsed.searchParams.get("story_fbid");
      const uid = parsed.searchParams.get("id");
      if (storyFbid && uid) {
        return `https://www.facebook.com/permalink.php?story_fbid=${encodeURIComponent(storyFbid)}&id=${encodeURIComponent(uid)}`;
      }
      if (storyFbid) {
        return `https://www.facebook.com/permalink.php?story_fbid=${encodeURIComponent(storyFbid)}`;
      }
      return null;
    }

    /* 2. /<username>/(posts|videos|activity)/<post_id_or_pfbid> */
    const mUserPost = path.match(/^\/([^/]+)\/(posts|videos|activity)\/([^/?#]+)/i);
    if (mUserPost) {
      return `https://www.facebook.com/${mUserPost[1]}/${mUserPost[2]}/${mUserPost[3]}`;
    }

    /* 3. /groups/<gid>/(posts|permalink)/<post_id> */
    const mGroupPost = path.match(/^\/groups\/([^/]+)\/(posts|permalink)\/([^/?#]+)/i);
    if (mGroupPost) {
      return `https://www.facebook.com/groups/${mGroupPost[1]}/${mGroupPost[2]}/${mGroupPost[3]}`;
    }

    /* 4. /share/p/<token> or /share/v/<token> or /share/<token> */
    const mShare = path.match(/^\/share\/(?:([pv])\/)?([^/?#]+)/i);
    if (mShare) {
      const kindSeg = mShare[1] ? `${mShare[1]}/` : "";
      return `https://www.facebook.com/share/${kindSeg}${mShare[2]}`;
    }

    /* 5. /photo.php?fbid=... or /photo/?fbid=... */
    if (cleanLowerPath === "/photo.php" || cleanLowerPath === "/photo") {
      const fbid = parsed.searchParams.get("fbid");
      if (fbid) {
        return `https://www.facebook.com/photo.php?fbid=${encodeURIComponent(fbid)}`;
      }
    }

    /* 6. /watch/?v=... */
    if (cleanLowerPath === "/watch") {
      const v = parsed.searchParams.get("v");
      if (v) {
        return `https://www.facebook.com/watch/?v=${encodeURIComponent(v)}`;
      }
    }

    return null;
  }

  function isInsideIgnoredChrome(el) {
    if (!el) return true;
    if (el.closest("#fb-contest-ext-panel")) return true;
    if (el.closest('[role="navigation"], [role="banner"], [role="complementary"]')) return true;
    const dlg = el.closest('div[role="dialog"]');
    if (dlg) {
      const aria = dlg.getAttribute("aria-label") || "";
      if (UTILITY_DIALOG_ARIA_RE.test(aria)) return true;
    }
    return false;
  }

  function triggerHoverHydration(container) {
    if (!container) return;
    const links = container.querySelectorAll('a, [role="link"]');
    for (const lnk of links) {
      try {
        lnk.dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
        lnk.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      } catch (e) {}
    }
  }

  function extractAvatarUrlFromContainer(container) {
    if (!container) return "";
    const svgImgs = container.querySelectorAll("svg image, image");
    for (const si of svgImgs) {
      const href = si.getAttribute("xlink:href") || si.getAttribute("href") || "";
      if (href && href.startsWith("http")) return href;
    }
    const imgs = container.querySelectorAll("img[src]");
    for (const im of imgs) {
      const src = im.getAttribute("src") || "";
      const alt = (im.getAttribute("alt") || "").toLowerCase();
      if (
        src.startsWith("http") &&
        !src.includes("emoji.php") &&
        !normalizeReactionType(alt) &&
        alt.length !== 1 &&
        alt.length !== 2
      ) {
        return src;
      }
    }
    return "";
  }

  function countDistinctAvatars(container) {
    if (!container) return 0;
    const seenUrls = new Set();
    let count = 0;
    const svgImgs = container.querySelectorAll("svg image, image");
    for (const si of svgImgs) {
      const href = si.getAttribute("xlink:href") || si.getAttribute("href") || "";
      if (href && href.startsWith("http")) {
        if (!seenUrls.has(href)) {
          seenUrls.add(href);
          count += 1;
        }
      }
    }
    if (count > 0) return count;
    const imgs = container.querySelectorAll("img[src]");
    for (const im of imgs) {
      const src = im.getAttribute("src") || "";
      const alt = (im.getAttribute("alt") || "").toLowerCase();
      if (
        src.startsWith("http") &&
        !src.includes("emoji.php") &&
        !normalizeReactionType(alt) &&
        alt.length !== 1 &&
        alt.length !== 2
      ) {
        const w = im.naturalWidth || im.width || 32;
        if (w >= 24 && !seenUrls.has(src)) {
          seenUrls.add(src);
          count += 1;
        }
      }
    }
    return count;
  }

  function extractNameFromAnchor(a) {
    if (!a) return null;
    const candidates = [];

    const innerNodes = a.querySelectorAll("h2, h3, h4, strong, span[dir='auto'], span");
    for (const n of innerNodes) {
      const txt = n.innerText || n.textContent;
      if (txt) candidates.push(txt);
    }

    candidates.push(a.innerText, a.textContent, a.getAttribute("aria-label"), a.getAttribute("title"));

    const mediaNodes = a.querySelectorAll("svg[aria-label], img[alt], image[aria-label]");
    for (const m of mediaNodes) {
      candidates.push(m.getAttribute("aria-label") || m.getAttribute("alt"));
    }

    for (const c of candidates) {
      if (!c) continue;
      const lines = String(c).split(/\r?\n/);
      for (const line of lines) {
        const validLine = cleanPersonName(line);
        if (validLine) return validLine;
      }
      const validFull = cleanPersonName(c);
      if (validFull) return validFull;
    }
    return null;
  }

  function classifyDialogWindow(dlg) {
    if (!dlg || dlg.id === "fb-contest-ext-panel") return "utility";
    const aria = cleanText(dlg.getAttribute("aria-label") || "").toLowerCase();
    if (UTILITY_DIALOG_ARIA_RE.test(aria)) return "utility";

    const rect = dlg.getBoundingClientRect();
    if (rect.width < 240 || rect.height < 160) return "utility";
    if (rect.bottom <= 20 || rect.top >= window.innerHeight - 20) return "utility";

    const belongsToThisDialog = (node) => node.closest('div[role="dialog"]') === dlg;

    /* Ignore Login / Signup / Cookie consent overlays in logged-out or incognito browsers */
    const hasPasswordOrLoginInput = Array.from(
      dlg.querySelectorAll('input[type="password"], input[name="pass"], input[name="email"]')
    ).some(belongsToThisDialog);
    if (hasPasswordOrLoginInput) return "utility";

    const headings = Array.from(dlg.querySelectorAll('h1, h2, h3, [role="heading"], span[dir="auto"]'))
      .filter(belongsToThisDialog)
      .slice(0, 22);
    for (const h of headings) {
      const hTxt = cleanText(h.innerText || h.textContent).toLowerCase();
      if (
        hTxt.includes("log in or sign up") ||
        hTxt.includes("see more on facebook") ||
        hTxt === "log in to facebook" ||
        hTxt === "create new account" ||
        hTxt.includes("allow all cookies") ||
        hTxt.includes("লগ ইন করুন") ||
        hTxt.includes("নতুন অ্যাকাউন্ট তৈরি করুন")
      ) {
        return "utility";
      }
    }

    if (
      aria.includes("people who shared") ||
      aria.includes("who shared this") ||
      aria.includes("যারা শেয়ার") ||
      aria.includes("যারা শেয়ার")
    ) {
      return "share";
    }
    if (
      aria.includes("people who reacted") ||
      aria === "reactions" ||
      aria.includes("যারা প্রতিক্রিয়া") ||
      aria.includes("যারা প্রতিক্রিয়া")
    ) {
      return "like";
    }

    for (const h of headings) {
      const hTxt = cleanText(h.innerText || h.textContent).toLowerCase();
      if (
        hTxt === "people who shared this" ||
        hTxt === "who shared this" ||
        hTxt.includes("যারা এটি শেয়ার") ||
        hTxt.includes("যারা এটি শেয়ার")
      ) {
        return "share";
      }
      if (
        hTxt === "people who reacted" ||
        hTxt === "reactions" ||
        hTxt.includes("যারা প্রতিক্রিয়া জানিয়েছেন") ||
        hTxt.includes("যারা প্রতিক্রিয়া জানিয়েছেন")
      ) {
        return "like";
      }
    }

    const tabs = Array.from(dlg.querySelectorAll('[role="tab"]')).filter(belongsToThisDialog);
    if (tabs.length >= 2) {
      const tabTexts = tabs.map((t) => cleanText(t.innerText || t.getAttribute("aria-label") || "").toLowerCase());
      if (
        tabTexts.some(
          (t) =>
            t === "all" ||
            t.startsWith("all ") ||
            t === "সব" ||
            t.startsWith("সব ") ||
            /\d/.test(t) ||
            t.includes("reaction") ||
            t.includes("like") ||
            t.includes("love") ||
            t.includes("প্রতিক্রি")
        )
      ) {
        return "like";
      }
    }

    const replyButtons = Array.from(dlg.querySelectorAll('div[role="button"], span[role="button"], span')).filter(
      (b) => {
        if (!belongsToThisDialog(b) || b.children.length > 0) return false;
        const bt = cleanText(b.textContent).toLowerCase();
        return bt === "reply" || bt === "উত্তর দিন";
      }
    );

    const commentIdLinks = Array.from(
      dlg.querySelectorAll('a[href*="comment_id="], a[href*="reply_comment_id="]')
    ).filter(belongsToThisDialog);

    const commentArticles = Array.from(dlg.querySelectorAll('div[role="article"]')).filter((art) => {
      if (!belongsToThisDialog(art)) return false;
      const aLabel = cleanText(art.getAttribute("aria-label") || "").toLowerCase();
      return (
        aLabel.startsWith("comment by") ||
        aLabel.startsWith("reply by") ||
        aLabel.includes("মন্তব্য") ||
        aLabel.includes("কমেন্ট")
      );
    });

    const hasCommentSortFilter = headings.some((h) => {
      const t = cleanText(h.innerText || h.textContent).toLowerCase();
      return (
        t === "most relevant" ||
        t === "all comments" ||
        t === "newest" ||
        t === "সবচেয়ে প্রাসঙ্গিক" ||
        t === "সবচেয়ে প্রাসঙ্গিক" ||
        t === "সব মন্তব্য" ||
        t === "সব কমেন্ট"
      );
    });

    const textboxes = Array.from(dlg.querySelectorAll('[role="textbox"], [contenteditable="true"]')).filter(belongsToThisDialog);
    const hasCommentComposer = textboxes.some((tb) => {
      const placeholder = cleanText(
        tb.getAttribute("aria-label") || tb.getAttribute("aria-placeholder") || tb.getAttribute("placeholder") || ""
      ).toLowerCase();
      return (
        placeholder.includes("comment") ||
        placeholder.includes("reply") ||
        placeholder.includes("answer") ||
        placeholder.includes("মন্তব্য") ||
        placeholder.includes("কমেন্ট")
      );
    });

    const hasPostReactionToolbar = Array.from(dlg.querySelectorAll('[role="toolbar"]'))
      .filter(belongsToThisDialog)
      .some((tb) => {
        const tbAria = cleanText(tb.getAttribute("aria-label") || "").toLowerCase();
        return (
          tbAria.includes("reacted") ||
          tbAria.includes("reaction") ||
          tbAria.includes("প্রতিক্রিয়া") ||
          tbAria.includes("প্রতিক্রিয়া")
        );
      });

    if (
      replyButtons.length >= 1 ||
      commentIdLinks.length >= 1 ||
      commentArticles.length >= 1 ||
      hasCommentSortFilter ||
      hasCommentComposer ||
      hasPostReactionToolbar ||
      aria.endsWith("'s post") ||
      aria.endsWith("’s post") ||
      aria.includes("-এর পোস্ট")
    ) {
      return "comment";
    }

    /* Exclude comment timestamp links (comment_id=) when counting post/share permalinks! */
    const postPermalinkLinks = Array.from(
      dlg.querySelectorAll('a[href*="/posts/"], a[href*="story_fbid="], a[href*="/permalink.php"]')
    ).filter((a) => {
      if (!belongsToThisDialog(a)) return false;
      const h = (a.getAttribute("href") || "").toLowerCase();
      return !h.includes("comment_id=") && !h.includes("reply_comment_id=");
    });

    const actionButtons = Array.from(dlg.querySelectorAll('div[role="button"], span[role="button"]'))
      .filter(belongsToThisDialog)
      .map((b) => cleanText(b.innerText || b.getAttribute("aria-label") || "").toLowerCase());

    const addFriendOrFollowCount = actionButtons.filter(
      (txt) =>
        txt === "add friend" ||
        txt === "follow" ||
        txt === "following" ||
        txt === "message" ||
        txt === "বন্ধু যোগ করুন" ||
        txt === "ফলো করুন" ||
        txt === "ফলো করছেন" ||
        txt === "মেসেজ"
    ).length;

    const shareIndicators = Array.from(dlg.querySelectorAll('[aria-label*="Shared with"], [aria-label*="Public"]')).filter(
      belongsToThisDialog
    ).length;

    if (postPermalinkLinks.length >= 2 || shareIndicators >= 2) {
      return "share";
    }

    if (addFriendOrFollowCount >= 2 || tabs.length >= 1) {
      return "like";
    }

    const profileLinks = Array.from(dlg.querySelectorAll("a[href]")).filter(
      (a) => belongsToThisDialog(a) && cleanProfileUrl(a.getAttribute("href"))
    );
    if (profileLinks.length >= 2 && postPermalinkLinks.length === 0 && rect.width <= 720) {
      return "like";
    }

    if (profileLinks.length >= 2 && postPermalinkLinks.length >= 1) {
      return "share";
    }

    return "unknown";
  }

  function getClassifiedDialogs() {
    const allDialogs = Array.from(document.querySelectorAll('div[role="dialog"]'));
    const results = [];
    for (const d of allDialogs) {
      const kind = classifyDialogWindow(d);
      if (kind !== "utility") {
        results.push({ el: d, kind });
      }
    }
    return results;
  }

  function tryCloseDialogElement(dlg) {
    if (!dlg) return false;
    const closeBtns = dlg.querySelectorAll(
      '[aria-label="Close"], [aria-label="বন্ধ করুন"], div[role="button"][aria-label*="Close" i]'
    );
    for (const cb of closeBtns) {
      if (cb.closest('div[role="dialog"]') === dlg) {
        try {
          cb.click();
          return true;
        } catch (e) {}
      }
    }
    return false;
  }

  function tryAutoOpenPopupForAction(actionType) {
    const dialogs = getClassifiedDialogs();
    const commentDialog = [...dialogs].reverse().find((d) => d.kind === "comment");
    const searchRoot = commentDialog ? commentDialog.el : document.body;

    if (actionType === "like") {
      /* 1. Check reaction summary toolbars and adjacent total count buttons (e.g. role="toolbar" aria-label="See who reacted to this") */
      const toolbars = Array.from(searchRoot.querySelectorAll('[role="toolbar"]'));
      for (const tb of toolbars) {
        if (isInsideIgnoredChrome(tb)) continue;
        const tbAria = cleanText(tb.getAttribute("aria-label") || "").toLowerCase();
        if (
          tbAria.includes("reacted") ||
          tbAria.includes("reaction") ||
          tbAria.includes("প্রতিক্রিয়া") ||
          tbAria.includes("প্রতিক্রিয়া")
        ) {
          /* First check if there is a sibling total reaction count button right next to the toolbar in the UFI bar */
          const ufiRow = tb.parentElement ? tb.parentElement.parentElement || tb.parentElement : tb;
          const siblingBtns = Array.from(ufiRow.querySelectorAll('div[role="button"], span[role="button"]')).filter(
            (b) => !tb.contains(b)
          );
          for (const sb of siblingBtns) {
            const sbTxt = cleanText(sb.innerText || sb.textContent || "");
            if (/^\d+[kmb,.]*$/i.test(sbTxt) || /others|reactions|প্রতিক্রি/i.test(sbTxt)) {
              try {
                sb.click();
                return true;
              } catch (e) {}
            }
          }
          const btn = tb.querySelector('div[role="button"], span[role="button"]') || tb;
          try {
            btn.click();
            return true;
          } catch (e) {}
        }
      }

      /* 2. Check all clickable buttons/links for reaction counts or aria labels */
      const clickables = Array.from(
        searchRoot.querySelectorAll('div[role="button"], span[role="button"], a[role="link"], span[aria-label]')
      );
      for (const el of clickables) {
        if (isInsideIgnoredChrome(el)) continue;
        const aria = cleanText(el.getAttribute("aria-label") || "").toLowerCase();
        const txt = cleanText(el.innerText || el.textContent).toLowerCase();
        if (
          aria.startsWith("all reactions:") ||
          aria.startsWith("see who reacted") ||
          aria.includes("people who reacted") ||
          aria.startsWith("like:") ||
          aria.startsWith("love:") ||
          aria.startsWith("care:") ||
          aria.startsWith("haha:") ||
          aria.startsWith("wow:") ||
          aria.startsWith("sad:") ||
          aria.startsWith("angry:") ||
          aria.includes("প্রতিক্রিয়া") ||
          aria.includes("প্রতিক্রিয়া") ||
          /^\d+[kmb,.]*\s+reactions?$/i.test(txt) ||
          /^(?:you\s+and\s+|.+?\s+and\s+)\d+[kmb,.]*\s+others?$/i.test(txt) ||
          /^\d+[kmb,.]*টি\s+প্রতিক্রি[য়য়]া$/i.test(txt)
        ) {
          try {
            const target = el.closest('div[role="button"], span[role="button"], a[role="link"]') || el;
            target.click();
            return true;
          } catch (e) {}
        }
      }
    } else if (actionType === "share") {
      const clickables = Array.from(
        searchRoot.querySelectorAll('div[role="button"], span[role="button"], a[role="link"]')
      );
      for (const el of clickables) {
        if (isInsideIgnoredChrome(el)) continue;
        const aria = cleanText(el.getAttribute("aria-label") || "").toLowerCase();
        const txt = cleanText(el.innerText || el.textContent).toLowerCase();
        if (
          /^\d+[kmb,.]*\s+shares?$/i.test(txt) ||
          /^\d+[kmb,.]*\s+shares?$/i.test(aria) ||
          aria.includes("people who shared") ||
          txt.includes("টি শেয়ার") ||
          txt.includes("টি শেয়ার")
        ) {
          try {
            el.click();
            return true;
          } catch (e) {}
        }
      }
    }
    return false;
  }

  function resolveTargetWindow(actionType) {
    const dialogs = getClassifiedDialogs();
    const mainEl = document.querySelector('[role="main"]') || document.body;

    if (actionType === "like") {
      for (let i = dialogs.length - 1; i >= 0; i--) {
        if (dialogs[i].kind === "like") {
          return { root: dialogs[i].el, kind: "like_dialog", label: "👍 Reactions Popup Modal" };
        }
      }
      for (let i = dialogs.length - 1; i >= 0; i--) {
        if (dialogs[i].kind === "unknown") {
          return { root: dialogs[i].el, kind: "like_dialog", label: "👍 Reactions Popup Modal" };
        }
      }
      if (/\/ufi\/reaction\//i.test(window.location.href)) {
        return { root: mainEl, kind: "like_page", label: "👍 Reactions Page View" };
      }
      return null;
    }

    if (actionType === "share") {
      for (let i = dialogs.length - 1; i >= 0; i--) {
        if (dialogs[i].kind === "share") {
          return { root: dialogs[i].el, kind: "share_dialog", label: "🔄 Shares Popup Modal" };
        }
      }
      for (let i = dialogs.length - 1; i >= 0; i--) {
        if (dialogs[i].kind === "unknown") {
          return { root: dialogs[i].el, kind: "share_dialog", label: "🔄 Shares Popup Modal" };
        }
      }
      if (/\/shares\/view/i.test(window.location.href)) {
        return { root: mainEl, kind: "share_page", label: "🔄 Shares Page View" };
      }
      return null;
    }

    if (actionType === "comment") {
      /* If a Reactions or Shares popup is sitting on top of the post from Step 1/3, auto-close it so Comments can be scraped immediately! */
      if (dialogs.length > 0) {
        const topDlg = dialogs[dialogs.length - 1];
        if (topDlg.kind === "like" || topDlg.kind === "share") {
          tryCloseDialogElement(topDlg.el);
        }
      }
      const commentDialogs = dialogs.filter((d) => d.kind === "comment");
      if (commentDialogs.length > 0) {
        commentDialogs.sort((a, b) => {
          const ra = a.el.getBoundingClientRect();
          const rb = b.el.getBoundingClientRect();
          return rb.width * rb.height - ra.width * rb.height;
        });
        return {
          root: commentDialogs[0].el,
          kind: "comment_dialog",
          label: "💬 Post Comments Modal",
          blockedByPopup: null
        };
      }
      const nonPopupDialogs = dialogs.filter((d) => d.kind !== "like" && d.kind !== "share");
      if (nonPopupDialogs.length > 0) {
        return {
          root: nonPopupDialogs[nonPopupDialogs.length - 1].el,
          kind: "comment_dialog",
          label: "💬 Active Dialog Modal",
          blockedByPopup: null
        };
      }
      return { root: mainEl, kind: "comment_page", label: "💬 Page Comments Section" };
    }

    return null;
  }

  function hasVisibleLoadingSpinner(targetRoot) {
    const scope = targetRoot || document.body;
    const spinners = scope.querySelectorAll(
      '[role="progressbar"], [aria-busy="true"], [data-visualcompletion="loading-state"]'
    );
    for (const sp of spinners) {
      if (isInsideIgnoredChrome(sp)) continue;
      const rect = sp.getBoundingClientRect();
      if (rect.width > 8 && rect.height > 8 && rect.top >= 0 && rect.bottom <= window.innerHeight + 80) {
        return true;
      }
    }
    return false;
  }

  async function trySwitchToAllComments(root) {
    if (switchedToAllComments) return false;
    const scope = root || document.body;
    const filterButtons = scope.querySelectorAll('div[role="button"], span[role="button"], span[dir="auto"]');
    for (const btn of filterButtons) {
      if (isInsideIgnoredChrome(btn)) continue;
      const txt = cleanText(btn.innerText || btn.textContent).toLowerCase();
      if (
        txt === "most relevant" ||
        txt === "newest" ||
        txt === "সবচেয়ে প্রাসঙ্গিক" ||
        txt === "সবচেয়ে প্রাসঙ্গিক" ||
        txt === "নতুন"
      ) {
        try {
          const clickTarget = btn.closest('div[role="button"], span[role="button"]') || btn;
          clickTarget.click();
          switchedToAllComments = true;
          updateUIStatus("Switching comment filter from 'Most relevant' to 'All comments'...");
          await sleep(1100);
          const menuItems = document.querySelectorAll(
            'div[role="menuitem"], div[role="menuitemradio"], div[role="option"], div[role="button"], span'
          );
          for (const mi of menuItems) {
            const mTxt = cleanText(mi.innerText || mi.textContent).toLowerCase();
            if (
              mTxt === "all comments" ||
              mTxt.startsWith("all comments ") ||
              mTxt.includes("show all comments, including potential spam") ||
              mTxt === "সব মন্তব্য" ||
              mTxt.startsWith("সব মন্তব্য ") ||
              mTxt === "সব কমেন্ট" ||
              mTxt.startsWith("সব কমেন্ট ")
            ) {
              mi.click();
              await sleep(1800);
              return true;
            }
          }
        } catch (e) {}
        break;
      }
    }
    if (scrollCount >= 2) {
      switchedToAllComments = true;
    }
    return false;
  }

  function clickSeeOriginalAndSeeMore(root) {
    if (!root) return { clickedOriginal: 0, clickedSeeMore: 0 };
    let clickedOriginal = 0;
    let clickedSeeMore = 0;
    const buttons = root.querySelectorAll('div[role="button"], span[role="button"], a[role="button"], span[dir="auto"]');
    for (const btn of buttons) {
      if (isInsideIgnoredChrome(btn)) continue;
      const txt = cleanText(btn.innerText || btn.textContent).toLowerCase();
      const aria = cleanText(btn.getAttribute("aria-label") || "").toLowerCase();
      const label = txt || aria;
      if (!label) continue;

      /* Strictly NEVER click "See translation" ("অনুবাদ দেখুন") */
      if (label.startsWith("see translation") || label === "অনুবাদ দেখুন") {
        continue;
      }

      const isSeeOriginal =
        label === "see original" ||
        label.startsWith("see original ") ||
        label.startsWith("see original(") ||
        label === "মূলটি দেখুন" ||
        label === "মূল লেখাটি দেখুন" ||
        label === "hide translation" ||
        label === "অনুবাদ লুকান";

      const isSeeMore = /^see\s+more$/i.test(label) || label === "আরও দেখুন";

      if (isSeeOriginal && btn.dataset.fbOriginalClicked !== "1") {
        const targetClickEl = btn.closest('div[role="button"], span[role="button"], a[role="button"]') || btn;
        const rect = targetClickEl.getBoundingClientRect();
        if (rect.width > 3 && rect.height > 3) {
          try {
            targetClickEl.click();
            btn.dataset.fbOriginalClicked = "1";
            clickedOriginal += 1;
          } catch (e) {}
        }
      } else if (isSeeMore && btn.dataset.fbExpandClicked !== "1") {
        const targetClickEl = btn.closest('div[role="button"], span[role="button"], a[role="button"]') || btn;
        const rect = targetClickEl.getBoundingClientRect();
        if (rect.width > 3 && rect.height > 3) {
          try {
            targetClickEl.click();
            btn.dataset.fbExpandClicked = "1";
            clickedSeeMore += 1;
          } catch (e) {}
        }
      }
    }
    return { clickedOriginal, clickedSeeMore };
  }

  async function ensureOriginalCommentsRevealed(root) {
    if (!root) return false;
    const pass1 = clickSeeOriginalAndSeeMore(root);
    if (pass1.clickedOriginal > 0 || pass1.clickedSeeMore > 0) {
      await sleep(520);
      const pass2 = clickSeeOriginalAndSeeMore(root);
      if (pass2.clickedOriginal > 0 || pass2.clickedSeeMore > 0) {
        await sleep(420);
      }
      return true;
    }
    return false;
  }

  function autoExpandComments(root) {
    let clickedExpand = false;
    const rev = clickSeeOriginalAndSeeMore(root);
    if (rev.clickedOriginal > 0 || rev.clickedSeeMore > 0) {
      clickedExpand = true;
    }
    const buttons = root.querySelectorAll('div[role="button"], span[role="button"], span[dir="auto"]');
    for (const btn of buttons) {
      if (isInsideIgnoredChrome(btn)) continue;
      if (btn.dataset.fbExpandClicked === "1") continue;
      const txt = cleanText(btn.innerText || btn.textContent).toLowerCase();
      if (txt.startsWith("see translation") || txt === "অনুবাদ দেখুন") continue;
      const isPaginationExpand =
        txt.startsWith("view more comments") ||
        txt.startsWith("view previous comments") ||
        txt.startsWith("view all ") ||
        txt.includes("more comments") ||
        txt.includes("previous comments") ||
        txt.includes("more replies") ||
        txt.includes("previous replies") ||
        /^\d+\s+replies$/i.test(txt) ||
        /^view\s+all\s+\d+\s+replies/i.test(txt) ||
        /^view\s+\d+\s+(?:more|previous)/i.test(txt) ||
        txt.includes("আরও মন্তব্য দেখুন") ||
        txt.includes("পূর্ববর্তী মন্তব্য") ||
        txt.includes("উত্তর দেখুন");

      if (isPaginationExpand) {
        const targetClickEl = btn.closest('div[role="button"], span[role="button"]') || btn;
        const rect = targetClickEl.getBoundingClientRect();
        if (rect.width > 5 && rect.height > 5) {
          try {
            if (rect.top < 0 || rect.bottom > window.innerHeight) {
              targetClickEl.scrollIntoView({ block: "center", behavior: "instant" });
            }
            targetClickEl.click();
            clickedExpand = true;
            break;
          } catch (e) {}
        }
      }
    }
    return clickedExpand;
  }

  function isNoiseCommentBodyLine(text, authorName, isButtonOrReactionNode = false) {
    if (!text) return true;
    const low = text.toLowerCase();
    if (authorName && low === authorName.toLowerCase()) return true;
    if (IGNORE_LABELS.has(low)) return true;
    if (
      low.startsWith("see original") ||
      low.startsWith("see translation") ||
      low.startsWith("hide translation") ||
      low.startsWith("rate this translation") ||
      low.startsWith("translated from ") ||
      low.startsWith("automatically translated") ||
      low === "মূলটি দেখুন" ||
      low === "মূল লেখাটি দেখুন" ||
      low === "অনুবাদ দেখুন" ||
      low === "অনুবাদ লুকান" ||
      low.startsWith("comment as ") ||
      low.startsWith("write a ") ||
      low.startsWith("replied to ") ||
      low.startsWith("reply to ") ||
      low.startsWith("view ") ||
      low.endsWith("'s post") ||
      low.endsWith("’s post") ||
      low.endsWith("-এর পোস্ট") ||
      low === "top fan" ||
      low === "author" ||
      low === "by author" ||
      low === "liked by author" ||
      low === "loved by author" ||
      low === "giphy" ||
      low === "sticker" ||
      low === "edited"
    ) {
      return true;
    }
    if (/^(\d+\s*(?:s|m|h|d|w|y|sec|min|hr|hrs|day|days|wk|wks|yr|yrs)|just now|yesterday)$/i.test(low)) {
      return true;
    }
    if (isButtonOrReactionNode && /^\d+[KMB,.]?$/i.test(low)) {
      return true;
    }
    if (/^[·•\s]+\d+\s*(?:s|m|h|d|w|y)/i.test(low)) {
      return true;
    }
    return false;
  }

  /**
   * Counts ONLY innermost leaf elements whose text is "Reply" (or Bangla "উত্তর দিন")
   * so a single Reply button always counts as 1 (never 3 or 4 from nested spans!).
   */
  function countLeafReplyNodes(container) {
    let count = 0;
    const spans = container.querySelectorAll("span, div[role='button']");
    for (const s of spans) {
      if (s.children.length > 0) continue;
      const t = cleanText(s.textContent).toLowerCase();
      if (t === "reply" || t === "উত্তর দিন") {
        count += 1;
      }
    }
    return count;
  }

  /**
   * Parses a single comment row DOM container (whether found via `<a href>`, a leaf `"Reply"` button,
   * `<div role="article">`, or a `comment_id=` timestamp link!)
   * and returns `{ name, url, avatar_url, content, action_type: "comment" }`.
   * Excludes any nested child `<div role="article">` (replies inside a parent comment) so parent comments
   * with replies never mix their links or text with nested replies, and prevents `@mention` links inside
   * a comment paragraph from overwriting the comment author!
   */
  function extractCommentFromSingleRowContainer(rowEl, modalOwnerNameLower = "") {
    if (!rowEl) return null;
    triggerHoverHydration(rowEl);

    const isInsideNestedCommentArticle = (node) => {
      if (!node || node === rowEl) return false;
      const closestArt = node.closest('div[role="article"]');
      return Boolean(closestArt && closestArt !== rowEl && rowEl.contains(closestArt));
    };

    let authorUrl = "";
    let authorName = "";

    /* 0. Check if rowEl itself (or its closest comment article) has aria-label="Comment by <Name> ..." */
    const ownAria = cleanText(rowEl.getAttribute("aria-label") || "");
    if (ownAria) {
      const mEn = ownAria.match(COMMENT_ARIA_PREFIX_RE);
      const mBn = ownAria.match(COMMENT_ARIA_BANGLA_RE);
      const candAriaName = cleanPersonName((mEn && mEn[1]) || (mBn && mBn[1]) || "");
      if (candAriaName) {
        authorName = candAriaName;
      }
    }

    /* Identify the primary comment body blocks (div[dir="auto"]) belonging to this comment (excluding nested replies) */
    const bodyDirBlocks = Array.from(rowEl.querySelectorAll('div[dir="auto"]')).filter(
      (b) => !isInsideNestedCommentArticle(b)
    );
    const firstBodyBlock = bodyDirBlocks.length > 0 ? bodyDirBlocks[0] : null;

    const isInlineMentionLinkInsideBody = (a) => {
      const parentBodyDiv = a.closest('div[dir="auto"]');
      if (!parentBodyDiv || !rowEl.contains(parentBodyDiv)) return false;
      const divTxt = cleanText(parentBodyDiv.innerText || parentBodyDiv.textContent || "");
      const aTxt = cleanText(a.innerText || a.textContent || "");
      /* If the div[dir="auto"] has surrounding comment words around the link, or if a preceding header already exists before this div[dir="auto"], it's a @mention inside the comment body! */
      if (divTxt.length > aTxt.length + 2) return true;
      if (firstBodyBlock && parentBodyDiv !== firstBodyBlock) return true;
      return false;
    };

    /* 1. Try finding author URL and Name from header <a href> inside rowEl (excluding nested replies & inline @mentions) */
    const links = Array.from(rowEl.querySelectorAll("a[href]")).filter(
      (a) => !isInsideNestedCommentArticle(a)
    );
    for (const a of links) {
      const rawHref = a.getAttribute("href") || a.href || "";
      const cUrl = cleanProfileUrl(rawHref);
      if (!cUrl) continue;
      if (isInlineMentionLinkInsideBody(a)) continue;
      /* If this link appears AFTER the first comment body block (e.g. a link in the footer or reaction bar), skip it as author */
      if (
        firstBodyBlock &&
        !firstBodyBlock.contains(a) &&
        Boolean(firstBodyBlock.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING)
      ) {
        continue;
      }
      if (!authorUrl) authorUrl = cUrl;
      const candName = extractNameFromAnchor(a);
      if (candName) {
        if (!authorName) authorName = candName;
        authorUrl = cUrl;
        break;
      }
    }

    /* 2. If authorName wasn't on an <a href> (e.g. avatar-only <a href>, unhydrated role="link", or span header like "Ayatullah Mushkan Maryam · 4h"), grab the first valid header name in rowEl */
    if (!authorName) {
      const nameCandidates = Array.from(
        rowEl.querySelectorAll(
          'a[role="link"], span[role="link"], h3, h4, strong, span[dir="auto"], svg[aria-label], img[alt]'
        )
      ).filter((nc) => !isInsideNestedCommentArticle(nc));
      for (const nc of nameCandidates) {
        if (nc.tagName === "A" && isInlineMentionLinkInsideBody(nc)) continue;
        const lines = String(
          nc.getAttribute("aria-label") || nc.getAttribute("alt") || nc.innerText || nc.textContent || ""
        ).split(/\r?\n/);
        for (const ln of lines) {
          const cleaned = cleanPersonName(ln);
          if (cleaned) {
            authorName = cleaned;
            break;
          }
        }
        if (authorName) break;
      }
    }

    if (!authorName) return null;

    /* Skip top modal header if it's just the Post Owner's main post header (no Reply button, no comment_id timestamp, and not a Comment aria-label) */
    if (modalOwnerNameLower && authorName.toLowerCase() === modalOwnerNameLower) {
      const hasCommentTimestamp = Array.from(
        rowEl.querySelectorAll('a[href*="comment_id="], a[href*="reply_comment_id="]')
      ).some((a) => !isInsideNestedCommentArticle(a));
      const isExplicitCommentAria =
        COMMENT_ARIA_PREFIX_RE.test(ownAria) || COMMENT_ARIA_BANGLA_RE.test(ownAria);
      if (countLeafReplyNodes(rowEl) === 0 && !hasCommentTimestamp && !isExplicitCommentAria) {
        return null;
      }
    }

    const avatarUrl = extractAvatarUrlFromContainer(rowEl);

    /* 2b. Ensure "See original" ("মূলটি দেখুন") and "See more" ("আরও দেখুন") inside this row are clicked BEFORE reading comment text */
    const rowBtns = Array.from(
      rowEl.querySelectorAll('div[role="button"], span[role="button"], a[role="button"], span[dir="auto"]')
    ).filter((rb) => !isInsideNestedCommentArticle(rb));
    for (const rb of rowBtns) {
      const rbTxt = cleanText(rb.innerText || rb.textContent).toLowerCase();
      const rbAria = cleanText(rb.getAttribute("aria-label") || "").toLowerCase();
      const rbLabel = rbTxt || rbAria;
      if (!rbLabel) continue;
      if (rbLabel.startsWith("see translation") || rbLabel === "অনুবাদ দেখুন") continue;
      if (
        rbLabel === "see original" ||
        rbLabel.startsWith("see original ") ||
        rbLabel.startsWith("see original(") ||
        rbLabel === "মূলটি দেখুন" ||
        rbLabel === "মূল লেখাটি দেখুন" ||
        rbLabel === "hide translation" ||
        rbLabel === "অনুবাদ লুকান"
      ) {
        if (rb.dataset.fbOriginalClicked !== "1") {
          try {
            const clickTarget = rb.closest('div[role="button"], span[role="button"], a[role="button"]') || rb;
            clickTarget.click();
            rb.dataset.fbOriginalClicked = "1";
          } catch (e) {}
        }
      } else if ((/^see\s+more$/i.test(rbLabel) || rbLabel === "আরও দেখুন") && rb.dataset.fbExpandClicked !== "1") {
        try {
          const clickTarget = rb.closest('div[role="button"], span[role="button"], a[role="button"]') || rb;
          clickTarget.click();
          rb.dataset.fbExpandClicked = "1";
        } catch (e) {}
      }
    }

    /* 3. Extract comment body text from dir="auto" blocks (excluding nested reply articles) */
    const textBlocks = Array.from(rowEl.querySelectorAll('div[dir="auto"], span[dir="auto"]')).filter(
      (tb) => !isInsideNestedCommentArticle(tb)
    );
    const bodyParts = [];
    for (const tb of textBlocks) {
      if (
        tb.parentElement &&
        tb.parentElement.closest('[dir="auto"]') &&
        rowEl.contains(tb.parentElement.closest('[dir="auto"]')) &&
        !isInsideNestedCommentArticle(tb.parentElement.closest('[dir="auto"]'))
      ) {
        continue;
      }
      const isBtnOrReact = Boolean(
        tb.closest('[role="button"], [aria-label*="reaction" i], [aria-label*="প্রতিক্রি"]')
      );
      const rawT = cleanText(tb.innerText || tb.textContent);
      const cleanedT = rawT.replace(INLINE_META_SUFFIX_RE, "").replace(TRAILING_TIME_RE, "").trim();
      if (
        isNoiseCommentBodyLine(rawT, authorName, isBtnOrReact) ||
        isNoiseCommentBodyLine(cleanedT, authorName, isBtnOrReact)
      ) {
        continue;
      }
      if (!bodyParts.includes(rawT)) {
        bodyParts.push(rawT);
      }
    }

    /* 4. Emoji / Sticker comment fallback (e.g. ❤️❤️ in Asfia Jahan's comment) */
    if (bodyParts.length === 0) {
      const imgs = Array.from(rowEl.querySelectorAll("img[alt]")).filter(
        (im) => !isInsideNestedCommentArticle(im)
      );
      for (const im of imgs) {
        if (im.closest('[role="button"], [aria-label*="reaction" i]')) continue;
        const alt = cleanText(im.getAttribute("alt"));
        if (alt && alt.length <= 16 && !alt.toLowerCase().includes("profile")) {
          bodyParts.push(alt);
        }
      }
    }

    return {
      name: authorName,
      url: authorUrl || "",
      avatar_url: avatarUrl,
      content: bodyParts.join(" ").trim(),
      action_type: "comment"
    };
  }

  /**
   * 4-Engine Comment Extractor:
   * Engine A (Leaf "Reply" / "উত্তর দিন" Button Exact Row Finder): Walks up from every leaf Reply button while `countLeafReplyNodes === 1`.
   * Engine B (Anchor-First `<a href>` Finder): Scans author `<a href>` profile links inside the comment area (skipping inline `@mentions` and `comment_id=` timestamps).
   * Engine C (`div[role="article"]` Scanner): Extracts BOTH parent comments (even when they contain nested reply articles!) and leaf reply articles.
   * Engine D (Logged-Out / Incognito / Restricted Post `comment_id=` Timestamp & Action Bar Scanner): Extracts comments even when Facebook hides `"Reply"` buttons and omits `role="article"`.
   */
  function extractCommentsFromRoot(root) {
    const found = [];
    const seenKeys = new Set();
    const processedRows = new Set();

    let modalOwnerNameLower = "";
    const titleHeading = root.querySelector("h1, h2, [role='heading']");
    if (titleHeading) {
      const titleTxt = cleanText(titleHeading.innerText || titleHeading.textContent);
      const mOwner = titleTxt.match(/^(.+?)(?:'s|’s|-এর)\s+(?:post|পোস্ট)$/i);
      if (mOwner) {
        modalOwnerNameLower = mOwner[1].trim().toLowerCase();
      }
    }

    const recordComment = (item, rowNode) => {
      if (!item || !item.name) return;
      const idPart = (item.url || item.name).toLowerCase();
      const key = `${idPart}|${item.content}`;
      if (seenKeys.has(key)) return;
      /* Also check if we already recorded this exact name + content without URL and now have URL (or vice versa) */
      const nameOnlyKey = `${item.name.toLowerCase()}|${item.content}`;
      if (seenKeys.has(nameOnlyKey)) {
        if (item.url) {
          const prev = found.find(
            (f) => f.name.toLowerCase() === item.name.toLowerCase() && f.content === item.content && !f.url
          );
          if (prev) prev.url = item.url;
        }
        return;
      }
      seenKeys.add(key);
      seenKeys.add(nameOnlyKey);
      found.push(item);
      if (rowNode) {
        processedRows.add(rowNode);
        lastExtractedElements.push(rowNode);
      }
    };

    /* Engine C-First: Explicit Comment/Reply <div role="article"> elements (including parent comments that contain nested reply articles!) */
    const articles = Array.from(root.querySelectorAll('div[role="article"]'));
    for (const art of articles) {
      if (isInsideIgnoredChrome(art)) continue;
      const artAria = cleanText(art.getAttribute("aria-label") || "").toLowerCase();
      const isExplicitCommentArticle =
        artAria.startsWith("comment by") ||
        artAria.startsWith("reply by") ||
        artAria.includes("মন্তব্য") ||
        artAria.includes("কমেন্ট") ||
        artAria.includes("উত্তর");
      /* Skip the outer main post wrapper article if it contains the post's UFI reaction toolbar and is not a comment article */
      if (!isExplicitCommentArticle && art.querySelector('[role="toolbar"]') && art.querySelectorAll('div[role="article"]').length > 0) {
        continue;
      }
      const item = extractCommentFromSingleRowContainer(art, modalOwnerNameLower);
      if (item) {
        recordComment(item, art);
      }
    }

    /* Engine A: Walk up from every leaf "Reply" / "উত্তর দিন" node while countLeafReplyNodes === 1 */
    const allSpansAndBtns = Array.from(root.querySelectorAll("span, div[role='button']"));
    for (const node of allSpansAndBtns) {
      if (node.children.length > 0) continue;
      if (isInsideIgnoredChrome(node)) continue;
      const t = cleanText(node.textContent).toLowerCase();
      if (t !== "reply" && t !== "উত্তর দিন") continue;

      let curr = node.parentElement;
      let bestCommentRow = curr;
      for (let depth = 0; depth < 14 && curr && curr !== root && curr !== document.body; depth++) {
        const replyCount = countLeafReplyNodes(curr);
        if (replyCount > 1) {
          break;
        }
        if (countDistinctAvatars(curr) > 1) {
          break;
        }
        bestCommentRow = curr;
        curr = curr.parentElement;
      }

      if (bestCommentRow && !processedRows.has(bestCommentRow)) {
        const item = extractCommentFromSingleRowContainer(bestCommentRow, modalOwnerNameLower);
        if (item) {
          recordComment(item, bestCommentRow);
        }
      }
    }

    /* Engine D: Logged-Out / Incognito / Restricted Post Comment Timestamp (a[href*="comment_id="]) Walker */
    const commentTimeLinks = Array.from(
      root.querySelectorAll('a[href*="comment_id="], a[href*="reply_comment_id="]')
    );
    for (const tl of commentTimeLinks) {
      if (isInsideIgnoredChrome(tl)) continue;
      let curr = tl.parentElement;
      let bestRow = curr;
      for (let depth = 0; depth < 12 && curr && curr !== root && curr !== document.body; depth++) {
        const timeLinksInCurr = curr.querySelectorAll('a[href*="comment_id="], a[href*="reply_comment_id="]');
        if (timeLinksInCurr.length > 1) break;
        if (countDistinctAvatars(curr) > 1) break;
        bestRow = curr;
        curr = curr.parentElement;
      }
      if (bestRow && !processedRows.has(bestRow)) {
        const item = extractCommentFromSingleRowContainer(bestRow, modalOwnerNameLower);
        if (item) {
          recordComment(item, bestRow);
        }
      }
    }

    /* Engine B: Anchor-First <a href> scan (covers any remaining comment layout variants) */
    const allLinks = Array.from(root.querySelectorAll("a[href]"));
    for (const a of allLinks) {
      if (isInsideIgnoredChrome(a)) continue;
      if (a.closest('[role="tab"], [role="tablist"], [role="toolbar"]')) continue;
      const rawHref = a.getAttribute("href") || a.href || "";
      if (rawHref.includes("comment_id=") || rawHref.includes("reply_comment_id=")) continue;

      /* Skip if already inside one of the processedRows from Engine C / A / D (unless that processedRow was a parent article and 'a' is inside a child reply) */
      let alreadyCovered = false;
      for (const pr of processedRows) {
        if (pr.contains(a)) {
          const closestArt = a.closest('div[role="article"]');
          if (!closestArt || closestArt === pr || !pr.contains(closestArt)) {
            alreadyCovered = true;
            break;
          }
        }
      }
      if (alreadyCovered) continue;

      /* Skip inline @mention links inside a comment text paragraph */
      const parentDirDiv = a.closest('div[dir="auto"]');
      if (parentDirDiv) {
        const pTxt = cleanText(parentDirDiv.innerText || parentDirDiv.textContent || "");
        const aTxt = cleanText(a.innerText || a.textContent || "");
        if (pTxt.length > aTxt.length + 2) continue;
      }

      const cUrl = cleanProfileUrl(rawHref);
      if (!cUrl) continue;

      let curr = a.parentElement;
      let bestRow = curr;
      for (let depth = 0; depth < 8 && curr && curr !== root && curr !== document.body; depth++) {
        if (countDistinctAvatars(curr) > 1) break;
        if (countLeafReplyNodes(curr) > 1) break;
        const otherAnchors = curr.querySelectorAll("a[href]");
        let hasDifferentPerson = false;
        for (const oa of otherAnchors) {
          if (oa === a) continue;
          const oaDirBlock = oa.closest('div[dir="auto"]');
          if (oaDirBlock && !oaDirBlock.contains(a)) continue;
          const oaUrl = cleanProfileUrl(oa.getAttribute("href") || oa.href);
          if (oaUrl && oaUrl.toLowerCase() !== cUrl.toLowerCase()) {
            hasDifferentPerson = true;
            break;
          }
        }
        if (hasDifferentPerson) break;
        bestRow = curr;
        curr = curr.parentElement;
      }

      if (bestRow && !processedRows.has(bestRow)) {
        const item = extractCommentFromSingleRowContainer(bestRow, modalOwnerNameLower);
        if (item) {
          if (!item.url) item.url = cUrl;
          recordComment(item, bestRow);
        }
      }
    }

    return found;
  }

  function normalizeReactionType(rawVal) {
    if (!rawVal) return "";
    const s = cleanText(String(rawVal));
    if (!s || /^\d+[kmb,.]*$/i.test(s)) return "";
    const low = s.toLowerCase().replace(/^[.,!?:;()[\]{}"'·•\s]+|[.,!?:;()[\]{}"'·•\s]+$/g, "");
    if (!low || low === "all" || low.startsWith("all ") || low === "সব") return "";

    if (
      low === "like" ||
      low === "liked" ||
      low === "👍" ||
      low.startsWith("👍") ||
      low === "লাইক" ||
      /^like\b/i.test(low) ||
      /\bliked$/i.test(low)
    ) {
      return "Like";
    }
    if (
      low === "love" ||
      low === "loved" ||
      low === "❤️" ||
      low === "❤" ||
      low.startsWith("❤️") ||
      low.startsWith("❤") ||
      low === "লাভ" ||
      low === "ভালোবাসা" ||
      /^love\b/i.test(low) ||
      /\bloved$/i.test(low)
    ) {
      return "Love";
    }
    if (
      low === "care" ||
      low === "cared" ||
      low === "🥰" ||
      low === "🤗" ||
      low === "কেয়ার" ||
      low === "কেয়ার" ||
      low === "যত্ন" ||
      /^care\b/i.test(low) ||
      /\bcared$/i.test(low)
    ) {
      return "Care";
    }
    if (
      low === "haha" ||
      low === "😆" ||
      low === "😂" ||
      low === "🤣" ||
      low === "হাহা" ||
      /^haha\b/i.test(low) ||
      /\bhaha$/i.test(low)
    ) {
      return "Haha";
    }
    if (
      low === "wow" ||
      low === "😮" ||
      low === "😲" ||
      low === "ওয়াও" ||
      low === "ওয়াও" ||
      low === "অবাক" ||
      /^wow\b/i.test(low) ||
      /\bwow$/i.test(low)
    ) {
      return "Wow";
    }
    if (
      low === "sad" ||
      low === "😢" ||
      low === "😭" ||
      low === "স্যাড" ||
      low === "দুঃখিত" ||
      /^sad\b/i.test(low) ||
      /\bsad$/i.test(low)
    ) {
      return "Sad";
    }
    if (
      low === "angry" ||
      low === "😡" ||
      low === "😠" ||
      low === "অ্যাংরি" ||
      low === "রাগান্বিত" ||
      low === "রাগ" ||
      /^angry\b/i.test(low) ||
      /\bangry$/i.test(low)
    ) {
      return "Angry";
    }

    const pairs = [
      ["reacted with love", "Love"],
      ["reacted with care", "Care"],
      ["reacted with haha", "Haha"],
      ["reacted with wow", "Wow"],
      ["reacted with sad", "Sad"],
      ["reacted with angry", "Angry"],
      ["reacted with like", "Like"],
      ["love:", "Love"],
      ["care:", "Care"],
      ["haha:", "Haha"],
      ["wow:", "Wow"],
      ["sad:", "Sad"],
      ["angry:", "Angry"],
      ["like:", "Like"],
      ["লাভ:", "Love"],
      ["কেয়ার:", "Care"],
      ["কেয়ার:", "Care"],
      ["হাহা:", "Haha"],
      ["ওয়াও:", "Wow"],
      ["ওয়াও:", "Wow"],
      ["স্যাড:", "Sad"],
      ["অ্যাংরি:", "Angry"],
      ["লাইক:", "Like"]
    ];
    for (const [sub, canonical] of pairs) {
      if (low.includes(sub)) return canonical;
    }
    return "";
  }

  function inferReactionFromSvgOrUrl(src) {
    if (!src) return "";
    const low = src.toLowerCase();
    if (low.startsWith("data:image/svg+xml")) {
      let decoded = low;
      try {
        decoded = decodeURIComponent(low);
      } catch (e) {}
      if (
        decoded.includes("#1877f2") ||
        decoded.includes("#0866ff") ||
        decoded.includes("#2078f4") ||
        decoded.includes("#0571ed") ||
        decoded.includes("#4267b2")
      ) {
        return "Like";
      }
      if (
        decoded.includes("#f33e58") ||
        decoded.includes("#e41e3f") ||
        decoded.includes("#fb3c44") ||
        decoded.includes("#fa383e") ||
        decoded.includes("#ff2d55")
      ) {
        return "Love";
      }
      if (decoded.includes("#e9710f") || decoded.includes("#dd6b20")) {
        return "Angry";
      }
    }
    return "";
  }

  function buildReactionIconUrlMap(likeDialog) {
    const iconMap = new Map();
    const scopes = [likeDialog, document.body].filter(Boolean);
    for (const scope of scopes) {
      /* 1. Check all elements with aria-label (e.g. "Like: 80 people", "Love, 25", role="tab") */
      const labeled = scope.querySelectorAll('[aria-label], [role="tab"]');
      for (const el of labeled) {
        const aria = cleanText(el.getAttribute("aria-label") || el.innerText || "");
        const rType = normalizeReactionType(aria);
        if (!rType) continue;
        const imgs = el.querySelectorAll("img[src], svg image");
        for (const im of imgs) {
          const s = im.getAttribute("src") || im.getAttribute("xlink:href") || im.getAttribute("href") || "";
          if (s) iconMap.set(s, rType);
        }
      }
      /* 2. Check all <img alt="..."> with explicit reaction alt text */
      const altImgs = scope.querySelectorAll("img[alt][src]");
      for (const im of altImgs) {
        const rType = normalizeReactionType(im.getAttribute("alt"));
        const s = im.getAttribute("src") || "";
        if (rType && s) {
          iconMap.set(s, rType);
        }
      }
    }
    return iconMap;
  }

  function detectActiveTabReactionType(likeDialog, iconMap) {
    if (!likeDialog) return "";
    const tabs = likeDialog.querySelectorAll('[role="tab"]');
    for (const tab of tabs) {
      const isSelected =
        tab.getAttribute("aria-selected") === "true" ||
        tab.getAttribute(" tabindex") === "0" ||
        tab.getAttribute("tabindex") === "0";
      if (!isSelected) continue;
      const aria = cleanText(tab.getAttribute("aria-label") || tab.innerText || "");
      if (/^all\b|^সব\b/i.test(aria)) return "";
      const direct = normalizeReactionType(aria);
      if (direct) return direct;
      const imgs = tab.querySelectorAll("img[src], svg image");
      for (const im of imgs) {
        const altType = normalizeReactionType(im.getAttribute("alt") || im.getAttribute("aria-label") || "");
        if (altType) return altType;
        const src = im.getAttribute("src") || im.getAttribute("xlink:href") || im.getAttribute("href") || "";
        if (src && iconMap && iconMap.has(src)) {
          return iconMap.get(src);
        }
        const svgHint = inferReactionFromSvgOrUrl(src);
        if (svgHint) return svgHint;
      }
    }
    return "";
  }

  function findRowForAnchor(a, root) {
    if (!a) return root;
    const primaryUrl = cleanProfileUrl(a.getAttribute("href") || a.href || "");
    let curr = a.parentElement;
    let bestRow = curr || a;

    for (let d = 0; d < 10 && curr && curr !== root && curr !== document.body; d++) {
      if (curr.getAttribute("role") === "dialog" || curr.querySelector('[role="tablist"]')) {
        break;
      }
      /* Stop if curr spans multiple listitems or multiple distinct profile avatars! */
      if (curr.querySelectorAll('[role="listitem"]').length > 1) {
        break;
      }
      if (countDistinctAvatars(curr) > 1) {
        break;
      }

      /* Stop if curr spans two different people's profile links (or ANY profile link when primaryUrl is null in Engine B!) */
      let hasOtherPerson = false;
      const otherLinks = curr.querySelectorAll("a[href]");
      for (const oa of otherLinks) {
        if (oa === a || a.contains(oa) || oa.contains(a)) continue;
        const oaUrl = cleanProfileUrl(oa.getAttribute("href") || oa.href || "");
        if (!oaUrl) continue;
        if (!primaryUrl || oaUrl.toLowerCase() !== primaryUrl.toLowerCase()) {
          hasOtherPerson = true;
          break;
        }
      }
      if (hasOtherPerson) break;

      /* Also stop if curr contains 2+ row action buttons ("Add friend", "Follow", "Message", Bangla equivalents) */
      const btns = curr.querySelectorAll('div[role="button"], span[role="button"]');
      let rowActionBtnCount = 0;
      for (const b of btns) {
        const bt = cleanText(b.innerText || b.getAttribute("aria-label") || "").toLowerCase();
        if (
          bt === "add friend" ||
          bt === "follow" ||
          bt === "following" ||
          bt === "message" ||
          bt === "friends" ||
          bt === "cancel request" ||
          bt === "বন্ধু যোগ করুন" ||
          bt === "ফলো করুন" ||
          bt === "ফলো করছেন" ||
          bt === "মেসেজ" ||
          bt === "বন্ধু" ||
          bt === "অনুরোধ বাতিল করুন"
        ) {
          rowActionBtnCount += 1;
        }
      }
      if (rowActionBtnCount > 1) break;

      bestRow = curr;
      curr = curr.parentElement;
    }
    return bestRow;
  }

  function extractNameFromRowContainer(rowEl) {
    if (!rowEl) return null;
    const candidates = [];
    const nodes = rowEl.querySelectorAll(
      'a[href], a[role="link"], div[role="link"], span[role="link"], h2, h3, h4, strong, span[dir="auto"], div[dir="auto"], svg[aria-label], img[alt]'
    );
    for (const n of nodes) {
      if (n.closest('div[role="button"], span[role="button"]')) {
        const bTxt = cleanText(n.innerText || n.textContent || "").toLowerCase();
        if (IGNORE_LABELS.has(bTxt)) continue;
      }
      const aria = n.getAttribute("aria-label") || n.getAttribute("alt") || "";
      if (aria && !normalizeReactionType(aria)) {
        candidates.push(aria);
      }
      const txt = n.innerText || n.textContent || "";
      if (txt) {
        for (const ln of String(txt).split(/\r?\n/)) {
          if (ln.trim()) candidates.push(ln);
        }
      }
    }
    for (const c of candidates) {
      const cleaned = cleanPersonName(c);
      if (cleaned) return cleaned;
    }
    return null;
  }

  function detectReactionTypeInRow(rowEl, avatarUrl, iconMap, activeTabReaction) {
    if (!rowEl) return activeTabReaction || "";

    /* Layer 1: Check explicit img[alt], svg[aria-label], or [aria-label] inside rowEl */
    const mediaAndAria = rowEl.querySelectorAll("img[alt], svg[aria-label], [aria-label], [title]");
    for (const el of mediaAndAria) {
      for (const attr of ["alt", "aria-label", "title"]) {
        const val = el.getAttribute(attr);
        if (!val) continue;
        /* Check both direct reaction label ("Love") and suffix ("Md Rahim Loved" / "Profile picture of X, Love") */
        const direct = normalizeReactionType(val);
        if (direct) return direct;
        const mSuffix = val.match(/(?:\s*[,·•]\s*|\s+)(Liked|Loved|Cared|Haha|Wow|Sad|Angry)\.?$/i);
        if (mSuffix) {
          const sufNorm = normalizeReactionType(mSuffix[1]);
          if (sufNorm) return sufNorm;
        }
      }
    }

    /* Layer 2: Check raw text lines inside rowEl for trailing reaction suffix ("Md Rahim · Loved") */
    const rawRowText = cleanText(rowEl.innerText || rowEl.textContent || "");
    if (rawRowText) {
      const mRowSuf = rawRowText.match(/\b(Liked|Loved|Cared|Haha|Wow|Sad|Angry)\b/i);
      if (mRowSuf) {
        const rNorm = normalizeReactionType(mRowSuf[1]);
        if (rNorm) return rNorm;
      }
    }

    /* Layer 3 & 4: Match badge <img src> or <svg image> against tab/UFI iconMap and SVG color signatures */
    const imgs = rowEl.querySelectorAll("img[src], svg image, image");
    for (const im of imgs) {
      const src = im.getAttribute("src") || im.getAttribute("xlink:href") || im.getAttribute("href") || "";
      if (!src || src === avatarUrl) continue;
      if (iconMap && iconMap.has(src)) {
        return iconMap.get(src);
      }
      const svgHint = inferReactionFromSvgOrUrl(src);
      if (svgHint) return svgHint;
    }

    /* Layer 5: Active reaction tab fallback (when scraping a specific reaction tab like Love/Like/Care) */
    return activeTabReaction || "";
  }

  function extractLikesFromDialog(likeDialog) {
    const found = [];
    if (!likeDialog) return found;
    triggerHoverHydration(likeDialog);

    const iconMap = buildReactionIconUrlMap(likeDialog);
    const activeTabReaction = detectActiveTabReactionType(likeDialog, iconMap);

    const links = Array.from(likeDialog.querySelectorAll("a[href]"));
    const urlToRecord = new Map();
    const orderedUrls = [];
    const coveredRows = new Set();

    /* Engine A: Anchor + Sibling Row Name & Reaction Badge Recovery */
    for (const a of links) {
      if (isInsideIgnoredChrome(a)) continue;
      if (a.closest('[role="tab"], [role="tablist"]')) continue;

      const cUrl = cleanProfileUrl(a.getAttribute("href") || a.href);
      if (!cUrl) continue;

      const rowEl = findRowForAnchor(a, likeDialog);
      if (rowEl && rowEl !== likeDialog) {
        coveredRows.add(rowEl);
      }

      /* Extract name from anchor first; if anchor is an avatar-only link, recover name from rowEl! */
      let name = extractNameFromAnchor(a);
      if (!name && rowEl && rowEl !== likeDialog) {
        name = extractNameFromRowContainer(rowEl);
      }

      /* Also check if raw anchor text/aria had a reaction suffix before cleanPersonName stripped it */
      let rawAnchorReaction = "";
      for (const rawCand of [a.getAttribute("aria-label"), a.innerText, a.textContent]) {
        if (!rawCand) continue;
        const mSuf = String(rawCand).match(/(?:\s*[,·•]\s*|\s+)(Liked|Loved|Cared|Haha|Wow|Sad|Angry)\.?$/i);
        if (mSuf) {
          rawAnchorReaction = normalizeReactionType(mSuf[1]);
          if (rawAnchorReaction) break;
        }
      }

      const avatarUrl = extractAvatarUrlFromContainer(rowEl);
      const reactionType =
        rawAnchorReaction || detectReactionTypeInRow(rowEl, avatarUrl, iconMap, activeTabReaction);

      if (!urlToRecord.has(cUrl)) {
        orderedUrls.push(cUrl);
        urlToRecord.set(cUrl, {
          name: name || "",
          avatar_url: avatarUrl || "",
          reaction_type: reactionType || ""
        });
      } else {
        const existing = urlToRecord.get(cUrl);
        if (name && (!existing.name || (a.innerText || "").trim().length > 0)) {
          existing.name = name;
        }
        if (avatarUrl && !existing.avatar_url) {
          existing.avatar_url = avatarUrl;
        }
        if (reactionType && !existing.reaction_type) {
          existing.reaction_type = reactionType;
        }
      }
      if (name || rowEl) {
        lastExtractedElements.push(rowEl || a);
      }
    }

    for (const u of orderedUrls) {
      const rec = urlToRecord.get(u);
      if (rec && rec.name) {
        found.push({
          name: rec.name,
          url: u,
          avatar_url: rec.avatar_url || "",
          reaction_type: rec.reaction_type || "",
          content: rec.reaction_type || "",
          action_type: "like"
        });
      }
    }

    /* Engine B: Unhydrated / Locked / Deactivated Profile Row Recovery (rows with no <a href>) */
    const seenNamesLower = new Set(found.map((it) => it.name.toLowerCase()));
    const rowCandidates = Array.from(
      likeDialog.querySelectorAll('[role="listitem"], div[dir="auto"], span[dir="auto"]')
    );
    for (const node of rowCandidates) {
      if (isInsideIgnoredChrome(node)) continue;
      if (node.closest('[role="tab"], [role="tablist"], [role="heading"], h1, h2, h3')) continue;

      let alreadyCovered = false;
      for (const cr of coveredRows) {
        if (cr.contains(node)) {
          alreadyCovered = true;
          break;
        }
      }
      if (alreadyCovered) continue;

      const rowEl = findRowForAnchor(node, likeDialog);
      if (!rowEl || rowEl === likeDialog || coveredRows.has(rowEl)) continue;
      /* Ensure this row actually looks like a reactor row (has an avatar image/svg) */
      if (!rowEl.querySelector("svg image, image, img")) continue;

      const name = extractNameFromRowContainer(rowEl);
      if (!name || seenNamesLower.has(name.toLowerCase())) continue;

      coveredRows.add(rowEl);
      seenNamesLower.add(name.toLowerCase());
      const avatarUrl = extractAvatarUrlFromContainer(rowEl);
      const reactionType = detectReactionTypeInRow(rowEl, avatarUrl, iconMap, activeTabReaction);
      lastExtractedElements.push(rowEl);

      found.push({
        name: name,
        url: "",
        avatar_url: avatarUrl || "",
        reaction_type: reactionType || "",
        content: reactionType || "",
        action_type: "like"
      });
    }

    return found;
  }

  async function tryStepToNextReactionTab(likeDialog) {
    if (!likeDialog) return false;
    const tabs = Array.from(likeDialog.querySelectorAll('[role="tab"]'));
    if (tabs.length <= 1) return false;

    const iconMap = buildReactionIconUrlMap(likeDialog);

    /* Record currently selected tab as visited */
    for (let i = 0; i < tabs.length; i++) {
      const t = tabs[i];
      if (t.getAttribute("aria-selected") === "true") {
        visitedReactionTabs.add(i);
      }
    }

    /* Check if any collected likes are missing a specific reaction_type, or if we haven't visited all tabs */
    for (let i = 0; i < tabs.length; i++) {
      if (visitedReactionTabs.has(i)) continue;
      const tab = tabs[i];
      const aria = cleanText(tab.getAttribute("aria-label") || tab.innerText || "").toLowerCase();
      if (aria === "more" || aria === "আরও") continue;

      visitedReactionTabs.add(i);
      const tabReaction =
        normalizeReactionType(aria) ||
        (() => {
          const im = tab.querySelector("img[src], svg image");
          if (!im) return "";
          const src = im.getAttribute("src") || im.getAttribute("xlink:href") || "";
          return (
            normalizeReactionType(im.getAttribute("alt") || "") ||
            (src && iconMap.get(src)) ||
            inferReactionFromSvgOrUrl(src) ||
            `Tab #${i + 1}`
          );
        })();

      try {
        updateUIStatus(`Switching to Reaction Tab (${tabReaction || aria || i + 1}) to capture all reactions...`);
        tab.click();
        lockedScrollEl = null;
        await sleep(1600);
        return true;
      } catch (e) {}
    }
    return false;
  }

  function findNestedCommentContainersInShareDialog(shareDialog) {
    const containers = [];
    if (!shareDialog) return containers;

    /* 1. Explicit comment/reply role="article" containers */
    const articles = shareDialog.querySelectorAll('div[role="article"]');
    for (const art of articles) {
      const aria = cleanText(art.getAttribute("aria-label") || "").toLowerCase();
      if (
        aria.startsWith("comment by") ||
        aria.startsWith("reply by") ||
        aria.includes("মন্তব্য") ||
        aria.includes("উত্তর")
      ) {
        containers.push(art);
      }
    }

    /* 2. Leaf "Reply" / "উত্তর দিন" buttons inside a share card's comments section */
    const spansAndBtns = shareDialog.querySelectorAll("span, div[role='button']");
    for (const node of spansAndBtns) {
      if (node.children.length > 0) continue;
      if (isInsideIgnoredChrome(node)) continue;
      const t = cleanText(node.textContent).toLowerCase();
      if (t !== "reply" && t !== "উত্তর দিন") continue;

      let curr = node.parentElement;
      let bestRow = curr;
      for (let d = 0; d < 10 && curr && curr !== shareDialog && curr !== document.body; d++) {
        if (countLeafReplyNodes(curr) > 1) break;
        const currTxt = cleanText(curr.innerText || curr.textContent).toLowerCase();
        if (currTxt.includes("show attachment") || currTxt.includes("hide attachment")) break;
        bestRow = curr;
        curr = curr.parentElement;
      }
      if (bestRow) containers.push(bestRow);
    }

    /* 3. UFI Comments section starting at "Most relevant" / "All comments" / "Newest" inside a Share Card */
    const allFilterCandidates = shareDialog.querySelectorAll('div[role="button"], span[role="button"], span');
    const profileAnchors = Array.from(shareDialog.querySelectorAll("a[href]")).filter((a) =>
      Boolean(cleanProfileUrl(a.getAttribute("href") || a.href))
    );

    for (const btn of allFilterCandidates) {
      if (isInsideIgnoredChrome(btn)) continue;
      const txt = cleanText(btn.innerText || btn.textContent).toLowerCase();
      if (
        txt !== "most relevant" &&
        txt !== "all comments" &&
        txt !== "newest" &&
        txt !== "সবচেয়ে প্রাসঙ্গিক" &&
        txt !== "সব মন্তব্য" &&
        txt !== "নতুন"
      ) {
        continue;
      }

      /* Walk up from the comment filter button while the ancestor does NOT contain any profile anchor that precedes the filter button */
      let curr = btn.parentElement;
      let ufiCommentsSection = curr;
      for (let d = 0; d < 10 && curr && curr !== shareDialog && curr !== document.body; d++) {
        let hasPrecedingSharerAnchor = false;
        for (const pa of profileAnchors) {
          if (curr.contains(pa) && Boolean(pa.compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING)) {
            hasPrecedingSharerAnchor = true;
            break;
          }
        }
        if (hasPrecedingSharerAnchor) break;
        ufiCommentsSection = curr;
        curr = curr.parentElement;
      }
      if (ufiCommentsSection) {
        containers.push(ufiCommentsSection);
      }
    }

    return containers;
  }

  function extractSharesFromDialog(shareDialog) {
    const found = [];
    if (!shareDialog) return found;

    triggerHoverHydration(shareDialog);
    clickSeeOriginalAndSeeMore(shareDialog);

    const nestedCommentContainers = findNestedCommentContainersInShareDialog(shareDialog);

    const isInsideNestedComment = (node) => {
      if (!node) return false;
      for (const nc of nestedCommentContainers) {
        if (nc === node || nc.contains(node)) return true;
      }
      if (
        node.closest(
          'div[role="article"][aria-label*="Comment by" i], div[role="article"][aria-label*="Reply by" i], div[role="article"][aria-label*="মন্তব্য"]'
        )
      ) {
        return true;
      }
      const row = findRowForAnchor(node, shareDialog);
      if (row && row !== shareDialog) {
        const commentLinks = row.querySelectorAll('a[href*="comment_id="], a[href*="reply_comment_id="]');
        if (commentLinks.length > 0) return true;
      }
      return false;
    };

    const links = Array.from(shareDialog.querySelectorAll("a[href]"));
    const urlToRecord = new Map();
    const orderedUrls = [];

    for (const a of links) {
      if (isInsideIgnoredChrome(a)) continue;
      if (a.closest('[role="tab"], [role="tablist"]')) continue;
      if (isInsideNestedComment(a)) continue;

      const rawHref = a.getAttribute("href") || a.href || "";
      const cUrl = cleanProfileUrl(rawHref);
      if (!cUrl) continue;

      const directPostUrl = cleanSharedPostUrl(rawHref) || "";
      const name = extractNameFromAnchor(a);
      const rowEl = findRowForAnchor(a, shareDialog);
      const avatarUrl = extractAvatarUrlFromContainer(rowEl);

      if (!urlToRecord.has(cUrl)) {
        orderedUrls.push(cUrl);
        urlToRecord.set(cUrl, {
          name: name || "",
          avatar_url: avatarUrl || "",
          shared_post_url: directPostUrl,
          content: "",
          anchors: [a]
        });
      } else {
        const existing = urlToRecord.get(cUrl);
        existing.anchors.push(a);
        if (name && (!existing.name || (a.innerText || "").trim().length > 0)) {
          existing.name = name;
        }
        if (avatarUrl && !existing.avatar_url) {
          existing.avatar_url = avatarUrl;
        }
        if (directPostUrl && !existing.shared_post_url) {
          existing.shared_post_url = directPostUrl;
        }
      }
      if (name) {
        a.dataset.fbScraped = "1";
        lastExtractedElements.push(a);
      }
    }

    /* Second pass: For each sharer, inspect their Share Card container to extract Shared Caption (content) and Shared Post Link (shared_post_url) */
    for (const u of orderedUrls) {
      const rec = urlToRecord.get(u);
      if (!rec || !rec.name) continue;

      const primaryAnchor = rec.anchors[0];
      if (primaryAnchor) {
        /* Walk up from primaryAnchor to find this sharer's full Share Card container without spilling into another sharer's card */
        let curr = primaryAnchor.parentElement;
        let cardEl = curr;
        for (let d = 0; d < 12 && curr && curr !== shareDialog && curr !== document.body; d++) {
          if (curr.querySelector('[aria-label="Close"], [aria-label="বন্ধ করুন"]')) {
            break;
          }
          const heading = curr.querySelector("h1, h2, [role='heading']");
          if (heading) {
            const hTxt = cleanText(heading.innerText || heading.textContent).toLowerCase();
            if (hTxt.includes("people who shared") || hTxt.includes("যারা এটি শেয়ার")) {
              break;
            }
          }

          let hasDifferentSharer = false;
          const cardAnchors = curr.querySelectorAll("a[href]");
          for (const oa of cardAnchors) {
            if (isInsideNestedComment(oa)) continue;
            const oaProfileUrl = cleanProfileUrl(oa.getAttribute("href") || oa.href);
            if (oaProfileUrl && oaProfileUrl.toLowerCase() !== u.toLowerCase()) {
              hasDifferentSharer = true;
              break;
            }
          }
          if (hasDifferentSharer) break;

          cardEl = curr;
          curr = curr.parentElement;
        }

        if (cardEl) {
          if (!rec.avatar_url) {
            rec.avatar_url = extractAvatarUrlFromContainer(cardEl) || "";
          }

          /* Find cutoff boundary inside cardEl where attachment / reactions / nested comments begin */
          let cutoffEl = null;
          const markCutoffCandidate = (cand) => {
            if (!cand || cand === cardEl || cand.contains(primaryAnchor)) return;
            if (!Boolean(primaryAnchor.compareDocumentPosition(cand) & Node.DOCUMENT_POSITION_FOLLOWING)) {
              return;
            }
            if (
              !cutoffEl ||
              Boolean(cand.compareDocumentPosition(cutoffEl) & Node.DOCUMENT_POSITION_FOLLOWING)
            ) {
              cutoffEl = cand;
            }
          };

          for (const nc of nestedCommentContainers) {
            if (cardEl.contains(nc)) markCutoffCandidate(nc);
          }

          const cardNodes = cardEl.querySelectorAll(
            'div[role="button"], span[role="button"], a, span, div[aria-label]'
          );
          for (const cn of cardNodes) {
            const aria = cleanText(cn.getAttribute("aria-label") || "").toLowerCase();
            if (
              aria.startsWith("all reactions") ||
              aria.startsWith("like:") ||
              aria.startsWith("love:")
            ) {
              markCutoffCandidate(cn);
              continue;
            }
            if (cn.children.length <= 2) {
              const txt = cleanText(cn.innerText || cn.textContent).toLowerCase();
              if (
                txt === "show attachment" ||
                txt === "hide attachment" ||
                txt === "অ্যাটাচমেন্ট দেখুন" ||
                txt === "most relevant" ||
                txt === "all comments" ||
                txt === "newest" ||
                txt === "সবচেয়ে প্রাসঙ্গিক" ||
                txt === "সব মন্তব্য"
              ) {
                markCutoffCandidate(cn);
              }
            }
          }

          const isAfterCutoff = (node) => {
            if (!node) return true;
            if (isInsideNestedComment(node)) return true;
            if (!cutoffEl) return false;
            if (cutoffEl === node || cutoffEl.contains(node)) return true;
            return Boolean(cutoffEl.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING);
          };

          /* 1. Extract Shared Post Link (shared_post_url) from any permalink/timestamp anchor inside cardEl before cutoff */
          if (!rec.shared_post_url) {
            const cardLinks = cardEl.querySelectorAll("a[href]");
            for (const cl of cardLinks) {
              if (isAfterCutoff(cl)) continue;
              const pUrl = cleanSharedPostUrl(cl.getAttribute("href") || cl.href);
              if (pUrl) {
                rec.shared_post_url = pUrl;
                break;
              }
            }
          }

          /* 2. Extract Shared Caption / Title (content) from dir="auto" text blocks inside cardEl before cutoff */
          const rawDirBlocks = Array.from(cardEl.querySelectorAll('div[dir="auto"], span[dir="auto"]'));
          const candidateBlocks = rawDirBlocks.filter((tb) => {
            if (isAfterCutoff(tb)) return false;
            if (tb.contains(primaryAnchor)) return false;
            if (cutoffEl && tb.contains(cutoffEl)) return false;
            /* Skip if tb is inside the sharer's profile link or timestamp link (but allow hashtag/mention links inside a caption block) */
            const parentLink = tb.closest("a[href]");
            if (parentLink) {
              const lHref = (parentLink.getAttribute("href") || "").toLowerCase();
              if (!lHref.includes("/hashtag/")) return false;
            }
            return true;
          });

          const candidateSet = new Set(candidateBlocks);
          const bodyParts = [];
          for (const tb of candidateBlocks) {
            /* If an ancestor is also in candidateSet, skip the child so we don't duplicate text */
            let hasCandidateAncestor = false;
            let p = tb.parentElement;
            while (p && p !== cardEl) {
              if (candidateSet.has(p)) {
                hasCandidateAncestor = true;
                break;
              }
              p = p.parentElement;
            }
            if (hasCandidateAncestor) continue;

            const rawT = cleanText(tb.innerText || tb.textContent);
            const cleanedT = rawT
              .replace(INLINE_META_SUFFIX_RE, "")
              .replace(TRAILING_TIME_RE, "")
              .trim();
            if (
              isNoiseCommentBodyLine(rawT, rec.name) ||
              isNoiseCommentBodyLine(cleanedT, rec.name)
            ) {
              continue;
            }
            const lowT = rawT.toLowerCase();
            if (
              lowT === "show attachment" ||
              lowT === "hide attachment" ||
              lowT === "অ্যাটাচমেন্ট দেখুন"
            ) {
              continue;
            }
            if (!bodyParts.includes(rawT)) {
              bodyParts.push(rawT);
            }
          }

          if (bodyParts.length > 0) {
            rec.content = bodyParts.join(" ").trim();
          }
        }
      }

      found.push({
        name: rec.name,
        url: u,
        avatar_url: rec.avatar_url || "",
        content: rec.content || "",
        shared_post_url: rec.shared_post_url || "",
        action_type: "share"
      });
    }

    return found;
  }

  function scrapeVisibleItems(actionType, targetWin) {
    lastExtractedElements = [];
    if (!targetWin || !targetWin.root) return [];

    if (actionType === "comment") {
      return extractCommentsFromRoot(targetWin.root);
    }
    if (actionType === "like") {
      return extractLikesFromDialog(targetWin.root);
    }
    if (actionType === "share") {
      return extractSharesFromDialog(targetWin.root);
    }
    return [];
  }

  function harvestVisibleIntoStore(actionType, targetWin) {
    const items = scrapeVisibleItems(actionType, targetWin);
    const targetMap = store[actionType];
    let added = 0;

    for (const item of items) {
      const idKey = (item.url || item.name || "").toLowerCase();
      if (!idKey) continue;
      const nameLower = (item.name || "").toLowerCase();

      /* If an earlier pass captured this same person without a profile URL (unhydrated), and now we have their hydrated URL, migrate the key in-place! */
      if (item.url && nameLower) {
        const unhydratedKey =
          actionType === "comment" ? `${nameLower}|${item.content}` : nameLower;
        if (targetMap.has(unhydratedKey) && unhydratedKey !== (actionType === "comment" ? `${idKey}|${item.content}` : idKey)) {
          const oldRec = targetMap.get(unhydratedKey);
          if (oldRec && !oldRec.url) {
            targetMap.delete(unhydratedKey);
          }
        }
      }

      if (actionType === "comment" && item.content) {
        const hasNonAscii = /[^\x00-\x7F]/.test(item.content);
        /* If an earlier pass captured an empty comment, a truncated prefix, or an ASCII-only translation for this same author, replace it with the original/expanded comment */
        for (const [existingKey, existingItem] of Array.from(targetMap.entries())) {
          const sameAuthor =
            existingKey.startsWith(`${idKey}|`) ||
            (nameLower && (existingItem.name || "").toLowerCase() === nameLower && (!existingItem.url || !item.url || existingItem.url === item.url));
          if (!sameAuthor) continue;
          const oldContent = (existingItem.content || "").trim();
          if (oldContent === item.content) continue;
          const isReplacingEmpty = !oldContent && item.content.length > 0;
          const oldPrefix = oldContent.replace(/[.…\s]+$/, "").trim();
          const isExpandedOfOld =
            oldPrefix.length >= 6 &&
            item.content.startsWith(oldPrefix) &&
            item.content.length > oldContent.length;
          const isOriginalReplacingTranslated = hasNonAscii && oldContent && !/[^\x00-\x7F]/.test(oldContent);
          if (isReplacingEmpty || isExpandedOfOld || isOriginalReplacingTranslated) {
            targetMap.delete(existingKey);
          }
        }
      }
      const key =
        actionType === "comment"
          ? `${idKey}|${item.content}`
          : idKey;
      if (!targetMap.has(key)) {
        targetMap.set(key, item);
        unsentBatch.push(item);
        added += 1;
      } else {
        const existing = targetMap.get(key);
        let updated = false;
        if (item.url && !existing.url) {
          existing.url = item.url;
          updated = true;
        }
        if (item.avatar_url && !existing.avatar_url) {
          existing.avatar_url = item.avatar_url;
          updated = true;
        }
        if (item.shared_post_url && !existing.shared_post_url) {
          existing.shared_post_url = item.shared_post_url;
          updated = true;
        }
        if (actionType === "like" && item.reaction_type && !existing.reaction_type) {
          existing.reaction_type = item.reaction_type;
          existing.content = item.reaction_type;
          updated = true;
        }
        if (
          actionType === "share" &&
          item.content &&
          (!existing.content || item.content.length > existing.content.length)
        ) {
          existing.content = item.content;
          updated = true;
        }
        if (updated) {
          unsentBatch.push(existing);
        }
      }
    }
    return added;
  }

  function isScrollableElement(el) {
    if (!el || el === document.body || el === document.documentElement) return false;
    if (el.scrollHeight <= el.clientHeight + 4 || el.clientHeight < 90 || el.clientWidth < 170) return false;
    const st = window.getComputedStyle(el);
    return st.overflowY !== "visible" && st.overflowY !== "hidden";
  }

  function getRankedScrollCandidatesForWindow(windowRoot, actionType) {
    if (!windowRoot) return [];
    const candidateScores = new Map();

    const addScore = (el, pts) => {
      if (!el || el === document.body || el === document.documentElement) return;
      candidateScores.set(el, (candidateScores.get(el) || 0) + pts);
    };

    for (const el of lastExtractedElements) {
      if (!windowRoot.contains(el)) continue;
      let curr = el.parentElement;
      while (curr && curr !== document.body) {
        if (isScrollableElement(curr)) {
          addScore(curr, 35);
          break;
        }
        if (curr === windowRoot) break;
        curr = curr.parentElement;
      }
    }

    if (actionType === "comment") {
      const btns = windowRoot.querySelectorAll('div[role="button"], span');
      for (const b of btns) {
        if (b.children.length > 0) continue;
        const t = cleanText(b.textContent).toLowerCase();
        if (t !== "reply" && t !== "উত্তর দিন") continue;
        let curr = b.parentElement;
        while (curr && curr !== document.body) {
          if (isScrollableElement(curr)) {
            addScore(curr, 25);
            break;
          }
          if (curr === windowRoot) break;
          curr = curr.parentElement;
        }
      }
    }

    if (isScrollableElement(windowRoot)) {
      addScore(windowRoot, 15);
    }
    const divs = windowRoot.querySelectorAll("div");
    for (const d of divs) {
      if (isScrollableElement(d)) {
        const linkCount = d.querySelectorAll("a[href], span[dir='auto']").length;
        addScore(d, Math.min(linkCount, 20));
      }
    }

    return Array.from(candidateScores.entries())
      .sort((a, b) => {
        if (b[1] !== a[1]) return b[1] - a[1];
        return b[0].scrollHeight - a[0].scrollHeight;
      })
      .map((entry) => entry[0]);
  }

  function findSingleScrollableForWindow(windowRoot, actionType) {
    if (!windowRoot) return null;
    if (
      lockedScrollEl &&
      lockedWindowRoot === windowRoot &&
      document.body.contains(lockedScrollEl) &&
      (lockedScrollEl === windowRoot || windowRoot.contains(lockedScrollEl)) &&
      isScrollableElement(lockedScrollEl) &&
      lockedScrollEl.scrollTop + lockedScrollEl.clientHeight < lockedScrollEl.scrollHeight - 4
    ) {
      return lockedScrollEl;
    }

    const candidates = getRankedScrollCandidatesForWindow(windowRoot, actionType);
    if (candidates.length > 0) {
      lockedScrollEl = candidates[0];
      lockedWindowRoot = windowRoot;
      return lockedScrollEl;
    }
    return null;
  }

  function dispatchScrollTriggerEvents(el, deltaY = 340) {
    if (!el) return;
    try {
      el.dispatchEvent(new WheelEvent("wheel", { deltaY, bubbles: true, cancelable: true }));
      el.dispatchEvent(new Event("scroll", { bubbles: true }));
    } catch (e) {}
  }

  async function smoothHumanScroll(actionType, targetWin) {
    if (!targetWin || !targetWin.root) return false;
    const cfg = SPEED_CONFIGS[speedProfile] || SPEED_CONFIGS.human;
    const isDialog = targetWin.root.getAttribute("role") === "dialog";

    const candidates = getRankedScrollCandidatesForWindow(targetWin.root, actionType);
    if (lockedScrollEl && !candidates.includes(lockedScrollEl) && targetWin.root.contains(lockedScrollEl)) {
      candidates.unshift(lockedScrollEl);
    } else if (lockedScrollEl && candidates.includes(lockedScrollEl)) {
      candidates.splice(candidates.indexOf(lockedScrollEl), 1);
      candidates.unshift(lockedScrollEl);
    }

    const steps = 10;
    const stepDelay = Math.max(25, Math.floor(cfg.scrollDurationMs / steps));

    for (const candidate of candidates) {
      const startTop = candidate.scrollTop;
      const maxPossibleTop = Math.max(0, candidate.scrollHeight - candidate.clientHeight);
      if (startTop >= maxPossibleTop - 2) {
        dispatchScrollTriggerEvents(candidate, 360);
        continue;
      }

      const rawDelta = Math.floor(candidate.clientHeight * cfg.viewportFraction);
      const totalDelta = Math.max(cfg.minScrollPx, Math.min(cfg.maxScrollPx, rawDelta)) + randomInt(0, 22);
      const perStep = Math.max(12, Math.floor(totalDelta / steps));

      candidate.scrollTop = Math.min(maxPossibleTop, candidate.scrollTop + perStep);
      dispatchScrollTriggerEvents(candidate, perStep);
      if (candidate.scrollTop <= startTop) {
        continue;
      }

      lockedScrollEl = candidate;
      lockedWindowRoot = targetWin.root;

      for (let i = 1; i < steps; i++) {
        if (!isRunning) break;
        const currMax = Math.max(0, candidate.scrollHeight - candidate.clientHeight);
        candidate.scrollTop = Math.min(currMax, candidate.scrollTop + perStep);
        dispatchScrollTriggerEvents(candidate, perStep);
        if (i === Math.floor(steps / 2)) {
          if (activeAction === "comment" || activeAction === "share" || actionType === "comment" || actionType === "share") {
            await ensureOriginalCommentsRevealed(targetWin.root);
          }
          harvestVisibleIntoStore(actionType, targetWin);
        }
        await sleep(stepDelay + randomInt(0, 12));
      }

      return candidate.scrollTop > startTop + 2;
    }

    const isStandalonePostUrl = /\/posts\/|\/permalink\.php|\/story\.php|\/videos\/|\/watch|\/photo/i.test(window.location.href);
    if (!isDialog || (actionType === "comment" && isStandalonePostUrl)) {
      const totalWinDelta = randomInt(cfg.minScrollPx, cfg.maxScrollPx);
      const perStep = Math.max(14, Math.floor(totalWinDelta / steps));
      const startY = window.scrollY;
      for (let i = 0; i < steps; i++) {
        if (!isRunning) break;
        window.scrollBy(0, perStep);
        if (i === Math.floor(steps / 2)) {
          if (actionType === "comment" || actionType === "share") {
            await ensureOriginalCommentsRevealed(targetWin.root);
          }
          harvestVisibleIntoStore(actionType, targetWin);
        }
        await sleep(stepDelay + randomInt(0, 12));
      }
      if (window.scrollY > startY + 2) {
        return true;
      }
    }

    /* Fallback for Likes, Comments, and Shares when inner scroll reaches bottom or 'View more comments' is at bottom of list */
    if (actionType === "comment" && autoExpandComments(targetWin.root)) {
      return true;
    }
    if (lastExtractedElements.length > 0) {
      try {
        const lastEl = lastExtractedElements[lastExtractedElements.length - 1];
        lastEl.scrollIntoView({ block: "end", behavior: "smooth" });
        dispatchScrollTriggerEvents(lockedScrollEl || lastEl.parentElement || targetWin.root, 380);
        await sleep(350);
        return true;
      } catch (e) {}
    }

    return false;
  }

  function postSingleBatchOverHttpBridge(payloadStr) {
    /* Channel 1: Direct Chrome Extension Background Service Worker -> Desktop App HTTP Bridge (100% immune to focus loss!) */
    try {
      if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
        chrome.runtime.sendMessage({ cmd: "SEND_BATCH", payloadStr: payloadStr }, () => {
          void chrome.runtime.lastError;
        });
      }
    } catch (e) {}

    /* Channel 2: Direct localhost HTTP POST (for Bookmarklet / direct browser mode) */
    for (const port of [19876, 19877, 19878]) {
      try {
        fetch(`http://127.0.0.1:${port}/batch`, {
          method: "POST",
          mode: "cors",
          headers: { "Content-Type": "text/plain;charset=UTF-8" },
          body: payloadStr
        }).catch(() => {});
      } catch (e) {}
    }
  }

  function writeTextToSystemClipboard(payloadStr) {
    const fallbackCopy = () => {
      try {
        const host = document.getElementById("fb-contest-ext-panel") || document.body;
        const ta = document.createElement("textarea");
        ta.value = payloadStr;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        host.appendChild(ta);
        ta.focus({ preventScroll: true });
        ta.select();
        const ok = document.execCommand("copy");
        host.removeChild(ta);
        return ok;
      } catch (e) {
        return false;
      }
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(payloadStr).catch(() => fallbackCopy());
    } else {
      fallbackCopy();
    }
  }

  function copyBatchToClipboard(items, actionLabel = "mixed") {
    if (!items || items.length === 0) return false;

    /* 1. Chunk large arrays (e.g. Copy All on 2,000+ items) into HTTP Bridge chunks so no payload ever exceeds buffer limits */
    let lastChunkBatchId = "";
    for (let offset = 0; offset < items.length; offset += MAX_HTTP_CHUNK_ITEMS) {
      const slice = items.slice(offset, offset + MAX_HTTP_CHUNK_ITEMS);
      const bId = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      lastChunkBatchId = bId;
      const singlePayloadObj = {
        batch_id: bId,
        action_type: actionLabel,
        timestamp: new Date().toISOString(),
        items: slice
      };
      postSingleBatchOverHttpBridge(BATCH_PREFIX + JSON.stringify(singlePayloadObj));

      /* 2. Push into Rolling Clipboard Ring Buffer & automatically wipe out old batches when clipboard approaches capacity */
      clipboardBatchRing.push({
        batch_id: bId,
        action_type: actionLabel,
        items: slice
      });
    }

    /* Evict oldest batches when ring exceeds MAX_CLIPBOARD_RING_BATCHES or MAX_CLIPBOARD_ITEMS */
    while (clipboardBatchRing.length > MAX_CLIPBOARD_RING_BATCHES) {
      clipboardBatchRing.shift();
      totalBatchesEvicted += 1;
    }
    let totalRingItems = clipboardBatchRing.reduce((acc, b) => acc + b.items.length, 0);
    while (clipboardBatchRing.length > 1 && totalRingItems > MAX_CLIPBOARD_ITEMS) {
      const removed = clipboardBatchRing.shift();
      totalRingItems -= removed ? removed.items.length : 0;
      totalBatchesEvicted += 1;
    }

    const buildRollingClipboardString = () => {
      const ringIds = clipboardBatchRing.map((b) => b.batch_id);
      const mergedItems = [];
      for (const b of clipboardBatchRing) {
        for (const it of b.items) {
          mergedItems.push(it);
        }
      }
      const rollingObj = {
        batch_id: lastChunkBatchId || ringIds[ringIds.length - 1] || `${Date.now()}`,
        batch_ids: ringIds,
        batches: clipboardBatchRing,
        evicted_batches: totalBatchesEvicted,
        action_type: actionLabel,
        timestamp: new Date().toISOString(),
        items: mergedItems
      };
      return BATCH_PREFIX + JSON.stringify(rollingObj);
    };

    let clipboardStr = buildRollingClipboardString();
    /* Byte-cap guard: if long comments make the clipboard JSON exceed MAX_CLIPBOARD_BYTES, wipe out older batches until compact */
    while (clipboardStr.length > MAX_CLIPBOARD_BYTES && clipboardBatchRing.length > 1) {
      clipboardBatchRing.shift();
      totalBatchesEvicted += 1;
      clipboardStr = buildRollingClipboardString();
    }

    writeTextToSystemClipboard(clipboardStr);

    batchesSent += 1;
    const evictedNote = totalBatchesEvicted > 0 ? ` [Auto-pruned ${totalBatchesEvicted} old batches]` : "";
    updateUIStatus(`Synced batch #${batchesSent} (${items.length} items) to Sentra!${evictedNote}`);
    return true;
  }

  function flushUnsentBatch(force = false) {
    if (unsentBatch.length === 0) return;
    if (force || unsentBatch.length >= BATCH_FLUSH_SIZE) {
      const toSend = unsentBatch.splice(0, unsentBatch.length);
      copyBatchToClipboard(toSend, activeAction);
    }
  }

  async function runHumanScrapeLoop() {
    if (!isRunning) return;

    const cfg = SPEED_CONFIGS[speedProfile] || SPEED_CONFIGS.human;
    const targetMap = store[activeAction];

    let targetWin = resolveTargetWindow(activeAction);

    if (!targetWin && (activeAction === "like" || activeAction === "share") && scrollCount === 0) {
      updateUIStatus(`Opening ${activeAction.toUpperCase()} popup automatically...`);
      if (tryAutoOpenPopupForAction(activeAction)) {
        await sleep(2200);
        targetWin = resolveTargetWindow(activeAction);
      }
    }

    if (!targetWin || !targetWin.root) {
      if (targetWin && targetWin.blockedByPopup) {
        stopScraping(
          `⚠️ Close the ${targetWin.blockedByPopup.toUpperCase()} popup first so Comments can be scraped cleanly!`
        );
        return;
      }
      const neededName =
        activeAction === "like"
          ? "Likes / Reactions popup (click the reaction count on the post)"
          : activeAction === "share"
          ? "Shares popup (click 'X shares' on the post)"
          : "Comments section";
      stopScraping(`⚠️ Could not find ${neededName}. Open it first and click Step again!`);
      return;
    }

    if (targetWin.blockedByPopup) {
      stopScraping(
        `⚠️ Close the top ${targetWin.blockedByPopup.toUpperCase()} popup before scraping Comments!`
      );
      return;
    }

    updateUIWindowBadge(targetWin.label);

    if (activeAction === "comment" && scrollCount === 0) {
      await trySwitchToAllComments(targetWin.root);
    }

    if (activeAction === "comment" || activeAction === "share") {
      await ensureOriginalCommentsRevealed(targetWin.root);
    }

    let newCount = harvestVisibleIntoStore(activeAction, targetWin);
    if (scrollCount === 0 && newCount > 0) {
      flushUnsentBatch(true);
    }

    if (activeAction === "comment") {
      if (autoExpandComments(targetWin.root)) {
        updateUIStatus("Clicked 'View more comments' / 'See original' — waiting naturally for load...");
        await sleep(randomInt(1600, 2300));
        await ensureOriginalCommentsRevealed(targetWin.root);
        newCount += harvestVisibleIntoStore(activeAction, targetWin);
      }
    }

    scrollCount += 1;
    const scrolled = await smoothHumanScroll(activeAction, targetWin);

    let settleWait = randomInt(cfg.minWaitMs, cfg.maxWaitMs);
    if (hasVisibleLoadingSpinner(targetWin.root)) {
      updateUIStatus(`Waiting for Facebook spinner to load more ${activeAction}s...`);
      settleWait += randomInt(1900, 2700);
    }
    await sleep(settleWait);

    if (activeAction === "comment" || activeAction === "share") {
      await ensureOriginalCommentsRevealed(targetWin.root);
    }

    newCount += harvestVisibleIntoStore(activeAction, targetWin);

    if (newCount === 0) {
      emptyScrolls += 1;
    } else {
      emptyScrolls = 0;
    }

    flushUnsentBatch(false);
    updateUICounters();
    updateUIStatus(
      `Scroll #${scrollCount} [${targetWin.label}]: +${newCount} new (${targetMap.size} total)`
    );

    if (!isRunning) return;

    const maxEmpty = scrolled ? cfg.maxEmptyScrolls : 6;
    if (emptyScrolls >= maxEmpty) {
      if (activeAction === "like" && targetWin && targetWin.root) {
        const steppedTab = await tryStepToNextReactionTab(targetWin.root);
        if (steppedTab) {
          emptyScrolls = 0;
          harvestVisibleIntoStore(activeAction, targetWin);
          flushUnsentBatch(false);
          updateUICounters();
          stepTimeoutId = setTimeout(runHumanScrapeLoop, randomInt(250, 500));
          return;
        }
      }
      /* Final full action sync so 100% of collected items for this step are guaranteed in Sentra */
      if (targetMap.size > 0) {
        unsentBatch = [];
        copyBatchToClipboard(Array.from(targetMap.values()), activeAction);
      }
      stopScraping(`✅ Finished ${activeAction.toUpperCase()}S (${targetMap.size} total)! Synced all ${targetMap.size} to Sentra.`);
      return;
    }

    stepTimeoutId = setTimeout(runHumanScrapeLoop, randomInt(250, 500));
  }

  function startScraping(actionType) {
    if (isRunning) stopScraping();
    activeAction = actionType;
    isRunning = true;
    emptyScrolls = 0;
    scrollCount = 0;
    lockedScrollEl = null;
    lockedWindowRoot = null;
    if (actionType === "comment") {
      switchedToAllComments = false;
    }
    if (actionType === "like") {
      visitedReactionTabs.clear();
    }
    updateUIStatus(`Detecting ${actionType.toUpperCase()} window...`);
    updateUICounters();
    runHumanScrapeLoop();
  }

  function stopScraping(customMsg) {
    isRunning = false;
    if (stepTimeoutId) {
      clearTimeout(stepTimeoutId);
      stepTimeoutId = null;
    }
    flushUnsentBatch(true);
    updateUICounters();
    if (customMsg) {
      updateUIStatus(customMsg);
    } else {
      updateUIStatus("Stopped & flushed batch to clipboard.");
    }
  }

  window.__FB_CONTEST_SCRAPER_TEARDOWN__ = () => {
    isRunning = false;
    if (stepTimeoutId) {
      clearTimeout(stepTimeoutId);
      stepTimeoutId = null;
    }
    const p = document.getElementById("fb-contest-ext-panel");
    if (p) p.remove();
  };

  function copyAllCollected() {
    const allItems = [
      ...store.like.values(),
      ...store.comment.values(),
      ...store.share.values()
    ];
    if (allItems.length === 0) {
      updateUIStatus("No items collected yet. Click Step 1, 2, or 3 first!");
      return;
    }
    copyBatchToClipboard(allItems, "all");
  }

  function clearAllCollected() {
    stopScraping();
    store.like.clear();
    store.comment.clear();
    store.share.clear();
    unsentBatch = [];
    clipboardBatchRing = [];
    totalBatchesEvicted = 0;
    batchesSent = 0;
    document.querySelectorAll("[data-fb-scraped]").forEach((el) => el.removeAttribute("data-fb-scraped"));
    updateUICounters();
    updateUIStatus("Cleared all counts & clipboard ring buffer.");
  }

  function createFloatingPanel() {
    const existing = document.getElementById("fb-contest-ext-panel");
    if (existing) {
      existing.style.display = "block";
      return existing;
    }

    const panel = document.createElement("div");
    panel.id = "fb-contest-ext-panel";
    panel.style.cssText = [
      "position:fixed",
      "bottom:20px",
      "right:20px",
      "width:328px",
      "background:#111827",
      "color:#f9fafb",
      "border:2px solid #2563eb",
      "border-radius:12px",
      "box-shadow:0 12px 28px rgba(0,0,0,0.45)",
      "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif",
      "font-size:12px",
      "z-index:2147483647",
      "padding:10px 12px",
      "user-select:none"
    ].join(";");

    const header = document.createElement("div");
    header.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;border-bottom:1px solid #374151;padding-bottom:6px;";
    const title = document.createElement("span");
    title.style.cssText = "display:flex;align-items:center;gap:6px;font-weight:800;font-size:13px;color:#ffffff;letter-spacing:0.6px;";
    title.innerHTML = `<svg width="20" height="20" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M 20.3 62.3 A 32 32 0 0 1 62.3 20.3" stroke="#35c5f0" stroke-width="6.5" stroke-linecap="round"/><path d="M 79.7 37.7 A 32 32 0 0 1 37.7 79.7" stroke="#35c5f0" stroke-width="6.5" stroke-linecap="round"/><circle cx="72.6" cy="27.4" r="7.2" stroke="#35c5f0" stroke-width="6" fill="#0b1120"/><circle cx="27.4" cy="72.6" r="7.2" stroke="#35c5f0" stroke-width="6" fill="#0b1120"/><circle cx="50" cy="50" r="8.2" stroke="#35c5f0" stroke-width="6" fill="#0b1120"/></svg><span>SENTRA <span style="color:#35c5f0;font-weight:600;font-size:11px;letter-spacing:0;">• Every signal has a story</span></span>`;
    const minBtn = document.createElement("button");
    minBtn.id = "fb-ext-min-btn";
    minBtn.style.cssText = "background:transparent;border:none;color:#9ca3af;cursor:pointer;font-size:14px;";
    minBtn.textContent = "—";
    header.appendChild(title);
    header.appendChild(minBtn);
    panel.appendChild(header);

    const bodyEl = document.createElement("div");
    bodyEl.id = "fb-ext-body";

    const winBadge = document.createElement("div");
    winBadge.id = "fb-ext-win-badge";
    winBadge.style.cssText = "background:#1e293b;border:1px solid #334155;color:#38bdf8;font-weight:700;font-size:11px;padding:4px 8px;border-radius:6px;margin-bottom:7px;text-align:center;";
    winBadge.textContent = "Locked Window: Auto-Detect Ready";
    bodyEl.appendChild(winBadge);

    const speedRow = document.createElement("div");
    speedRow.style.cssText = "display:flex;align-items:center;justify-content:space-between;margin-bottom:7px;gap:6px;";
    const speedLabel = document.createElement("span");
    speedLabel.style.cssText = "color:#d1d5db;font-weight:600;font-size:11px;";
    speedLabel.textContent = "Scroll Pace:";
    const speedSelect = document.createElement("select");
    speedSelect.style.cssText = "flex:1;background:#1f2937;color:#f9fafb;border:1px solid #374151;border-radius:5px;padding:3px 6px;font-size:11px;";
    const opts = [
      ["human", "🐢 Natural Human (~3.5s, 42% step)"],
      ["slow", "🐌 Extra Careful (~4.8s, 36% step)"],
      ["normal", "🚶 Steady (~2.4s, 50% step)"]
    ];
    for (const [val, txt] of opts) {
      const o = document.createElement("option");
      o.value = val;
      o.textContent = txt;
      if (val === "human") o.selected = true;
      speedSelect.appendChild(o);
    }
    speedSelect.addEventListener("change", () => {
      speedProfile = speedSelect.value;
    });
    speedRow.appendChild(speedLabel);
    speedRow.appendChild(speedSelect);
    bodyEl.appendChild(speedRow);

    const stepCol = document.createElement("div");
    stepCol.style.cssText = "display:flex;flex-direction:column;gap:5px;margin-bottom:8px;";

    function makeBtn(id, label, bg, extraStyle = "") {
      const b = document.createElement("button");
      b.id = id;
      b.textContent = label;
      b.style.cssText = `background:${bg};color:#fff;border:none;border-radius:6px;padding:7px;font-weight:700;cursor:pointer;${extraStyle}`;
      return b;
    }

    const likeBtn = makeBtn("fb-ext-like-btn", "1. Auto-Scrape Likes 👍 (Locks to Likes Popup)", "#1d4ed8");
    const commentBtn = makeBtn("fb-ext-comment-btn", "2. Auto-Scrape Comments 💬 (Locks to Comments)", "#7e22ce");
    const shareBtn = makeBtn("fb-ext-share-btn", "3. Auto-Scrape Shares 🔄 (Locks to Shares Popup)", "#15803d");
    stepCol.appendChild(likeBtn);
    stepCol.appendChild(commentBtn);
    stepCol.appendChild(shareBtn);
    bodyEl.appendChild(stepCol);

    const ctrlRow = document.createElement("div");
    ctrlRow.style.cssText = "display:flex;gap:5px;margin-bottom:8px;";
    const stopBtn = makeBtn("fb-ext-stop-btn", "⏹ Stop & Send", "#dc2626", "flex:1;padding:6px;");
    const copyAllBtn = makeBtn("fb-ext-copyall-btn", "📋 Copy All Now", "#0284c7", "flex:1;padding:6px;");
    const clearBtn = makeBtn("fb-ext-clear-btn", "🗑", "#374151", "padding:6px 8px;color:#e5e7eb;");
    ctrlRow.appendChild(stopBtn);
    ctrlRow.appendChild(copyAllBtn);
    ctrlRow.appendChild(clearBtn);
    bodyEl.appendChild(ctrlRow);

    const countsEl = document.createElement("div");
    countsEl.id = "fb-ext-counts";
    countsEl.style.cssText = "background:#1f2937;padding:6px 8px;border-radius:6px;font-weight:700;margin-bottom:6px;text-align:center;";
    countsEl.textContent = "👍 0 | 💬 0 | 🔄 0 | 📋 Batches: 0";
    bodyEl.appendChild(countsEl);

    const statusEl = document.createElement("div");
    statusEl.id = "fb-ext-status";
    statusEl.style.cssText = "color:#93c5fd;font-size:11px;line-height:1.35;";
    statusEl.textContent = "Ready — Dual-Engine (Reply-Row + Anchor-First + Avatar Sync)!";
    bodyEl.appendChild(statusEl);

    panel.appendChild(bodyEl);
    document.body.appendChild(panel);

    likeBtn.addEventListener("click", () => startScraping("like"));
    commentBtn.addEventListener("click", () => startScraping("comment"));
    shareBtn.addEventListener("click", () => startScraping("share"));
    stopBtn.addEventListener("click", () => stopScraping());
    copyAllBtn.addEventListener("click", () => copyAllCollected());
    clearBtn.addEventListener("click", () => clearAllCollected());

    minBtn.addEventListener("click", () => {
      bodyEl.style.display = bodyEl.style.display === "none" ? "block" : "none";
    });

    return panel;
  }

  function updateUIWindowBadge(label) {
    const el = document.getElementById("fb-ext-win-badge");
    if (!el) return;
    el.textContent = `Locked Window: ${label}`;
  }

  function updateUICounters() {
    const el = document.getElementById("fb-ext-counts");
    if (!el) return;
    el.textContent = `👍 ${store.like.size} | 💬 ${store.comment.size} | 🔄 ${store.share.size} | 📋 Batches: ${batchesSent}`;
  }

  function updateUIStatus(msg) {
    const el = document.getElementById("fb-ext-status");
    if (!el) return;
    el.textContent = msg;
  }

  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      if (msg.cmd === "START") {
        createFloatingPanel();
        startScraping(msg.action);
        sendResponse({ ok: true });
      } else if (msg.cmd === "STOP") {
        stopScraping();
        sendResponse({ ok: true });
      } else if (msg.cmd === "COPY_ALL") {
        copyAllCollected();
        sendResponse({ ok: true });
      } else if (msg.cmd === "GET_COUNTS") {
        sendResponse({
          likes: store.like.size,
          comments: store.comment.size,
          shares: store.share.size,
          batches: batchesSent
        });
      }
      return true;
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createFloatingPanel);
  } else {
    createFloatingPanel();
  }
})();
