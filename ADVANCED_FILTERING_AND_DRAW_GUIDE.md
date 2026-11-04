# 🎯 FairDraw & Advanced Winner Filtering Guide

This guide documents the complete **DrawSystem (FairDraw / Vejal Nai Draw Engine)** feature set and the **Interactive Action Requirement Toggle Bar (`👍 Like` / `💬 Comment` / `🔄 Share`)** integrated into **Facebook Contest Validator**.

---

## 1. Architecture & Feature Parity with `DrawSystem (2).zip`

Every core engine and workflow from `DrawSystem (2).zip` has been deeply integrated into [`AdvancedFilterEngine`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/utils/advanced_filter_engine.py), [`ResultsPanel`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/gui/results_panel.py), [`CustomRuleBuilderDialog`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/gui/custom_rule_dialog.py), and [`LiveLotteryDialog`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/gui/live_lottery_dialog.py) without breaking any existing Phone ADB, Web Browser, or Hybrid 3-Layer Profile Sync workflows:

| `DrawSystem (2).zip` Component | Integrated Module in Facebook Contest Validator | Capabilities |
| :--- | :--- | :--- |
| **`RuleEngine.php` & `WinnerSelectionService.php`** | [`AdvancedFilterEngine`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/utils/advanced_filter_engine.py) | Action requirement toggles (`Like`, `Comment`, `Share`), Boolean `OR` / `AND` / `NOT` keywords, Exact & Whole-Word Bangla/English regex boundaries, Emoji-only detection, Min Length/Words, `@Mention`/`#Hashtag` checks, `1 Entry / Person` deduplication, and sequential `#0001..#NNNN` lottery serial assignment. |
| **`AnalyzerController.php` & `analyzer.blade.php` (Global Intelligence)** | [`CustomRuleBuilderDialog`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/gui/custom_rule_dialog.py) + [`ResultsPanel`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/gui/results_panel.py) | Create unlimited custom analysis rules (`keyword_match`, `keyword_all`, `keyword_exact`, `keyword_exclude`, `regex_match`, `length_greater`, `has_tags`, `action_combo`) that appear as live `🧠 <Rule Name>` `✅ TRUE` / `❌ FALSE` columns in the table and optionally enforce winner qualification. |
| **8 Quick Category Filter Pills (`giveaway.blade.php`)** | [`ResultsPanel`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/gui/results_panel.py) Sub-row 3 | One-click filter pills with live counts and percentages (`%`): `📋 All`, `🏆 Qualified Winners`, `🎯 Correct Answers`, `❌ Wrong Answers`, `🚫 Invalid / Emoji-Only`, `😶 No Comments`, `👯 Duplicates`, `⛔ Disqualified`. |
| **Demographic & Sentiment Intelligence (`analyzer.blade.php`)** | [`AdvancedFilterEngine`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/utils/advanced_filter_engine.py) | Automatic Bangla + English **Gender Detection** (`♂ Male`, `♀ Female`, `Unknown`) and **Sentiment Analysis** (`😊 Positive`, `😐 Neutral`, `😠 Negative`) with live header statistics. |
| **`ParticipantController.php` (Bulk Merge, Clean Duplicates, Disqualify)** | [`ResultsPanel`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/gui/results_panel.py) | **`🔗 Merge Selected`** (combines 2+ rows into one person), **`🧹 Clean Duplicates`** (merges same-name records), and **`🚫 Disqualify / Qualify`** button & right-click context menu. |
| **`DrawEngine.php`, `draw.blade.php`, `winner_card.blade.php`** | [`LiveLotteryDialog`](file:///Users/MacBookPro/Downloads/ShareExtractor-main%202/facebook_share_collector/app/gui/live_lottery_dialog.py) | Cryptographic `secrets.SystemRandom` slot-machine spin, configurable **Spin Duration (2–15 sec)**, **Winners per Spin (1–10)**, **Active Rule Banner**, **`🚫 Disqualify & Re-spin`**, and **`📸 Save Winner Card (PNG)`**. |

---

## 2. 3-Field Chained Action Toggle Bar (`Field 1` ➔ `Dropdown 1` ➔ `Field 2` ➔ `Dropdown 2` ➔ `Field 3`)

Inside the **`🎯 FairDraw Advanced Filtering & Boolean Logic`** bar (Sub-row 0), the **Action Toggle Bar** uses the exact 3-Field Chained layout:

```text
[ ✓ F1 ] [ 👍 Like ▾ ]  ➔  [ AND (&) ▾ ]  ➔  [ ✓ F2 ] [ 💬 Comment ▾ ]  ➔  [ AND (&) ▾ ]  ➔  [ ✓ F3 ] [ 🔄 Share ▾ ]   [ ☐ F1 op (F2 op F3) ]
```

### How Each Element Works:
1. **3 Action Fields (`Field 1`, `Field 2`, `Field 3`)**:
   - Each field has a **toggle button** (`✓ F1`, `✓ F2`, `✓ F3`) and a **dropdown** where you can select:
     - `— Not Selected (Off) —`
     - `👍 Like`
     - `💬 Comment`
     - `🔄 Share`
2. **2 Operator Dropdowns (`Dropdown 1` between F1 & F2, `Dropdown 2` between F2 & F3)**:
   - Inside each operator dropdown, you can select any Boolean operator:
     - **`AND (&)`**: Both fields must match.
     - **`OR (|)`**: Either field matches.
     - **`NOT (AND NOT)`**: Left side matches **AND** right field does **NOT** match.
     - **`OR NOT`**: Left side matches **OR** right field does **NOT** match.
3. **Rule When Field 3 (or Field 2) Is Not Selected**:
   - **If the 3rd field (`F3`) is NOT selected** (either you uncheck `✓ F3` so it shows `✗ F3`, or you choose `— Not Selected (Off) —` in Field 3's dropdown), **Field 3 and Dropdown 2 are completely ignored and NOT applied!** Only `Field 1 [Dropdown 1] Field 2` is evaluated.
   - Similarly, if `Field 2` is not selected, `Dropdown 1 + Field 2` is not applied.
4. **Grouping Checkbox (`F1 op (F2 op F3)`)**:
   - **Unchecked (Default)**: Evaluates left-to-right as `(Field 1 [Op1] Field 2) [Op2] Field 3`.
     - Example: `(Like OR Share) AND Comment` → set `F1 = Like`, `Op1 = OR`, `F2 = Share`, `Op2 = AND`, `F3 = Comment`.
   - **Checked**: Evaluates right-grouped as `Field 1 [Op1] (Field 2 [Op2] Field 3)`.
     - Example: `Comment AND (Like OR Share)` → set `F1 = Comment`, `Op1 = AND`, `F2 = Like`, `Op2 = OR`, `F3 = Share`, and check `F1 op (F2 op F3)`.
5. **`1 Entry/Person` Toggle**:
   - Ensures each unique normalized display name gets at most 1 lottery serial (`#0001`).

---

## 3. 3-Field Chained Keyword Toggle Bar (`K1` ➔ `Dropdown 1` ➔ `K2` ➔ `Dropdown 2` ➔ `K3`)

Sub-row 1 provides the exact same **3-Field Chained layout** for filtering comments and share captions by keywords:

```text
[ ✓ K1 ] [ Field 1 keywords... ]  ➔  [ AND (&) ▾ ]  ➔  [ ✓ K2 ] [ Field 2 keywords... ]  ➔  [ NOT (AND NOT) ▾ ]  ➔  [ ✓ K3 ] [ Field 3 keywords... ]   [ ☐ K1 op (K2 op K3) ]
```

### How the 3-Field Keyword Chain Works:
- **`K1` (`Field 1`)**, **`K2` (`Field 2`)**, **`K3` (`Field 3`)**:
  - Each text box accepts a keyword, phrase, or comma-separated synonyms (e.g. `apple, আপেল, 4, চার`).
  - You can also type full inline boolean expressions inside any field!
- **Operator Dropdowns (`Dropdown 1` & `Dropdown 2`)**:
  - Choose **`AND (&)`**, **`OR (|)`**, **`NOT (AND NOT)`**, or **`OR NOT`** between `K1` & `K2`, and between `K2` & `K3`.
- **If the 3rd Field (`K3`) or 2nd Field (`K2`) Is Not Selected or Empty**:
  - If `✓ K3` is unchecked (`✗ K3`) **or** `Field 3` is left blank, **Field 3 and Dropdown 2 are NOT applied at all!**
  - If `✓ K2` is unchecked (`✗ K2`) **or** `Field 2` is left blank, **Field 2 and Dropdown 1 are NOT applied at all!**
  - When `Dropdown 2` is set to `NOT (AND NOT)` and `K3` has keywords (e.g., `14, ১৪, wrong, spam`), any participant matching `K3` is immediately flagged as **`❌ WRONG ANSWER`** and excluded from winning.

### Match Modes (`Match:` Dropdown) & Smart Bangla ↔ English Digit Equivalence
1. **`Whole Word (Bangla+EN)`** *(Recommended Default)*
   - Uses custom Unicode word boundaries (`(?<![a-zA-Z0-9\u0980-\u09FF])...(?![a-zA-Z0-9\u0980-\u09FF])`) **plus bi-directional Bangla ↔ English numeral normalization (`০-৯` ↔ `0-9`)** so:
     - Typing **`4`** (or **`৪`**) automatically matches **both** `"Answer is 4."` AND `"উত্তর: ৪!"` — while **never** falsely matching `"14"`, `"১৪"`, or `"40"`.
     - Searching for **`ভালো`** matches `"খুব ভালো!"` — but **never** falsely matches `"ভালোবাসি"`.
     - Searching for **`apple`** matches `"I like apple"` — but **never** falsely matches `"pineapple"`.
2. **`Contains (Partial)`**
   - Matches anywhere inside a word or sentence (`"ভালো"` matches `"ভালোবাসি"`).
3. **`Exact Comment Match`**
   - The entire comment (ignoring leading/trailing punctuation/spaces) must equal one of the keywords.
4. **`Custom Regex`**
   - Evaluates your keywords as full Python/PCRE regular expressions.

---

## 4. Content Quality, Gender, Sentiment & Custom Intelligence Rules

Sub-row 2 provides fine-grained quality and demographic filters:

- **`Min Chars` & `Min Words`**: Require comments to have at least `N` characters (e.g., `10` chars) or `M` words (e.g., `3` words) so 1-word spam is filtered out.
- **`🚫 No Emoji-Only`**: Automatically rejects comments that contain only emojis/symbols (`🔥🔥❤️❤️`) with zero Bangla or English letters/digits.
- **`🏷️ Require @Tag/#Hash`**: Requires the participant to mention a friend (`@name`) or include a hashtag (`#contest`).
- **`Gender` Dropdown**: Filter by **`♂ Male`**, **`♀ Female`**, or **`Unknown`** (powered by Bangla + English name dictionaries).
- **`Sentiment` Dropdown**: Filter by **`😊 Positive`** (`আলহামদুলিল্লাহ`, `মাশাল্লাহ`, `ধন্যবাদ`, `অসাধারণ`, `awesome`, `great`, etc.), **`😐 Neutral`**, or **`😠 Negative`**.
- **`🧠 +Custom Rule (N)` Button**:
  - Opens the **Global Intelligence Custom Rule Builder** dialog (`CustomRuleBuilderDialog`).
  - Create named rules (e.g., `"Has Phone Number"`, `"Tagged Friend"`, `"Answered Quiz B"`) using any rule type (`Contains ANY`, `Contains ALL`, `Exact Match`, `Exclude NOT`, `Custom Regex`, `Length >= X`, `Has @/#`, or `Action Combo`).
  - Every rule adds a live **`🧠 <Rule Name>`** column (`✅ TRUE` / `❌ FALSE`) to the table and can be toggled to enforce winner qualification.

---

## 5. Participant Management (`Merge`, `Clean Duplicates`, `Disqualify`)

- **`🔗 Merge Selected`**: Select 2 or more rows in the table (using `Ctrl+Click` or `Shift+Click`) and click **`🔗 Merge Selected`** (or right-click → **Merge Selected Rows into 1 Person**). This combines their Likes, Comments, Shares, and Profile URL into a single unified participant!
- **`🧹 Clean Duplicates`**: Automatically consolidates rows that have the exact same normalized name into a single participant.
- **`🚫 Disqualify`**: Select any row(s) and click **`🚫 Disqualify`** (or right-click) to manually disqualify/re-qualify them. Disqualified participants appear in the `⛔ Disqualified` pill and are excluded from the winner draw.

---

## 6. Live Lottery Spin Draw (`🎰 Live Spin Draw`) & Printable Slips (`🎟️ Print Lottery Tickets`)

When you click **`🎰 Live Spin Draw`**, the stage automatically loads **only the Qualified Winners** that passed your active Action Toggle Bar + Keyword/Filter rules:

1. **Active Rule Banner**: Displays the exact Action & Keyword rules used to qualify the current winner pool at the top of the stage.
2. **Configurable Spin Controls**:
   - **`Winners per Spin`**: Draw `1` to `10` unique winners in a single spin.
   - **`Spin Duration`**: Set the slot-machine reel animation from `2 sec` to `15 sec`.
3. **Spotlight Winner Card Actions**:
   - **`🌐 Open Winner Profile`**: Opens the winner's Facebook profile in your browser for live verification.
   - **`📸 Save Winner Card (PNG)`**: Saves a high-resolution PNG image of the Winner Spotlight Card for posting on your Facebook page.
   - **`🚫 Disqualify & Re-spin`**: Immediately disqualifies the drawn person (updating the main table too) and spins a replacement winner on the spot!
4. **`🎟️ Print Lottery Tickets (PDF/HTML)`**:
   - Generates print-ready cut-out lottery slips (`#0001..#NNNN`) and a **Master Judge Verification Sheet** for all qualified winners matching your active Action Toggle Bar and filter rules.

