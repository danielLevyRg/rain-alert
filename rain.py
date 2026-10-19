import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
DEFAULT_LAT = float(os.environ["DEFAULT_LAT"])
DEFAULT_LON = float(os.environ["DEFAULT_LON"])
TEST_MODE = os.environ.get("TEST_MODE") == "yes"

RAIN_MM = 0.2          # כמות גשם ב-15 דקות שנחשבת "גשם"
LOOKAHEAD_MIN = 75     # כמה דקות קדימה מסתכלים
STATE = Path("state.json")
API = f"https://api.telegram.org/bot{TOKEN}"


def send(text):
    r = requests.post(f"{API}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text}, timeout=15)
    r.raise_for_status()


def get_location():
    """המיקום החי האחרון ששיתפת בטלגרם (עד 12 שעות אחורה), אחרת ברירת המחדל."""
    try:
        r = requests.get(f"{API}/getUpdates", params={"offset": -100}, timeout=15)
        r.raise_for_status()
        for u in reversed(r.json()["result"]):
            msg = u.get("edited_message") or u.get("message")
            if not msg or "location" not in msg:
                continue
            if str(msg["chat"]["id"]) != str(CHAT_ID):
                continue
            ts = msg.get("edit_date") or msg["date"]
            if time.time() - ts < 12 * 3600:
                return msg["location"]["latitude"], msg["location"]["longitude"], "live"
    except Exception as e:
        print("location error:", e)
    return DEFAULT_LAT, DEFAULT_LON, "default"


def get_forecast(lat, lon):
    r = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon,
        "minutely_15": "precipitation",
        "timezone": "auto", "forecast_days": 2}, timeout=15)
    r.raise_for_status()
    j = r.json()
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    now = utc_now + timedelta(seconds=j["utc_offset_seconds"])
    slots = [(datetime.fromisoformat(t), p)
             for t, p in zip(j["minutely_15"]["time"], j["minutely_15"]["precipitation"])]
    return now, slots


def main():
    lat, lon, source = get_location()
    print(f"location source: {source}")

    if TEST_MODE:
        send(f"בדיקה: הבוט עובד ✅ (מקור מיקום: {source})")
        return

    now, slots = get_forecast(lat, lon)
    window = [(t, p) for t, p in slots
              if now - timedelta(minutes=15) <= t <= now + timedelta(minutes=LOOKAHEAD_MIN)]

    # אם כבר יורד גשם עכשיו, אין טעם להתריע
    if not window or window[0][1] >= RAIN_MM:
        return
    rain_start = next((t for t, p in window if p >= RAIN_MM), None)
    if rain_start is None:
        return

    # מניעת כפילויות: לא להתריע שוב על אותו גשם
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    last = state.get("last_rain_start")
    if last and abs(datetime.fromisoformat(last) - rain_start) < timedelta(hours=2):
        return

    mins = max(0, int((rain_start - now).total_seconds() // 60))
    send(f"☔ צפוי גשם בעוד כ-{mins} דקות (בערך ב-{rain_start:%H:%M}). קח מטרייה!")
    STATE.write_text(json.dumps({"last_rain_start": rain_start.isoformat()}))


if __name__ == "__main__":
    main()
