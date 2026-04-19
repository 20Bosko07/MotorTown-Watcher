import cv2
import mss
import numpy as np
import pytesseract
import time
import keyboard
import logging
import asyncio
import os
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn
import cv2
import numpy as np
import mss
import pytesseract
import time
import base64
import os
import re
import asyncio
import keyboard
import logging
from collections import deque
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import socketio
import re
import pygetwindow as gw
import base64
from collections import deque

tess_paths = [
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    r'C:\Users\\' + os.getlogin() + r'\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'
]
for p in tess_paths:
    if os.path.exists(p):
        pytesseract.pytesseract.tesseract_cmd = p
        break

if not os.path.exists(pytesseract.pytesseract.tesseract_cmd):
    print("!!! ERROR: TESSERACT OCR NOT FOUND !!!")
    print("Please install Tesseract OCR from: https://github.com/UB-Mannheim/tesseract/wiki")
    print("The app will not recognize any text until it is installed.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(background_task())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, app)
templates = Jinja2Templates(directory="templates")

class MotorTownAnalyzer:
    def __init__(self):
        self.sct = mss.mss()
        self.monitor_full = self.sct.monitors[1]

        self.monitor_km = {"top": 990, "left": 5, "width": 250, "height": 45}
        self.monitor_ap = {"top": 400, "left": 1600, "width": 300, "height": 100}
        self.monitor_dash = {"top": 700, "left": 1300, "width": 350, "height": 350}
        self.current_km = 0
        self.arrive_notified = False
        self.stuck_notified = False
        self.last_km = 0.0
        self.fuel_percent = 50
        self.temp_percent = 50
        self.autopilot_on = False
        self.jobs_done = 0
        self.total_km_driven = 0
        self.stuck_time = 0
        self.last_update_time = time.time()
        self.km_history = deque(maxlen=30)
        self.pending_km = None
        self.pending_km_count = 0
        self.last_km_raw = ""
        self.latest_b64_image = ""
        self.latest_b64_dash = ""
        self.custom_km_rect_pct = None

        if os.path.exists("config.json"):
            try:
                with open("config.json", "r") as f:
                    data = json.load(f)
                    if "km_rect_pct" in data:
                        self.custom_km_rect_pct = data["km_rect_pct"]
            except Exception:
                pass

    def _extract_km_values(self, km_text: str):
        km_clean = km_text.lower()
        # OCR cleanup before regex parsing.
        km_clean = km_clean.replace('o', '0').replace('O', '0').replace('l', '1').replace('I', '1')
        km_clean = re.sub(r'ca\.?\s*\d+\s*(min)?\b', ' ', km_clean)
        km_clean = re.sub(r'\d+\s*min\b', ' ', km_clean)

        for w in ['ca.', 'ca', 'min.', 'min', 'ata', 'eta', 'verbleibend', '-']:
            km_clean = km_clean.replace(w, ' ')

        # Remove common time/temperature artifacts that often appear in OCR output.
        km_clean = re.sub(r'\b\d{1,2}[:\.]\d{2}\b', ' ', km_clean)
        km_clean = re.sub(r'\d+\s*°c\b', ' ', km_clean, flags=re.IGNORECASE)
        km_clean = re.sub(r'\d+\s*c\b', ' ', km_clean, flags=re.IGNORECASE)
        km_clean = re.sub(r'\d+\s*Â°C', ' ', km_clean, flags=re.IGNORECASE)

        # Accept only values with explicit unit (km/m) to avoid clock/time false positives.
        values = []
        for m in re.finditer(r'([0-9]+(?:[\.,][0-9]+)?)\s*(km|m)\b', km_clean, re.IGNORECASE):
            try:
                val = float(m.group(1).replace(',', '.'))
                unit = m.group(2).lower()
                val_km = val / 1000.0 if unit == 'm' else val
                if 0.02 <= val_km < 250.0:
                    values.append(val_km)
            except Exception:
                pass
        return values

    def _choose_best_km_candidate(self, candidates):
        vals = [v for v in candidates if v is not None and v >= 0]
        if not vals:
            return None
        if self.current_km > 0.01:
            # Prevent picking up static map scales if possible. Since we usually drive towards 0, 
            # favor candidates that are smaller than current_km, unless there's a valid jump.
            valid_progress_vals = [v for v in vals if v < self.current_km + 0.1]
            if valid_progress_vals:
                return min(valid_progress_vals, key=lambda v: abs(v - self.current_km))

            # Recovery: if there is a clearly higher explicit km value, prefer it.
            if len(vals) >= 2 and (max(vals) - min(vals)) > 1.5 and max(vals) > (self.current_km + 1.0):
                return max(vals)
            return min(vals, key=lambda v: abs(v - self.current_km))
        return max(vals)

    def _required_stable_frames(self, current_median: float, candidate_km: float):
        diff = abs(candidate_km - current_median)
        if diff > 8.0:
            return 6
        if diff > 4.0:
            return 5
        if diff > 2.0:
            return 4
        if diff > 1.0:
            return 3
        if diff > 0.4:
            return 2
        return 1

    def update_coords_from_window(self):
        try:
            windows = [w for w in gw.getWindowsWithTitle("Motor Town") if 'Watcher' not in w.title]
            if windows:
                win = windows[0]
                if win.width > 200 and win.height > 200:
                    self.monitor_full = {"top": max(0, win.top), "left": max(0, win.left), "width": win.width, "height": win.height}
                    if getattr(self, 'custom_km_rect_pct', None):
                        pt = self.custom_km_rect_pct
                        self.monitor_km = {
                            "top": win.top + int(win.height * pt['y']),
                            "left": win.left + int(win.width * pt['x']),
                            "width": int(win.width * pt['w']),
                            "height": int(win.height * pt['h'])
                        }
                    else:
                        self.monitor_km = {
                            "top": win.top + win.height - int(win.height * 0.084),
                            "left": win.left + int(win.width * 0.003),
                            "width": int(win.width * 0.15),
                            "height": int(win.height * 0.045)
                        }
                    self.monitor_ap = {
                        "top": win.top + int(win.height * 0.37),
                        "left": win.left + int(win.width * 0.80),
                        "width": int(win.width * 0.18),
                        "height": int(win.height * 0.12)
                    }
                    self.monitor_dash = {
                        "top": win.top + win.height - int(win.height * 0.35),
                        "left": win.left + int(win.width * 0.65),
                        "width": int(win.width * 0.35),
                        "height": int(win.height * 0.35)
                    }
        except Exception:
            pass

    def get_text_from_image(self, monitor_area, debug_filename=None, ocr_config='--psm 7'):
        try:
            img_np = np.array(self.sct.grab(monitor_area))
            hsv = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
            hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)
            
            mask = cv2.inRange(hsv, (0, 0, 150), (180, 255, 255))
            inv = cv2.bitwise_not(mask)
            
            z = cv2.resize(inv, (0,0), fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)

            if debug_filename:
                cv2.imwrite(debug_filename, z)

            text = pytesseract.image_to_string(z, config=ocr_config)
            return text.strip()
        except Exception as e:
            print(f"[OCR Error] Could not read image: {e}")
            return ""

    def analyze_frame(self):
        self.update_coords_from_window()
        km_text_1 = self.get_text_from_image(
            self.monitor_km,
            "debug_km.png",
            ocr_config='--psm 7 -c tessedit_char_whitelist=0123456789.,:kmKMm '
        )
        km_text_2 = self.get_text_from_image(
            self.monitor_km,
            None,
            ocr_config='--psm 8 -c tessedit_char_whitelist=0123456789.,:kmKMm '
        )
        self.last_km_raw = km_text_1 or km_text_2

        try:
            dash_img_np = np.array(self.sct.grab(self.monitor_dash))
            dash_bgr = cv2.cvtColor(dash_img_np, cv2.COLOR_BGRA2BGR)
            _, buf = cv2.imencode('.jpg', dash_bgr, [cv2.IMWRITE_JPEG_QUALITY, 50])
            self.latest_b64_dash = base64.b64encode(buf).decode('utf-8')        
        except Exception:
            pass

        # KM parsing + robust jump filter
        try:
            all_candidates = []
            all_candidates.extend(self._extract_km_values(km_text_1))
            all_candidates.extend(self._extract_km_values(km_text_2))
            candidate_km = self._choose_best_km_candidate(all_candidates)

            if candidate_km is not None and candidate_km >= 0:
                new_km = candidate_km

                # Guard against OCR digit-loss like 34.2 -> 4.x caused by missing leading digit.
                if self.current_km >= 5.0 and new_km < (self.current_km * 0.55):
                    looks_like_dropped_leading_digit = abs((new_km * 10.0) - self.current_km) <= max(2.5, self.current_km * 0.35)
                    if looks_like_dropped_leading_digit:
                        new_km = self.current_km
                        self.pending_km = None
                        self.pending_km_count = 0

                if len(self.km_history) >= 2:
                    current_median = sorted(list(self.km_history))[len(self.km_history) // 2]
                    required = self._required_stable_frames(current_median, new_km)

                    # Additional guard for unrealistic drops in one second.
                    if self.current_km > 0 and (self.current_km - new_km) > 0.25:
                        required = max(required, 4)
                    if self.current_km > 2.0 and (self.current_km - new_km) > 1.0:
                        required = max(required, 5)
                    if self.current_km > 8.0 and (self.current_km - new_km) > 3.0:
                        required = max(required, 6)
                    # Strong guard for "suddenly below 200m" jumps.
                    if self.current_km > 0.8 and new_km < 0.2:
                        required = max(required, 8)
                    
                    # Prevent large jump directly to under 50m (often false detection when arrived)
                    if self.current_km > 1.0 and new_km <= 0.05:
                        required = max(required, 15)

                    if required > 1:
                        stable_band = max(0.30, 0.05 * max(new_km, self.pending_km if self.pending_km is not None else new_km))
                        if self.pending_km is not None and abs(self.pending_km - new_km) <= stable_band:
                            self.pending_km_count += 1
                        else:
                            self.pending_km = new_km
                            self.pending_km_count = 1

                        if self.pending_km_count < required:
                            new_km = self.current_km
                        else:
                            # Lock accepted value and reset history to avoid bounce-back.
                            new_km = self.pending_km if self.pending_km is not None else new_km
                            self.pending_km = None
                            self.pending_km_count = 0
                            self.km_history.clear()
                    else:
                        self.pending_km = None
                        self.pending_km_count = 0
                else:
                    self.pending_km = None
                    self.pending_km_count = 0

                # Snap to 0 (arrived/stop) if 50 meters or less, meaning the route likely disappeared
                if new_km <= 0.05 and new_km > 0.0:
                    new_km = 0.0

                self.km_history.append(new_km)

                if new_km > self.current_km + 3 and self.current_km < 0.5:
                    self.jobs_done += 1
                if self.current_km > 0 and 0 <= self.current_km - new_km < 5:
                    self.total_km_driven += (self.current_km - new_km)

                self.last_km = self.current_km
                self.current_km = new_km

        except Exception:
            pass

        # Autopilot
        try:
            ap_img = np.array(self.sct.grab(self.monitor_ap))
            hsv = cv2.cvtColor(ap_img, cv2.COLOR_BGRA2BGR)
            hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)
            lower_yellow = np.array([12, 100, 150])
            upper_yellow = np.array([45, 255, 255])
            yellow_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
            cv2.imwrite("debug_ap_yellow.png", yellow_mask)
            yellow_pixels = cv2.countNonZero(yellow_mask)
            self.autopilot_on = yellow_pixels > 50
        except Exception:
            pass

        if self.autopilot_on and abs(self.current_km - self.last_km) < 0.05:
            self.stuck_time += 1
        else:
            self.stuck_time = 0

        try:
            full_img_np = np.array(self.sct.grab(self.monitor_full))
            full_resized = cv2.resize(cv2.cvtColor(full_img_np, cv2.COLOR_BGRA2BGR), (800, 450))
            _, buf = cv2.imencode('.jpg', full_resized, [cv2.IMWRITE_JPEG_QUALITY, 30])
            self.latest_b64_image = base64.b64encode(buf).decode('utf-8')
        except Exception:
            pass

        # State updates (OS notifications handled by browser instead)
        self.arrived = False
        if 0.0 < self.current_km < 0.15: # < 150m = arrived
            self.arrived = True

    def get_status(self):
        km_display = f"{int(self.current_km * 1000)} m" if self.current_km < 1.0 else f"{self.current_km:.1f} km"
        is_stuck = getattr(self, 'stuck_time', 0) > 30 and not getattr(self, 'arrived', False)
        return {
            "km": km_display,
            "autopilot": getattr(self, 'autopilot_on', False),
            "stuck_alert": is_stuck,
            "arrive_alert": self.current_km < 1.0 and self.current_km >= 0.15,
            "arrived": getattr(self, 'arrived', False),
            "jobs_done": self.jobs_done,
            "total_km": f"{self.total_km_driven:.1f}",
            "dash_img": f"data:image/jpeg;base64,{self.latest_b64_dash}",
            "screenshot": f"data:image/jpeg;base64,{self.latest_b64_image}"
        }

