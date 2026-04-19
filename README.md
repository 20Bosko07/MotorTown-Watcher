# MotorTown Watcher

A smart companion app and dashboard for the driving simulator **Motor Town: Behind The Wheel**.

MotorTown Watcher uses screen capture and OCR to track your driving progress in real-time, displays a dashboard, and alerts you via audio/browser notifications whenever something happens (e.g. reaching a destination, getting stuck on autopilot, remaining distance).

## Features
- 🏎️ **Live Dashboard:** Displays your current remaining kilometers.
- 🛜 **Remote Notifications:** Push notifications to your phone/second screen when you arrive!
- 🤖 **Autopilot Detection:** Triggers an alert if your vehicle gets stuck while using autopilot.
- 🛑 **Emergency Brake:** Remote emergency brake functionality.

## Prerequisites
1. **[Python 3.10+](https://www.python.org/downloads/)**
   - **Important:** Make sure to check the box `Add Python to PATH` when installing!
2. **[Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)**
   - **Important:** Tesseract must be installed at `C:\Program Files\Tesseract-OCR\tesseract.exe` (this is the default installer location).

## Installation

Go to the [Releases page](https://github.com/20Bosko07/MotorTown-Watcher/releases/latest) and download the latest zip file containing the project. 

Extract the `.zip` file on your computer to any convenient location.

## Quick Start
1. Double-click the `start.bat` file in the folder.
2. The script will automatically install missing Python dependencies and check for updates.
3. Your browser will open showing the Dashboard on `http://localhost:5000`.
4. Ensure the game **Motor Town** runs in borderless/windowed mode on your primary monitor so the tracker can observe the screen.

## Auto Update Check
Every time you launch `start.bat`, the script queries GitHub for the latest release tag. It will notify you in the command console if you are not running the newest version.

## Troubleshooting
- **No data incoming:** Ensure the game window is not completely minimized or covered. The app analyzes specific coordinates of the Motor Town window. Make sure you don't scale the UI too drastically.
- **Python/Tesseract Error:** Check if Python is in your `PATH` variables, and ensure `tesseract.exe` exists in `C:\Program Files\Tesseract-OCR\`.

## License
MIT
