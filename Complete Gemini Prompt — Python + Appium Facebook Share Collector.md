You are a senior Python automation engineer specializing in:

- Appium 2
- Python
- Android UI automation
- UiAutomator2
- ADB
- Accessibility/UI hierarchy inspection
- Robust data extraction
- CSV/Excel/JSON generation
- PySide6 desktop applications
- Production-quality automation systems

I want you to build a complete, production-quality **Python + Appium Android automation application** called:

# Facebook Share Collector

The purpose of this application is to help the user collect the publicly/visibly exposed profiles/pages that Facebook displays in the share list of a Facebook post through the official Facebook Android application.

The application will NOT use Facebook's private APIs.

It will NOT bypass Facebook security or privacy controls.

It will operate the user's own Android device through Appium + UiAutomator2 and only process information that is actually exposed through the Facebook Android application's UI/accessibility hierarchy.

---

# 1. CORE OBJECTIVE

The desired workflow is:

User connects Android phone to computer.

↓

Python application detects the phone.

↓

Appium connects to Android.

↓

User opens Facebook manually.

↓

User navigates to their desired Facebook post.

↓

User opens:

"X shares"

or

"View shares"

↓

The Python application detects the Facebook share-list screen.

↓

The collector reads the currently visible UI elements.

↓

It identifies visible profile/page entries.

↓

It extracts available information such as:

- Profile/page name
- Profile URL if exposed
- Share URL if exposed
- Other publicly displayed information relevant to identifying the share

↓

The application scrolls the Facebook share list.

↓

Waits for the UI to update.

↓

Extracts newly visible entries.

↓

Deduplicates previously collected profiles.

↓

Continues until the list appears exhausted.

↓

Displays the total number collected.

↓

Exports:

CSV

JSON

and optionally XLSX.

---

# 2. VERY IMPORTANT LIMITATIONS

The application must NOT:

- bypass Facebook privacy settings
- access private shares
- access hidden/private APIs
- steal authentication cookies
- extract Facebook access tokens
- extract passwords
- intercept Facebook network traffic
- bypass authentication
- use MITM
- reverse-engineer authentication mechanisms
- circumvent rate limits
- bypass security mechanisms
- access information that Facebook does not expose through the UI
- fabricate profile URLs
- guess profile identities
- automatically log into Facebook

The application should only interact with the Facebook Android UI through Appium/UiAutomator2.

If Facebook does not expose a particular piece of information, store it as null/empty rather than guessing.

---

# 3. TECHNOLOGY STACK

Use:

Python 3.12+

Appium 2

Appium Python Client

UiAutomator2

ADB

Android SDK Platform Tools

PySide6 for desktop GUI

Pandas for data processing/export where useful

OpenPyXL for XLSX export

SQLite for persistent local storage

Python logging

Pytest for tests

Use a virtual environment.

Example:

python -m venv .venv

Activate the environment.

Then install dependencies from requirements.txt.

---

# 4. PROJECT STRUCTURE

Create a professional project structure similar to:

facebook_share_collector/

├── README.md
├── requirements.txt
├── .gitignore
├── config.yaml
├── run.py
│
├── app/
│   ├── __init__.py
│   │
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py
│   │   ├── device_panel.py
│   │   ├── collector_panel.py
│   │   ├── results_panel.py
│   │   └── logs_panel.py
│   │
│   ├── automation/
│   │   ├── __init__.py
│   │   ├── appium_manager.py
│   │   ├── device_manager.py
│   │   ├── facebook_detector.py
│   │   ├── share_list_detector.py
│   │   ├── ui_inspector.py
│   │   ├── profile_extractor.py
│   │   ├── scroll_controller.py
│   │   └── collector_engine.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── share_profile.py
│   │   └── collection_session.py
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   └── repository.py
│   │
│   ├── exporters/
│   │   ├── __init__.py
│   │   ├── csv_exporter.py
│   │   ├── json_exporter.py
│   │   └── xlsx_exporter.py
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── text_normalizer.py
│   │   ├── url_normalizer.py
│   │   ├── deduplicator.py
│   │   └── logger.py
│   │
│   └── config/
│       └── settings.py
│
├── tests/
│   ├── test_deduplication.py
│   ├── test_url_normalization.py
│   ├── test_csv_export.py
│   ├── test_profile_extraction.py
│   └── test_text_normalization.py
│
└── data/