analyzer = MotorTownAnalyzer()

@app.get('/manifest.json')
async def get_manifest():
    return FileResponse('templates/manifest.json')

@app.get('/sw.js')
async def get_sw():
    return FileResponse('templates/sw.js')

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")       

@sio.on('connect')
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.on('brake_now')
async def handle_brake(sid):
    print("EMERGENCY BRAKE TRIGGERED FROM WEB!")
    keyboard.press('5')
    await asyncio.sleep(0.1)
    keyboard.release('5')
    await asyncio.sleep(0.1)
    for _ in range(8):
        keyboard.press('s')
        await asyncio.sleep(0.4)
        keyboard.release('s')
        await asyncio.sleep(0.2)
    keyboard.press('space')
    keyboard.press('s')
    await asyncio.sleep(15.0)
    keyboard.release('s')
    keyboard.release('space')

async def background_task():
    while True:
        try:
            analyzer.analyze_frame()
            status = analyzer.get_status()
            await sio.emit('update', status)
        except Exception as e:
            print(f"Error in background task: {e}")
        await asyncio.sleep(1)

def check_and_ask_roi(analyzer_instance):
    if analyzer_instance.custom_km_rect_pct is not None:
        return 

    print("\n=======================================================")
    print("[SETUP] Dein KM Bereich auf dem Bildschirm wird nicht erkannt?")
    print("[SETUP] Willst du den Bereich EINMALIG und MANUELL mit der Maus markieren?")
    print("        Druecke J (fuer Ja) oder N (fuer Nein / Standard verwenden).")
    print("=======================================================")
    
    try:
        import pygetwindow as gw
        choice = input("Deine Wahl (J/N): ").strip().lower()
        if choice != 'j':
            return
            
        print("\n[SETUP] Motor Town Fenster wird gesucht...")
        windows = [w for w in gw.getWindowsWithTitle("Motor Town") if 'Watcher' not in w.title]
        if not windows:
            print("[FEHLER] Motor Town ist nicht offen! Starte erst das Spiel. Verwende Standard.")
            time.sleep(3)
            return
            
        win = windows[0]
        if win.width < 200 or win.height < 200:
            print("[FEHLER] Das Motor Town Fenster ist minimiert! Verwende Standard.")
            time.sleep(3)
            return

        with mss.mss() as sct:
            mon = {"top": max(0, win.top), "left": max(0, win.left), "width": win.width, "height": win.height}
            img_np = np.array(sct.grab(mon))
            bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
            
            windowname = "KM Bereich ziehen (Danach ENTER druecken!)"
            cv2.namedWindow(windowname, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(windowname, int(win.width * 0.7), int(win.height * 0.7))
            cv2.setWindowProperty(windowname, cv2.WND_PROP_TOPMOST, 1)
            
            print("[SETUP] Ein Screenshot hat sich geoeffnet!")
            print("[SETUP] Bitte ziehe jetzt mit der Maus einen Rahmen GENAU um die KM Anzeige. Druecke anschliessend die ENTER Taste zu bestaetigen.")
            roi = cv2.selectROI(windowname, bgr, showCrosshair=True, fromCenter=False)
            cv2.destroyWindow(windowname)
            
            if roi[2] > 0 and roi[3] > 0:
                pct = {
                    "x": roi[0] / mon["width"],
                    "y": roi[1] / mon["height"],
                    "w": roi[2] / mon["width"],
                    "h": roi[3] / mon["height"]
                }
                analyzer_instance.custom_km_rect_pct = pct
                with open("config.json", "w") as f:
                    json.dump({"km_rect_pct": pct}, f)
                print(f"[ERFOLG] Neuer KM Bereich PERFEKT gespeichert! Er wird von nun an fuer dein Spiel verwendet.")
            else:
                print("[SETUP] Auswahl abgebrochen. Verwende Standard.")
    except Exception as e:
        print(f"[FEHLER] Konnte Bereich nicht setzen: {e}")

if __name__ == "__main__":
    check_and_ask_roi(analyzer)
    uvicorn.run(socket_app, host="0.0.0.0", port=5000)