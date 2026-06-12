"""
SunShift — automatically switches Windows between light mode (day) and
dark mode (night), following the real sunrise and sunset for your location.

How it works, in three parts:
  1. LOCATION  — on first run we ask ipinfo.io "where am I?" (based on your
     IP address) and save the answer to sunshift_config.json. You can edit
     that file by hand any time if the guess is off.
  2. SUN TIMES — the `astral` library computes today's sunrise and sunset
     from your latitude/longitude. No internet needed after first run.
  3. THE SWITCH — Windows keeps light/dark mode in two registry values.
     We set them to 1 (light) while the sun is up, 0 (dark) after sunset,
     then tell all running apps "settings changed!" so they update live.

Usage:
  python sunshift.py            run forever, switching at each sunrise/sunset
  python sunshift.py --once     set the correct theme for right now, then exit
  python sunshift.py --status   show location, sun times and current theme
"""

import ctypes
import json
import sys
import time
import winreg
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from astral import Observer
from astral.sun import sun, elevation

# Config lives next to the script (or next to the .exe once packaged).
APP_DIR = Path(getattr(sys, "frozen", False) and Path(sys.executable).parent
               or Path(__file__).resolve().parent)
CONFIG_PATH = APP_DIR / "sunshift_config.json"

# Where Windows stores the light/dark choice. Two values live under this key:
#   AppsUseLightTheme   — apps (Explorer, Settings, most programs)
#   SystemUsesLightTheme — taskbar, Start menu
# 1 means light, 0 means dark.
PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


# =============================================================================
# Location / config
# =============================================================================
def load_config():
    """Load saved location, or look it up once and save it."""
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    print("First run — looking up your approximate location from your IP...")
    info = requests.get("https://ipinfo.io/json", timeout=10).json()
    lat, lon = (float(x) for x in info["loc"].split(","))
    cfg = {
        "latitude": lat,
        "longitude": lon,
        "city": info.get("city", "unknown"),
        "timezone": info.get("timezone", ""),  # e.g. "America/New_York"
    }
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"Saved location: {cfg['city']} ({lat:.3f}, {lon:.3f}) -> {CONFIG_PATH.name}")
    return cfg


def sun_times(cfg, day=None):
    """Return (sunrise, sunset) as local-time datetimes for the given day."""
    observer = Observer(latitude=cfg["latitude"], longitude=cfg["longitude"])
    # Prefer the named timezone from the config (e.g. "America/New_York") —
    # it knows about daylight saving, so dates in any season come out right.
    # Fall back to the PC's current UTC offset if the config doesn't have one.
    if cfg.get("timezone"):
        local_tz = ZoneInfo(cfg["timezone"])
    else:
        local_tz = datetime.now().astimezone().tzinfo
    day = day or datetime.now().date()
    s = sun(observer, date=day, tzinfo=local_tz)
    return s["sunrise"], s["sunset"]


# =============================================================================
# Theme switching
# =============================================================================
def get_theme():
    """Return 1 if Windows is currently in light mode, 0 if dark."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY) as key:
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    return value


def set_theme(light: bool):
    """Set Windows light/dark mode and notify running apps."""
    value = 1 if light else 0
    if get_theme() == value:
        return False  # already correct — nothing to do

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY, 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, value)
        winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, value)

    # Broadcast WM_SETTINGCHANGE so open apps re-read the theme immediately.
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SETTINGCHANGE, 0, "ImmersiveColorSet",
        SMTO_ABORTIFHUNG, 2000, ctypes.byref(result))
    return True


# =============================================================================
# Main logic
# =============================================================================
def apply_now(cfg):
    """Set the right theme for the current moment. Returns the next switch time."""
    now = datetime.now().astimezone()
    try:
        sunrise, sunset = sun_times(cfg)

        if sunrise <= now < sunset:
            daytime, next_switch = True, sunset
        elif now < sunrise:
            daytime, next_switch = False, sunrise
        else:  # after sunset — next switch is tomorrow's sunrise
            tomorrow_rise, _ = sun_times(cfg, day=now.date() + timedelta(days=1))
            daytime, next_switch = False, tomorrow_rise
    except ValueError:
        # Polar day or polar night: the sun doesn't rise or set at all today
        # (only happens above ~66° latitude). Fall back to "is the sun above
        # the horizon right now?" and check again in a few hours.
        observer = Observer(latitude=cfg["latitude"], longitude=cfg["longitude"])
        daytime = elevation(observer, now) > 0
        next_switch = now + timedelta(hours=6)

    changed = set_theme(light=daytime)
    mode = "light" if daytime else "dark"
    note = "switched to" if changed else "already"
    print(f"[{now:%H:%M}] {note} {mode} mode — next switch at {next_switch:%a %H:%M}")
    return next_switch


def main():
    cfg = load_config()

    if "--status" in sys.argv:
        sunrise, sunset = sun_times(cfg)
        mode = "light" if get_theme() else "dark"
        print(f"Location: {cfg['city']} ({cfg['latitude']:.3f}, {cfg['longitude']:.3f})")
        print(f"Today:    sunrise {sunrise:%H:%M}, sunset {sunset:%H:%M}")
        print(f"Theme:    currently {mode} mode")
        return

    if "--once" in sys.argv:
        apply_now(cfg)
        return

    # Run forever. Sleep until the next sunrise/sunset, but never more than
    # 30 minutes at a stretch — that way we recover gracefully if the PC
    # slept through a transition or the clock changed.
    while True:
        next_switch = apply_now(cfg)
        seconds = (next_switch - datetime.now().astimezone()).total_seconds()
        time.sleep(max(60, min(seconds + 5, 1800)))


if __name__ == "__main__":
    main()