You may improve this architecture if you have a better production design.

---

# 5. PHASE 1 — DEVICE DETECTION

The application must first detect Android devices connected through ADB.

Run:

adb devices

Parse the output.

Display:

Device detected:

Samsung Galaxy...

Serial:

XXXXXXXX

State:

Connected

If multiple devices exist, allow the user to choose one.

Handle:

- unauthorized
- offline
- disconnected
- multiple devices
- no devices

Do not silently select an arbitrary device if multiple devices are connected.

---

# 6. PHASE 2 — APPIUM SERVER

The application should support connecting to an Appium 2 server.

Default:

http://127.0.0.1:4723

Provide configuration for:

- Appium host
- Appium port
- device ID
- platform version
- automation name

Check whether Appium is reachable.

Display:

Appium:

CONNECTED

or

NOT CONNECTED

Provide useful error messages.

---

# 7. PHASE 3 — ANDROID SESSION

Create an Appium Android session using UiAutomator2.

Capabilities should include appropriate values such as:

platformName = Android

automationName = UiAutomator2

deviceName = detected device

udid = detected device ID

noReset = true

Do not hard-code a specific user's device.

Use dynamic configuration.

Do not unnecessarily reinstall or reset Facebook.

---

# 8. FACEBOOK PACKAGE

Use the Facebook Android package where applicable:

com.facebook.katana

But do not assume this is always the package.

Create a configuration option:

facebook_package

Default:

com.facebook.katana

Before starting collection, verify that the foreground package is Facebook.

---

# 9. PHASE 4 — UI INSPECTOR

This is extremely important.

Before implementing Facebook-specific extraction, build a powerful UI Inspector.

The inspector should be able to retrieve:

page source

from Appium.

Display the hierarchy in a readable format.

For each node, show:

- class
- text
- content-desc
- resource-id
- clickable
- enabled
- focusable
- scrollable
- selected
- bounds
- package

Example:

Node:

class:
android.widget.TextView

text:
Rahim Ahmed

resource-id:
...

clickable:
true

bounds:
[0,400][1080,480]

The inspector must support:

- save page source to XML
- save parsed node information to JSON
- search nodes by text
- search nodes by class
- search nodes containing "share"
- display clickable nodes
- display scrollable nodes

This inspector will be used to determine how the current Facebook app exposes its share-list UI.

DO NOT invent Facebook selectors.

---

# 10. SHARE-LIST DETECTION

Create a dedicated:

ShareListDetector

It should detect whether the current Facebook screen is likely to be a share list.

Possible text patterns:

English:

Shares

Share

Shared

View shares

See shares

People who shared

Shared by

Bangla:

শেয়ার

শেয়ার

শেয়ার দেখুন

শেয়ার দেখুন

Other localized text should be configurable.

Do not rely only on text.

Combine:

- text
- content descriptions
- clickable nodes
- scrollable containers
- node hierarchy
- screen structure

Return a confidence score.

Example:

ShareListDetectionResult(
    detected=True,
    confidence=0.92
)

---

# 11. PROFILE EXTRACTION

Create:

ProfileExtractor

Its job is to inspect the current UI hierarchy and identify candidate profile/page entries.

Possible signals:

- clickable text node
- image + text relationship
- profile-like URL
- content description
- repeated list-item structure
- nearby profile-related controls

Do not assume one fixed Facebook layout.

The extractor should use a layered heuristic approach.

For example:

Candidate score:

