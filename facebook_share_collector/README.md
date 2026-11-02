# Facebook Share Collector

A robust, production-quality Python automation application to collect publicly visible profiles/pages from Facebook's "Shares" list using an Android device, Appium 2, and UiAutomator2, all managed via a PySide6 GUI.

## Prerequisites
- **Python 3.12+**
- **Android Device** connected via USB with Developer Options and **USB Debugging** enabled.
- **Node.js** (for installing Appium 2)
- **ADB (Android Debug Bridge)** installed and added to your system PATH.

## Environment Setup

### 1. Install Appium 2 and UiAutomator2 Driver
```bash
npm install -g appium
appium driver install uiautomator2
```

### 2. Set Up Python Virtual Environment
**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**macOS/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Start Appium Server
Open a separate terminal and run:
```bash
appium
```

### 5. Verify Connected Device
Run `adb devices` in the terminal to verify your Android device is listed and marked as `device` (not `unauthorized`).

## Running the Application

Before running the application, ensure you have activated your virtual environment:
**Windows:**
```bash
.venv\Scripts\activate
```
**macOS/Linux:**
```bash
source .venv/bin/activate
```

Then run the application:
```bash
python3 run.py
# If python3 is not found, you can try: python run.py
```

## Workflow
1. Connect your Android phone to the computer.
2. **Start the Appium Server**: Open a *brand new, separate* terminal window (e.g., a new VS Code terminal tab, or press `Cmd + T` in Mac Terminal) and run:
   ```bash
   appium
   ```
   *Leave this terminal window open and running in the background.*
   *(Note: If Appium fails to connect later complaining about `ANDROID_HOME`, make sure your Android SDK path is exported in your terminal, for example: `export ANDROID_HOME=$HOME/Library/Android/sdk`)*
3. Open another terminal and navigate to the project directory:
   ```bash
   cd facebook_share_collector
   ```
4. Launch the application inside your activated virtual environment (`python3 run.py`).
5. Manually open Facebook on your phone and navigate to the desired post's "Shares" list.
6. In the application GUI, click **Start Collection** to begin collecting profiles.
7. Once completed or stopped, you can search for a name and hit Enter to find it on the device, or export the data.

## Limitations & Privacy
- This application does **NOT** bypass Facebook privacy settings.
- It will only collect publicly/visibly exposed information from the Share list.
- It operates strictly via UI automation, interacting only with what is visible on the screen.
