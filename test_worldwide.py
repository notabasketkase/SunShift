"""Quick sanity check that the sun math works anywhere on Earth.

Run with:  python test_worldwide.py
Only does calculations and printing — never touches the Windows theme.
"""
from datetime import date, datetime

import sunshift
from sunshift import Observer, elevation

print("--- Sydney, Australia (southern hemisphere: seasons inverted) ---")
sydney = {"latitude": -33.87, "longitude": 151.21, "timezone": "Australia/Sydney"}
for d in [date(2026, 6, 20), date(2026, 12, 21)]:
    sunrise, sunset = sunshift.sun_times(sydney, day=d)
    print(f"{d:%b %d}:  sunrise {sunrise:%H:%M}  sunset {sunset:%H:%M}")

print()
print("--- Tromso, Norway (69.6N — midnight sun this time of year) ---")
tromso = {"latitude": 69.65, "longitude": 18.96, "timezone": "Europe/Oslo"}
try:
    sunshift.sun_times(tromso)
    print("got normal sunrise/sunset (not polar season today)")
except ValueError as e:
    print(f"astral says: {e}")
    observer = Observer(latitude=69.65, longitude=18.96)
    el = elevation(observer, datetime.now().astimezone())
    mode = "light" if el > 0 else "dark"
    print(f"fallback kicks in: sun elevation now = {el:.1f} degrees -> {mode} mode")