+0.4 if node has a valid Facebook URL

+0.3 if node is clickable

+0.2 if text resembles a person's/page name

+0.1 if node is inside a repeated list structure

Then classify:

>= 0.80 strong candidate

0.60–0.79 probable

<0.60 ignore

Make the thresholds configurable.

---

# 12. PROFILE DATA MODEL

Create:

ShareProfile

Fields:

id

name

profile_url

share_url

source

confidence

first_seen_at

last_seen_at

session_id

Example:

{
    "id": "...",
    "name": "Rahim Ahmed",
    "profile_url": "https://www.facebook.com/...",
    "share_url": null,
    "source": "facebook_android_ui",
    "confidence": 0.93
}

Never fabricate missing data.

---

# 13. URL EXTRACTION

If a Facebook profile URL is exposed through the UI, extract it.

Normalize:

https://facebook.com/username

https://www.facebook.com/username

https://m.facebook.com/username

etc.

Do not convert a person's name into a guessed Facebook URL.

If no URL exists:

profile_url = null

---

# 14. NAME EXTRACTION

Normalize names:

- trim whitespace
- collapse repeated spaces
- remove irrelevant UI labels
- normalize Unicode
- preserve Bangla characters
- preserve emojis when they are genuinely part of displayed names

Do not aggressively strip Unicode.

Do not modify people's names unnecessarily.

---

# 15. DEDUPLICATION

Facebook's list may recycle UI elements during scrolling.

For every candidate, generate a stable deduplication key.

Priority:

1. profile URL
2. exposed Facebook ID
3. share URL
4. normalized name + additional identifying information

Do NOT merge two people solely because their names are identical if other identifying information differs.

Example:

Rahim Ahmed + URL A

Rahim Ahmed + URL B

must remain two records.

---

# 16. SCROLL ENGINE

Create:

ScrollController

It must:

1. Locate the appropriate scrollable element.
2. Capture current page source.
3. Extract candidates.
4. Perform a scroll.
5. Wait for UI update.
6. Capture new page source.
7. Extract candidates.
8. Compare with previous results.
9. Continue.

Do not use fixed coordinate scrolling as the primary method.

Prefer UiAutomator/Appium scrolling APIs.

Potential strategies:

mobile: scrollGesture

UiScrollable

W3C actions

or other current Appium-supported mechanisms.

Choose the most reliable approach.

---

# 17. VIRTUALIZED LISTS

Facebook may recycle list elements.

Therefore:

DO NOT assume the complete list exists in one page source.

The collector must maintain an accumulated set:

Pass 1:

A B C D

Pass 2:

C D E F

Pass 3:

E F G H

Final:

A B C D E F G H

---

# 18. UI WAITING

After scrolling, do not immediately scrape.

Implement:

- explicit waits
- polling
- page-source comparison
- small debounce
- configurable timeout

Example:

scroll

↓

wait for UI change

↓

extract

↓

if UI unchanged:

wait again

↓

retry

Avoid excessive fixed sleeps.

---

# 19. END-OF-LIST DETECTION

Stop when:

- scroll returns false
- no new profiles after N consecutive passes
- page source stops changing
- scroll container is no longer scrollable
- maximum scroll count reached
- maximum runtime reached
- user presses Stop

Default:

MAX_SCROLLS = 500

MAX_NO_NEW_RESULTS = 5

MAX_RUNTIME_MINUTES = 30

MAX_PROFILES = 50_000

All configurable.

---

# 20. COLLECTION STATE MACHINE

Implement a clear state machine:

IDLE

CONNECTING

READY

DETECTING

COLLECTING

SCROLLING

PAUSED

STOPPING

COMPLETED

ERROR

The GUI must reflect the current state.

---

# 21. START/PAUSE/RESUME/STOP

Provide:

Start

Pause

Resume

Stop

When stopped, the collector must immediately stop scrolling.

Do not kill the Appium server unnecessarily.

