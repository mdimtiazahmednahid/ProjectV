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

  let isRunning = false;
  let activeAction = "like";
  let stepTimeoutId = null;
  let emptyScrolls = 0;
  let scrollCount = 0;
  let batchesSent = 0;
  let lastExtractedElements = [];
  let lockedScrollEl = null;
  let lockedWindowRoot = null;
  let switchedToAllComments = false;
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
    "write an answer…", "write an answer...", "write a public comment…", "write a public comment..."
  ]);

  const UTILITY_DIALOG_ARIA_RE = /notification|messenger|chat|account|menu|your profile|settings|search facebook|create post|stories|reels/i;
  const REACTION_SUFFIX_RE = /\s+(?:Liked|Loved|Cared|Haha|Wow|Sad|Angry)$/i;
  const PROFILE_PIC_NOISE_RE = /(?:'s\s+profile\s+(?:picture|photo)|\s+profile\s+(?:picture|photo).*|^profile\s+(?:picture|photo)\s+of\s+|^online\s+status\s+indicator\s*(?:active)?)/i;
  const INLINE_META_SUFFIX_RE = /\s*[·•]\s*(?:\d+\s*(?:s|m|h|d|w|y|sec|min|hr|hrs|day|days|wk|wks|yr|yrs)\b|just now|yesterday|follow|following|1st|2nd|3rd|author|top fan|admin|moderator|rising contributor|top contributor|edited).*$/i;
  const TRAILING_TIME_RE = /\s+\d+\s*(?:s|m|h|d|w|y|sec|min|hr|hrs)\s*$/i;

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
    s = s.replace(PROFILE_PIC_NOISE_RE, "").trim();
    s = s.replace(INLINE_META_SUFFIX_RE, "").trim();
    s = s.replace(REACTION_SUFFIX_RE, "").trim();
    s = s.replace(INLINE_META_SUFFIX_RE, "").trim();
    s = s.replace(TRAILING_TIME_RE, "").trim();
    if (s.endsWith("'s Post") || s.endsWith("’s Post")) return null;
    if (s.length < 2 || s.length > 70) return null;

    const low = s.toLowerCase();
    if (IGNORE_LABELS.has(low)) return null;
    if (
      low.includes("online status indicator") ||
      low.startsWith("profile photo of") ||
      low.startsWith("profile picture of") ||
      low.includes("mutual friend") ||
      low.startsWith("works at ") ||
      low.startsWith("studied at ") ||
      low.startsWith("lives in ") ||
      low.startsWith("from ") ||
      low.startsWith("followed by ") ||
      low.startsWith("see original") ||
      low.startsWith("see translation") ||
      low.startsWith("comment as ") ||
      low.startsWith("reply to ")
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
    const letters = s.match(/\p{L}/gu) || [];
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
    if (cleanLowerPath === "/profile.php") {
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
      if (["posts", "videos", "photos", "about"].includes(secondSeg)) {
        if (hasCommentId) return null;
        segments = [segments[0]];
      } else {
        return null;
      }
    }

    const username = decodeURIComponent(segments[0]).trim();
    if (!username || username.endsWith(".php")) return null;
    if (IGNORE_LABELS.has(username.toLowerCase())) return null;

    return `https://www.facebook.com/${username}`;
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
      if (src.startsWith("http") && !src.includes("emoji.php") && alt.length !== 1 && alt.length !== 2) {
        return src;
      }
    }
    return "";
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
      const firstLine = c.split(/\r?\n/)[0];
      const valid = cleanPersonName(firstLine) || cleanPersonName(c);
      if (valid) return valid;
    }
    return null;
  }

  function classifyDialogWindow(dlg) {
    if (!dlg || dlg.id === "fb-contest-ext-panel") return "utility";
    const aria = cleanText(dlg.getAttribute("aria-label") || "").toLowerCase();
    if (UTILITY_DIALOG_ARIA_RE.test(aria)) return "utility";

    const rect = dlg.getBoundingClientRect();
    if (rect.width < 250 || rect.height < 180) return "utility";
    if (rect.bottom <= 20 || rect.top >= window.innerHeight - 20) return "utility";

    const belongsToThisDialog = (node) => node.closest('div[role="dialog"]') === dlg;

    if (aria.includes("people who shared") || aria.includes("who shared this")) {
      return "share";
    }
    if (aria.includes("people who reacted") || aria === "reactions") {
      return "like";
    }

    const headings = Array.from(dlg.querySelectorAll('h1, h2, h3, [role="heading"], span[dir="auto"]'))
      .filter(belongsToThisDialog)
      .slice(0, 18);
    for (const h of headings) {
      const hTxt = cleanText(h.innerText || h.textContent).toLowerCase();
      if (hTxt === "people who shared this" || hTxt === "who shared this") {
        return "share";
      }
      if (hTxt === "people who reacted" || hTxt === "reactions") {
        return "like";
      }
    }

    const tabs = Array.from(dlg.querySelectorAll('[role="tab"]')).filter(belongsToThisDialog);
    if (tabs.length >= 2) {
      const tabTexts = tabs.map((t) => cleanText(t.innerText || t.getAttribute("aria-label") || "").toLowerCase());
      if (
        tabTexts.some((t) => t === "all" || t.startsWith("all ") || /\d/.test(t) || t.includes("reaction") || t.includes("like") || t.includes("love"))
      ) {
        return "like";
      }
    }

    const replyButtons = Array.from(dlg.querySelectorAll('div[role="button"], span[role="button"], span'))
      .filter((b) => belongsToThisDialog(b) && b.children.length === 0 && cleanText(b.textContent).toLowerCase() === "reply");

    const textboxes = Array.from(dlg.querySelectorAll('[role="textbox"], [contenteditable="true"]')).filter(belongsToThisDialog);
    const hasCommentComposer = textboxes.some((tb) => {
      const placeholder = cleanText(
        tb.getAttribute("aria-label") || tb.getAttribute("aria-placeholder") || tb.getAttribute("placeholder") || ""
      ).toLowerCase();
      return placeholder.includes("comment") || placeholder.includes("reply") || placeholder.includes("answer");
    });

    if (replyButtons.length >= 1 || hasCommentComposer || aria.endsWith("'s post") || aria.endsWith("’s post")) {
      return "comment";
    }

    const postPermalinkLinks = Array.from(
      dlg.querySelectorAll('a[href*="/posts/"], a[href*="story_fbid="], a[href*="/permalink.php"]')
    ).filter(belongsToThisDialog);

    const actionButtons = Array.from(dlg.querySelectorAll('div[role="button"], span[role="button"]'))
      .filter(belongsToThisDialog)
      .map((b) => cleanText(b.innerText || b.getAttribute("aria-label") || "").toLowerCase());

    const addFriendOrFollowCount = actionButtons.filter(
      (txt) => txt === "add friend" || txt === "follow" || txt === "following" || txt === "message"
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

  function tryAutoOpenPopupForAction(actionType) {
    const dialogs = getClassifiedDialogs();
    const commentDialog = [...dialogs].reverse().find((d) => d.kind === "comment");
    const searchRoot = commentDialog ? commentDialog.el : document.body;

    const clickables = Array.from(
      searchRoot.querySelectorAll('div[role="button"], span[role="button"], a[role="link"]')
    );

    if (actionType === "like") {
      for (const el of clickables) {
        if (isInsideIgnoredChrome(el)) continue;
        const aria = cleanText(el.getAttribute("aria-label") || "").toLowerCase();
        const txt = cleanText(el.innerText || el.textContent).toLowerCase();
        if (
          aria.startsWith("all reactions:") ||
          aria.includes("people who reacted") ||
          aria.startsWith("like:") ||
          aria.startsWith("love:") ||
          /^\d+[kmb,.]*\s+reactions?$/i.test(txt)
        ) {
          try {
            el.click();
            return true;
          } catch (e) {}
        }
      }
    } else if (actionType === "share") {
      for (const el of clickables) {
        if (isInsideIgnoredChrome(el)) continue;
        const aria = cleanText(el.getAttribute("aria-label") || "").toLowerCase();
        const txt = cleanText(el.innerText || el.textContent).toLowerCase();
        if (
          /^\d+[kmb,.]*\s+shares?$/i.test(txt) ||
          /^\d+[kmb,.]*\s+shares?$/i.test(aria) ||
          aria.includes("people who shared")
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
          return { root: dialogs[i].el, kind: "like_dialog", label: "👍 Likes Popup Modal" };
        }
      }
      for (let i = dialogs.length - 1; i >= 0; i--) {
        if (dialogs[i].kind === "unknown") {
          return { root: dialogs[i].el, kind: "like_dialog", label: "👍 Likes Popup Modal" };
        }
      }
      if (dialogs.length > 0) {
        return { root: dialogs[dialogs.length - 1].el, kind: "like_dialog", label: "👍 Active Dialog Modal" };
      }
      return { root: mainEl, kind: "like_page", label: "👍 Page View" };
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
      if (dialogs.length > 0) {
        return { root: dialogs[dialogs.length - 1].el, kind: "share_dialog", label: "🔄 Active Dialog Modal" };
      }
      return { root: mainEl, kind: "share_page", label: "🔄 Page View" };
    }

    if (actionType === "comment") {
      const commentDialogs = dialogs.filter((d) => d.kind === "comment");
      if (commentDialogs.length > 0) {
        commentDialogs.sort((a, b) => {
          const ra = a.el.getBoundingClientRect();
          const rb = b.el.getBoundingClientRect();
          return rb.width * rb.height - ra.width * ra.height;
        });
        return {
          root: commentDialogs[0].el,
          kind: "comment_dialog",
          label: "💬 Post Comments Modal",
          blockedByPopup: null
        };
      }
      if (dialogs.length > 0) {
        return {
          root: dialogs[dialogs.length - 1].el,
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
    const filterButtons = scope.querySelectorAll('div[role="button"], span[role="button"]');
    for (const btn of filterButtons) {
      if (isInsideIgnoredChrome(btn)) continue;
      const txt = cleanText(btn.innerText || btn.textContent).toLowerCase();
      if (
        txt === "most relevant" ||
        txt === "newest" ||
        txt === "সবচেয়ে প্রাসঙ্গিক" ||
        txt === "নতুন"
      ) {
        try {
          btn.click();
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
              mTxt.startsWith("সব মন্তব্য ")
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
    switchedToAllComments = true;
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

  function isNoiseCommentBodyLine(text, authorName) {
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
    if (/^(\d+\s*(?:s|m|h|d|w|y|sec|min|hr|hrs|day|days|wk|wks|yr|yrs)|just now|yesterday|\d+[KMB,.]?)$/i.test(low)) {
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
   * Parses a single comment row DOM container (whether found via `<a href>` OR via a leaf `"Reply"` button!)
   * and returns `{ name, url, avatar_url, content, action_type: "comment" }`.
   * Even if Facebook did not hydrate a profile `url` on this comment, keeps the comment with `name` + `avatar_url` + `content`!
   */
  function extractCommentFromSingleRowContainer(rowEl, modalOwnerNameLower = "") {
    if (!rowEl) return null;
    triggerHoverHydration(rowEl);

    let authorUrl = "";
    let authorName = "";

    /* 1. Try finding author URL and Name from any <a href> inside rowEl */
    const links = Array.from(rowEl.querySelectorAll("a[href]"));
    for (const a of links) {
      const cUrl = cleanProfileUrl(a.getAttribute("href") || a.href);
      if (!cUrl) continue;
      if (!authorUrl) authorUrl = cUrl;
      const candName = extractNameFromAnchor(a);
      if (candName) {
        authorName = candName;
        authorUrl = cUrl;
        break;
      }
    }

    /* 2. If authorName wasn't on an <a href> (e.g. unhydrated role="link" or span header like "Ayatullah Mushkan Maryam · 4h"), grab the first valid name in rowEl */
    if (!authorName) {
      const nameCandidates = rowEl.querySelectorAll(
        'a[role="link"], span[role="link"], h3, h4, strong, span[dir="auto"], svg[aria-label], img[alt]'
      );
      for (const nc of nameCandidates) {
        const raw =
          nc.getAttribute("aria-label") ||
          nc.getAttribute("alt") ||
          (nc.innerText || nc.textContent || "").split(/\r?\n/)[0];
        const cleaned = cleanPersonName(raw);
        if (cleaned) {
          authorName = cleaned;
          break;
        }
      }
    }

    if (!authorName) return null;

    /* Skip top modal header if it's just the Post Owner and has no Reply button */
    if (modalOwnerNameLower && authorName.toLowerCase() === modalOwnerNameLower) {
      if (countLeafReplyNodes(rowEl) === 0) {
        return null;
      }
    }

    const avatarUrl = extractAvatarUrlFromContainer(rowEl);

    /* 2b. Ensure "See original" ("মূলটি দেখুন") and "See more" ("আরও দেখুন") inside this row are clicked BEFORE reading comment text */
    let hasActiveSeeOriginal = false;
    const rowBtns = rowEl.querySelectorAll('div[role="button"], span[role="button"], a[role="button"], span[dir="auto"]');
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
        hasActiveSeeOriginal = true;
        try {
          const clickTarget = rb.closest('div[role="button"], span[role="button"], a[role="button"]') || rb;
          clickTarget.click();
          rb.dataset.fbOriginalClicked = "1";
        } catch (e) {}
      } else if ((/^see\s+more$/i.test(rbLabel) || rbLabel === "আরও দেখুন") && rb.dataset.fbExpandClicked !== "1") {
        try {
          const clickTarget = rb.closest('div[role="button"], span[role="button"], a[role="button"]') || rb;
          clickTarget.click();
          rb.dataset.fbExpandClicked = "1";
        } catch (e) {}
      }
    }

    if (hasActiveSeeOriginal) {
      const waits = Number(rowEl.dataset.fbWaitOriginalCount || "0") + 1;
      rowEl.dataset.fbWaitOriginalCount = String(waits);
      if (waits <= 2) {
        /* Wait for Facebook React DOM to replace the English translation with the exact original comment on the next pass */
        return null;
      }
    }

    /* 3. Extract comment body text from dir="auto" blocks */
    const textBlocks = Array.from(rowEl.querySelectorAll('div[dir="auto"], span[dir="auto"]'));
    const bodyParts = [];
    for (const tb of textBlocks) {
      if (
        tb.parentElement &&
        tb.parentElement.closest('[dir="auto"]') &&
        rowEl.contains(tb.parentElement.closest('[dir="auto"]'))
      ) {
        continue;
      }
      const rawT = cleanText(tb.innerText || tb.textContent);
      const cleanedT = rawT.replace(INLINE_META_SUFFIX_RE, "").replace(TRAILING_TIME_RE, "").trim();
      if (isNoiseCommentBodyLine(rawT, authorName) || isNoiseCommentBodyLine(cleanedT, authorName)) {
        continue;
      }
      if (!bodyParts.includes(rawT)) {
        bodyParts.push(rawT);
      }
    }

    /* 4. Emoji-only comment fallback (e.g. ❤️❤️ in Asfia Jahan's comment) */
    if (bodyParts.length === 0) {
      const imgs = Array.from(rowEl.querySelectorAll("img[alt]"));
      for (const im of imgs) {
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
   * Dual-Engine Comment Extractor:
   * Engine A (Leaf "Reply" Button Exact Row Finder): Walks up from every leaf "Reply" button while `countLeafReplyNodes === 1`.
   *   Guarantees 100% extraction on Facebook's `[👍] [👎] Reply` layout even when `<a>` links have no `href` or no `role="article"`!
   * Engine B (Anchor-First `<a href>` Finder): Scans all `<a href>` profile links inside the modal (just like Likes!).
   */
  function extractCommentsFromRoot(root) {
    const found = [];
    const seenKeys = new Set();
    const processedRows = new Set();

    let modalOwnerNameLower = "";
    const titleHeading = root.querySelector("h1, h2, [role='heading']");
    if (titleHeading) {
      const titleTxt = cleanText(titleHeading.innerText || titleHeading.textContent);
      const mOwner = titleTxt.match(/^(.+?)(?:'s|’s)\s+post$/i);
      if (mOwner) {
        modalOwnerNameLower = mOwner[1].trim().toLowerCase();
      }
    }

    const recordComment = (item, rowNode) => {
      if (!item || !item.name) return;
      const idPart = (item.url || item.name).toLowerCase();
      const key = `${idPart}|${item.content}`;
      if (seenKeys.has(key)) return;
      seenKeys.add(key);
      found.push(item);
      if (rowNode) {
        processedRows.add(rowNode);
        lastExtractedElements.push(rowNode);
      }
    };

    /* Engine A: Walk up from every leaf "Reply" node while countLeafReplyNodes === 1 */
    const allSpansAndBtns = Array.from(
      root.querySelectorAll("span:not([data-fb-scraped='1']), div[role='button']:not([data-fb-scraped='1'])")
    );
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
        bestCommentRow = curr;
        curr = curr.parentElement;
      }

      if (bestCommentRow && !processedRows.has(bestCommentRow)) {
        const item = extractCommentFromSingleRowContainer(bestCommentRow, modalOwnerNameLower);
        if (item) {
          if (item.url && item.content) {
            node.dataset.fbScraped = "1";
          }
          recordComment(item, bestCommentRow);
        }
      }
    }

    /* Engine B: Anchor-First <a href> scan (same mechanism that works for Likes!) */
    const allLinks = Array.from(root.querySelectorAll("a[href]:not([data-fb-scraped='1'])"));
    for (const a of allLinks) {
      if (isInsideIgnoredChrome(a)) continue;
      if (a.closest('[role="tab"], [role="tablist"]')) continue;

      /* Skip if already inside one of the processedRows from Engine A */
      let alreadyCovered = false;
      for (const pr of processedRows) {
        if (pr.contains(a)) {
          alreadyCovered = true;
          break;
        }
      }
      if (alreadyCovered) continue;

      const cUrl = cleanProfileUrl(a.getAttribute("href") || a.href);
      if (!cUrl) continue;

      let curr = a.parentElement;
      let bestRow = curr;
      for (let depth = 0; depth < 7 && curr && curr !== root && curr !== document.body; depth++) {
        const otherAnchors = curr.querySelectorAll("a[href]");
        let hasDifferentPerson = false;
        for (const oa of otherAnchors) {
          if (oa === a) continue;
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

    /* Engine C: Comment <div role="article"> scan (covers replies & layout variants without visible Reply buttons) */
    const articles = Array.from(root.querySelectorAll('div[role="article"]'));
    for (const art of articles) {
      if (isInsideIgnoredChrome(art)) continue;
      if (processedRows.has(art)) continue;
      if (art.querySelector('div[role="article"]')) continue; // Only leaf comment articles
      const item = extractCommentFromSingleRowContainer(art, modalOwnerNameLower);
      if (item) {
        recordComment(item, art);
      }
    }

    return found;
  }

  function findRowForAnchor(a, root) {
    let curr = a.parentElement;
    for (let d = 0; d < 5 && curr && curr !== root && curr !== document.body; d++) {
      if (curr.querySelector("svg image, img")) return curr;
      curr = curr.parentElement;
    }
    return a.parentElement || a;
  }

  function extractLikesFromDialog(likeDialog) {
    const found = [];
    triggerHoverHydration(likeDialog);
    const links = Array.from(likeDialog.querySelectorAll("a[href]:not([data-fb-scraped='1'])"));
    const urlToRecord = new Map();
    const orderedUrls = [];

    for (const a of links) {
      if (isInsideIgnoredChrome(a)) continue;
      if (a.closest('[role="tab"], [role="tablist"]')) continue;

      const cUrl = cleanProfileUrl(a.getAttribute("href") || a.href);
      if (!cUrl) continue;

      const name = extractNameFromAnchor(a);
      const rowEl = findRowForAnchor(a, likeDialog);
      const avatarUrl = extractAvatarUrlFromContainer(rowEl);

      if (!urlToRecord.has(cUrl)) {
        orderedUrls.push(cUrl);
        urlToRecord.set(cUrl, { name: name || "", avatar_url: avatarUrl });
      } else {
        const existing = urlToRecord.get(cUrl);
        if (name && (!existing.name || (a.innerText || "").trim().length > 0)) {
          existing.name = name;
        }
        if (avatarUrl && !existing.avatar_url) {
          existing.avatar_url = avatarUrl;
        }
      }
      if (name) {
        a.dataset.fbScraped = "1";
        lastExtractedElements.push(a);
      }
    }

    for (const u of orderedUrls) {
      const rec = urlToRecord.get(u);
      if (rec && rec.name) {
        found.push({
          name: rec.name,
          url: u,
          avatar_url: rec.avatar_url || "",
          content: "",
          action_type: "like"
        });
      }
    }
    return found;
  }

  function extractSharesFromDialog(shareDialog) {
    const found = [];
    triggerHoverHydration(shareDialog);
    const links = Array.from(shareDialog.querySelectorAll("a[href]:not([data-fb-scraped='1'])"));
    const urlToRecord = new Map();
    const orderedUrls = [];

    for (const a of links) {
      if (isInsideIgnoredChrome(a)) continue;
      if (a.closest('[role="tab"], [role="tablist"]')) continue;

      const cUrl = cleanProfileUrl(a.getAttribute("href") || a.href);
      if (!cUrl) continue;

      const name = extractNameFromAnchor(a);
      const rowEl = findRowForAnchor(a, shareDialog);
      const avatarUrl = extractAvatarUrlFromContainer(rowEl);

      if (!urlToRecord.has(cUrl)) {
        orderedUrls.push(cUrl);
        urlToRecord.set(cUrl, { name: name || "", avatar_url: avatarUrl });
      } else {
        const existing = urlToRecord.get(cUrl);
        if (name && (!existing.name || (a.innerText || "").trim().length > 0)) {
          existing.name = name;
        }
        if (avatarUrl && !existing.avatar_url) {
          existing.avatar_url = avatarUrl;
        }
      }
      if (name) {
        a.dataset.fbScraped = "1";
        lastExtractedElements.push(a);
      }
    }

    for (const u of orderedUrls) {
      const rec = urlToRecord.get(u);
      if (rec && rec.name) {
        found.push({
          name: rec.name,
          url: u,
          avatar_url: rec.avatar_url || "",
          content: "",
          action_type: "share"
        });
      }
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
      if (actionType === "comment" && item.content) {
        const hasNonAscii = /[^\x00-\x7F]/.test(item.content);
        /* If an earlier pass captured a truncated prefix or an ASCII-only translation for this same author, replace it with the original/expanded comment */
        for (const [existingKey, existingItem] of Array.from(targetMap.entries())) {
          if (!existingKey.startsWith(`${idKey}|`)) continue;
          const oldContent = (existingItem.content || "").trim();
          if (!oldContent || oldContent === item.content) continue;
          const oldPrefix = oldContent.replace(/[.…\s]+$/, "").trim();
          const isExpandedOfOld = oldPrefix.length >= 8 && item.content.startsWith(oldPrefix) && item.content.length > oldContent.length;
          const isOriginalReplacingTranslated = hasNonAscii && !/[^\x00-\x7F]/.test(oldContent);
          if (isExpandedOfOld || isOriginalReplacingTranslated) {
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
      } else if (item.url && !targetMap.get(key).url) {
        targetMap.get(key).url = item.url;
      }
    }
    return added;
  }

  function isScrollableElement(el) {
    if (!el || el === document.body || el === document.documentElement) return false;
    if (el.scrollHeight <= el.clientHeight + 6 || el.clientHeight < 100 || el.clientWidth < 180) return false;
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
        continue;
      }

      const rawDelta = Math.floor(candidate.clientHeight * cfg.viewportFraction);
      const totalDelta = Math.max(cfg.minScrollPx, Math.min(cfg.maxScrollPx, rawDelta)) + randomInt(0, 22);
      const perStep = Math.max(12, Math.floor(totalDelta / steps));

      candidate.scrollTop = Math.min(maxPossibleTop, candidate.scrollTop + perStep);
      if (candidate.scrollTop <= startTop) {
        continue;
      }

      lockedScrollEl = candidate;
      lockedWindowRoot = targetWin.root;

      for (let i = 1; i < steps; i++) {
        if (!isRunning) break;
        const currMax = Math.max(0, candidate.scrollHeight - candidate.clientHeight);
        candidate.scrollTop = Math.min(currMax, candidate.scrollTop + perStep);
        if (i === Math.floor(steps / 2)) {
          if (actionType === "comment") {
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
          if (actionType === "comment") {
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

    /* Fallback for Comments when inner scroll reaches bottom or 'View more comments' is at bottom of list */
    if (actionType === "comment") {
      if (autoExpandComments(targetWin.root)) {
        return true;
      }
      if (lastExtractedElements.length > 0) {
        try {
          const lastEl = lastExtractedElements[lastExtractedElements.length - 1];
          lastEl.scrollIntoView({ block: "end", behavior: "smooth" });
          await sleep(350);
          return true;
        } catch (e) {}
      }
    }

    return false;
  }

  function copyBatchToClipboard(items, actionLabel = "mixed") {
    if (!items || items.length === 0) return false;
    const payloadObj = {
      batch_id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      action_type: actionLabel,
      timestamp: new Date().toISOString(),
      items: items
    };
    const payloadStr = BATCH_PREFIX + JSON.stringify(payloadObj);

    /* Channel 1: Direct Chrome Extension Background Service Worker -> Desktop App HTTP Bridge (100% immune to focus loss!) */
    try {
      if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
        chrome.runtime.sendMessage({ cmd: "SEND_BATCH", payloadStr: payloadStr }, () => {
          void chrome.runtime.lastError;
        });
      }
    } catch (e) {}

    /* Channel 2: Direct localhost HTTP POST (for Bookmarklet / direct browser mode) */
    try {
      fetch("http://127.0.0.1:19876/batch", {
        method: "POST",
        mode: "cors",
        headers: { "Content-Type": "text/plain;charset=UTF-8" },
        body: payloadStr
      }).catch(() => {});
    } catch (e) {}

    /* Channel 3: System Clipboard backup */
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

    batchesSent += 1;
    updateUIStatus(`Synced batch #${batchesSent} (${items.length} items) to Desktop App!`);
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

    if (activeAction === "comment") {
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

    if (activeAction === "comment") {
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
      stopScraping(`✅ Finished ${activeAction.toUpperCase()}S (${targetMap.size} total)! Click '📋 Copy All Now' if needed.`);
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
    batchesSent = 0;
    document.querySelectorAll("[data-fb-scraped]").forEach((el) => el.removeAttribute("data-fb-scraped"));
    updateUICounters();
    updateUIStatus("Cleared all counts.");
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
