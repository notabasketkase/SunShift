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
# Options users can toggle in sunshift_config.json. Anything missing from an
# older config file is filled in with these defaults (and saved back) so
# upgrading never breaks.
DEFAULT_OPTIONS = {
    "switch_theme": True,       # flip Windows light/dark mode at sunrise/sunset
    "brightness_ramp": False,   # ease monitor brightness up at dawn, down at dusk
    "day_brightness": 75,       # brightness % during the day
    "night_brightness": 35,     # brightness % at night
    "ramp_minutes": 45,         # how long the dawn/dusk brightness glide takes
}


def load_config():
    """Load saved location, or look it up once and save it."""
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        missing = {k: v for k, v in DEFAULT_OPTIONS.items() if k not in cfg}
        if missing:
            cfg.update(missing)
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return cfg

    print("First run — looking up your approximate location from your IP...")
    info = requests.get("https://ipinfo.io/json", timeout=10).json()
    lat, lon = (float(x) for x in info["loc"].split(","))
    cfg = {
        "latitude": lat,
        "longitude": lon,
        "city": info.get("city", "unknown"),
        "timezone": info.get("timezone", ""),  # e.g. "America/New_York"
        **DEFAULT_OPTIONS,
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
# Brightness ramping
# =============================================================================
def target_brightness(cfg, now, sunrise, sunset):
    """What should the brightness be right now?

    Full day brightness in the middle of the day, full night brightness at
    night, and a smooth linear glide during the ramp window: the first
    `ramp_minutes` after sunrise (easing up) and the last `ramp_minutes`
    before sunset (easing down).
    """
    day, night = cfg["day_brightness"], cfg["night_brightness"]
    ramp = timedelta(minutes=max(1, cfg["ramp_minutes"]))

    if now < sunrise or now >= sunset:
        return night
    if now < sunrise + ramp:                      # dawn: easing up
        fraction = (now - sunrise) / ramp
    elif now >= sunset - ramp:                    # dusk: easing down
        fraction = (sunset - now) / ramp
    else:                                         # broad daylight
        return day
    return round(night + (day - night) * fraction)


def apply_brightness(target):
    """Gently fade all monitors to the target brightness (1% per quarter second).

    Quietly does nothing if the monitors don't support software control.
    """
    try:
        import screen_brightness_control as sbc
        current = sbc.get_brightness()
        if all(abs(b - target) <= 2 for b in current):
            return  # close enough — don't fiddle
        sbc.fade_brightness(target, increment=1, interval=0.25)
        print(f"        brightness {current} -> {target}%")
    except Exception as e:
        print(f"        (brightness control unavailable: {e})")


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
        sunrise = sunset = None  # no ramp possible without sun times

    changed = cfg.get("switch_theme", True) and set_theme(light=daytime)
    mode = "light" if daytime else "dark"
    note = "switched to" if changed else "already"
    print(f"[{now:%H:%M}] {note} {mode} mode — next switch at {next_switch:%a %H:%M}")

    if cfg.get("brightness_ramp"):
        if sunrise is None:  # polar day/night: no ramp, just day or night level
            target = cfg["day_brightness"] if daytime else cfg["night_brightness"]
        else:
            target = target_brightness(cfg, now, sunrise, sunset)
        apply_brightness(target)

    return next_switch


def main():
    cfg = load_config()

    if "--status" in sys.argv:
        sunrise, sunset = sun_times(cfg)
        mode = "light" if get_theme() else "dark"
        print(f"Location: {cfg['city']} ({cfg['latitude']:.3f}, {cfg['longitude']:.3f})")
        print(f"Today:    sunrise {sunrise:%H:%M}, sunset {sunset:%H:%M}")
        print(f"Theme:    currently {mode} mode")
        if cfg.get("brightness_ramp"):
            target = target_brightness(cfg, datetime.now().astimezone(), sunrise, sunset)
            print(f"Ramp:     on — brightness target right now is {target}%")
        else:
            print("Ramp:     off (set \"brightness_ramp\": true in the config to enable)")
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