Do not close Facebook.

Allow the user to resume later if the session remains valid.

---

# 22. GUI

Use PySide6.

Create a polished desktop application.

Main dashboard:

------------------------------------------

Facebook Share Collector

Device:
Samsung Galaxy S...

ADB:
CONNECTED

Appium:
CONNECTED

Facebook:
DETECTED

Status:
COLLECTING

Profiles:
1,248

Scrolls:
83

New this pass:
14

Elapsed:
00:08:42

------------------------------------------

Buttons:

[Connect Device]

[Inspect UI]

[Start Collection]

[Pause]

[Resume]

[Stop]

[Export CSV]

[Export XLSX]

[Export JSON]

[Clear Results]

------------------------------------------

---

# 23. RESULTS TABLE

Show:

#

Name

Profile URL

Share URL

Confidence

First Seen

Last Seen

Allow:

- search
- sort
- filter
- copy URL
- copy name
- remove row

Show:

Total records

Unique profiles

Records without URL

High-confidence records

---

# 24. LIVE LOG

Show logs such as:

17:42:03 Appium connected

17:42:04 Facebook detected

17:42:12 Share list detected

17:42:13 Found 17 candidates

17:42:15 Added 11 new profiles

17:42:17 Scrolling...

17:42:19 Added 8 new profiles

17:42:45 No new profiles

17:42:52 Collection completed

---

# 25. CSV EXPORT

CSV columns:

Name

Profile URL

Share URL

Confidence

Source

First Seen

Last Seen

Session ID

Correctly escape:

commas

quotes

newlines

Unicode

The CSV must work correctly in Excel and Google Sheets.

Use UTF-8.

Prefer UTF-8 BOM if necessary for Excel compatibility.

---

# 26. XLSX EXPORT

Create an XLSX file using OpenPyXL.

Use:

- header row
- autofilter
- freeze panes
- readable column widths
- Unicode support

Filename:

facebook_share_list_YYYY-MM-DD_HH-MM.xlsx

---

# 27. JSON EXPORT

Export valid UTF-8 JSON.

Use:

ensure_ascii=False

Preserve Bangla names correctly.

---

# 28. DATABASE

Use SQLite.

Store:

collection sessions

profiles

relationships between sessions and profiles

Suggested schema:

collection_sessions

profiles

session_profiles

Do not store passwords, cookies, tokens, or authentication information.

---

# 29. RESUMABLE SESSIONS

Allow the user to see previous sessions:

Session #1

Date

Profiles

Duration

Status

Allow:

Open

Export

Delete

---

# 30. CONFIGURATION

Create config.yaml:

appium:
  host: 127.0.0.1
  port: 4723

facebook:
  package: com.facebook.katana

collector:
  max_scrolls: 500
  max_no_new_results: 5
  max_runtime_minutes: 30
  max_profiles: 50000

extraction:
  minimum_confidence: 0.60

Make settings editable from the GUI where appropriate.

---

# 31. ERROR HANDLING

Handle gracefully:

- no Android device
- unauthorized device
- Appium unavailable
- UiAutomator2 unavailable
- Facebook not installed
- Facebook not foreground
- share list not found
- no scrollable container
- stale element
- Appium session crash
- Facebook UI changes
- timeout
- export failure
- database failure
- device disconnect

Never crash silently.

---

# 32. APPIUM SESSION RECOVERY

If Appium session disconnects:

Detect it.

Show:

"Appium session disconnected."

Offer:

[Reconnect]

Do not automatically perform potentially destructive actions.

Do not reset Facebook.

---

# 33. DEBUGGING TOOLS

Add a Developer Tools section:

### UI Inspector

Show:

Current package

Current activity if available

Page source

Node tree

Clickable nodes

Scrollable nodes

Text nodes

Facebook-related nodes

### Save Inspection

Allow saving:

page_source.xml

nodes.json

timestamp

device information

