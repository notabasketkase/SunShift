# SunShift 🌗

A tiny Windows utility that automatically switches between **light mode during
the day** and **dark mode at night** — following the *real* sunrise and sunset
for wherever you are, all year round.

No accounts, no settings screens, no background bloat. It wakes up every 15
minutes, asks "is the sun up?", sets your Windows theme to match, and goes
back to sleep.

## Features

- ☀️ **Real sun times** — computed from your latitude/longitude, so switch
  times drift naturally with the seasons (in Maine that's a 4:49 AM sunrise in
  June and a 3:56 PM sunset in December)
- 📍 **Zero setup** — your approximate location is detected once on first run
  and saved locally; edit `sunshift_config.json` by hand any time
- 🌍 **Works anywhere on Earth** — southern hemisphere, the tropics, even
  above the Arctic Circle (during midnight sun / polar night it falls back to
  checking the sun's actual elevation)
- 🔒 **Private** — after the one-time location lookup, everything runs
  offline. Your location never leaves your machine.
- 🪶 **Light touch** — it only flips the standard Windows light/dark setting
  (the same one in Settings → Personalization → Colors). Nothing else is
  touched, and you can override it manually any time.

## Install

1. Download `SunShift.exe` from the latest release
2. Put it somewhere permanent (e.g. `C:\Tools\SunShift\`)
3. Run it once — it detects your location and sets the right theme:
   ```
   SunShift.exe --once
   ```
4. Make Windows run it automatically every 15 minutes:
   ```
   schtasks /Create /TN "SunShift" /SC MINUTE /MO 15 /TR "\"C:\Tools\SunShift\SunShift.exe\" --once"
   ```

To pause it: `schtasks /Change /TN "SunShift" /DISABLE` (or `/ENABLE` to resume).
To remove it: `schtasks /Delete /TN "SunShift" /F` — then delete the folder. That's everything.

## Usage

```
SunShift.exe --status    show your location, today's sun times, current theme
SunShift.exe --once      set the correct theme for right now, then exit
SunShift.exe             run continuously, switching at each sunrise/sunset
```

## Running from source

```
pip install astral requests
python sunshift.py --status
```

`python test_worldwide.py` runs a quick sanity check of the sun math against
Sydney and Tromsø, Norway.

## How it works

Windows stores the light/dark choice as two registry values under
`HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize`. SunShift
sets them to match the sun, then broadcasts a settings-change message so open
apps update immediately. Sunrise/sunset come from the
[astral](https://github.com/sffjunkie/astral) library — pure astronomy, no
internet required after first run.