This is extremely important for adapting the collector when Facebook changes its UI.

---

# 34. SELECTOR STRATEGY

Do NOT write code like:

driver.find_element(By.ID, "some_random_facebook_id")

and assume it will always work.

Facebook UI changes.

Instead create selector strategies:

1. accessibility ID
2. text
3. UiSelector
4. XPath only when necessary
5. structural detection
6. scrollable container detection

Keep Facebook-specific selectors in one module.

Example:

facebook_selectors.py

This makes future maintenance easier.

---

# 35. DO NOT OVERUSE XPATH

Avoid fragile XPath such as:

/hierarchy/android.widget.FrameLayout[1]/...

Prefer semantic or structural selectors.

XPath may be used as a fallback only.

---

# 36. OPTIONAL SCREENSHOT SUPPORT

When debugging:

Allow:

Take Screenshot

Save:

screenshots/YYYY-MM-DD_HH-MM-SS.png

This is for debugging UI detection.

Do not continuously record the device screen unnecessarily.

---

# 37. OPTIONAL OCR FALLBACK

Design the architecture so OCR can be added later.

If the accessibility/UI hierarchy does not expose usable names:

Screenshot

↓

OCR

↓

Candidate text

↓

Validation

↓

Deduplication

Do not make OCR the default.

Do not use OCR to bypass privacy restrictions.

---

# 38. PERFORMANCE

The application should not:

- capture screenshots unnecessarily
- call page_source repeatedly without reason
- scroll too rapidly
- overload the Android device
- overload Appium

Use reasonable delays and event/state-based waiting.

---

# 39. THREADING

The GUI must remain responsive.

Do not run Appium collection on the PySide6 GUI thread.

Use:

QThread

or

QRunnable/QThreadPool

or an appropriate asyncio/thread architecture.

The UI should remain usable while collection is running.

---

# 40. LOGGING

Use Python's logging module.

Log to:

console

and:

logs/app.log

Levels:

DEBUG

INFO

WARNING

ERROR

Do not log:

passwords

cookies

access tokens

authentication headers

private credentials

---

# 41. TESTING

Write unit tests for:

text normalization

URL normalization

duplicate detection

confidence scoring

CSV export

JSON export

XLSX export

end-of-list detection

collection state transitions

Create mock page-source XML files for testing the parser without Facebook.

Example:

tests/fixtures/facebook_share_list_01.xml

The tests must run without an Android device.

---

# 42. MOCK MODE

Implement a Mock/Offline Mode.

This allows development without:

Android phone

Facebook

Appium

The mock mode should load saved XML UI hierarchies and run the extraction engine against them.

This is extremely important for development and testing.

---

# 43. FIRST-RUN WIZARD

When the application launches for the first time:

Step 1:

Check Python dependencies.

Step 2:

Check ADB.

Step 3:

Check connected Android device.

Step 4:

Check Appium.

Step 5:

Check UiAutomator2 driver.

Step 6:

Test Appium connection.

Show clear green/red status indicators.

---

# 44. README

Write a complete README explaining:

Prerequisites

Python installation

Android Developer Options

USB Debugging

ADB installation

Appium installation

UiAutomator2 installation

Python virtual environment

requirements installation

Running the application

Connecting phone

Opening Facebook

Opening the share list

Starting collection

Exporting data

Troubleshooting

Facebook UI changes

Known limitations

Privacy/security

---

# 45. INSTALLATION COMMANDS

Provide exact commands.

For example:

python -m venv .venv

Windows:

.venv\Scripts\activate

macOS/Linux:

source .venv/bin/activate

pip install -r requirements.txt

Install Appium 2:

npm install -g appium

Install UiAutomator2:

appium driver install uiautomator2

Start Appium:

appium

Verify:

adb devices

---

# 46. DEVELOPMENT ORDER

Do NOT build the entire scraper blindly.

Follow this order:

PHASE 1

Device detection

↓

PHASE 2

Appium connection

↓

PHASE 3

Facebook detection

↓

PHASE 4

UI Inspector

↓

PHASE 5

Share-list detection

↓

PHASE 6

Profile extraction

↓

PHASE 7

Deduplication

↓

PHASE 8

Scrolling

↓

PHASE 9

Collection engine

↓

PHASE 10

SQLite

↓

PHASE 11

CSV/JSON/XLSX export

↓

PHASE 12

PySide6 GUI

↓

PHASE 13

Testing

↓

PHASE 14

Packaging

---

# 47. CRITICAL REQUIREMENT: INSPECT BEFORE SCRAPING

Do NOT assume that Facebook's current UI exposes profile names or URLs in a particular way.

The first working milestone must be:

"Facebook UI Inspector"

The user should be able to:

1. Connect phone.
2. Open Facebook.
3. Open the share list.
4. Click "Inspect UI."
5. See the complete relevant UI hierarchy.
6. Save it to XML/JSON.

Only after analyzing that actual hierarchy should Facebook-specific extraction rules be finalized.

If necessary, ask the user to provide the generated XML/page source for their Facebook version.

Do not invent selectors.

---

# 48. PROFILE IDENTIFICATION

The collector must distinguish between:

Actual profile/page entries

and

UI controls such as:

Share

Like

Comment

Follow

Invite

See more

Back

Close

Search

Menu

Do not accidentally add these as profiles.

Use context and structural analysis.

---

# 49. MULTILINGUAL SUPPORT

The user may use Facebook in Bangla or English.

Therefore:

Do not hardcode only English.

Create a localization/configuration dictionary.

Example:

SHARE_TERMS = {
    "en": [...],
    "bn": [...]
}

The extraction engine itself should remain language-independent where possible.

---

# 50. NO FAKE DATA

This is mandatory.

If the application sees:

"Rahim Ahmed"

but no URL:

save:

name = "Rahim Ahmed"

profile_url = null

Do NOT produce:

https://facebook.com/rahimahmed

unless Facebook actually exposed that URL.

---

# 51. FINAL DELIVERABLE

I want a complete, runnable project.

Do not provide pseudocode where actual implementation is expected.

Do not say:

"implement this yourself"

"etc."

"the remaining files are similar"

or

"you can add this later"

Provide the actual files.

For every file, clearly show:

FILE: path/to/file.py

Then provide the complete contents.

---

# 52. FINAL RESPONSE FORMAT

Your response must be structured as:

## Part 1 — Technical Analysis

Explain the architecture and limitations.

## Part 2 — Project Structure

Show the complete directory tree.

## Part 3 — Environment Setup

Exact installation commands.

## Part 4 — Phase 1

Device detection implementation.

## Part 5 — Phase 2

Appium implementation.

## Part 6 — Phase 3

UI Inspector.

## Part 7 — Phase 4

Facebook share-list detector.

## Part 8 — Phase 5

Profile extraction.

## Part 9 — Phase 6

Scrolling engine.

## Part 10 — Phase 7

Collection engine.

## Part 11 — Phase 8

Database.

## Part 12 — Phase 9

Exports.

## Part 13 — Phase 10

PySide6 GUI.

## Part 14 — Tests.

## Part 15 — README.

## Part 16 — Final consistency review.

Before finishing, check every import, class name, method name, dependency, configuration key, database table, signal, slot, and file path for consistency.

The final project must be runnable with:

python run.py

---

# 53. IMPORTANT DEVELOPMENT PRINCIPLE

Think like a reverse-engineering/debugging engineer, not a simple web scraper.

The Facebook Android UI is dynamic and can change.

Therefore the system must be:

ROBUST

OBSERVABLE

CONFIGURABLE

RECOVERABLE

MODULAR

TESTABLE

Do not optimize for a single screenshot.

Optimize for resilience across Facebook UI changes.

Begin by designing the architecture and then implement the project in the development order above.