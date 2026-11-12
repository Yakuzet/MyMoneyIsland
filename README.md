# Island Tracker

A small floating "island" for Windows that sits at the top of your screen and tracks how long you've worked and how much you've earned, live.

Set your hourly wage, hit start, and watch your session earnings tick up. Everything is saved locally, and you can see your history by day, week or month.

## Features

- Always-on-top bar showing the current session's earnings, and optionally the elapsed time
- Start, pause and finish from the island or the tray menu
- Time the computer spends asleep or locked isn't counted
- Add time by hand for work you did while the app was closed, as a duration or a start/end time
- History with edit and delete, plus totals for today, this week, this month and all time
- 13 currencies (USD, EUR, GBP, TRY, CHF, JPY, CAD, AUD, CNY, INR, BRL, MXN, KRW), with an optional second one shown on hover
- Exchange rates refreshed hourly from [Frankfurter](https://frankfurter.dev), no API key needed
- Dark theme with a native dark title bar
- Everything is stored in a local JSON file, which gets backed up if it's ever unreadable

## Download

Grab the latest `IslandTracker.exe` from the [Releases](../../releases) page. No installation or Python needed: just run it.

## Run from source

Requires **Python 3.10+** on Windows.

```bash
pip install PyQt6
python app.py
```

## Build the .exe yourself

```bash
python build.py
```

This creates an isolated build environment (`.build-venv`), generates the app icon, and packages everything into a single file at `dist/IslandTracker.exe` using PyInstaller. It must be run on Windows.

## Where is my data stored?

Your data lives in your user config folder (on Windows, inside `%LOCALAPPDATA%\IslandTracker\`):

| File | Purpose |
|------|---------|
| `state.json` | Your wage, settings and all time entries |
| `app.log` | Error log, helpful for troubleshooting |

Delete that folder to fully reset the app.

## Tech stack

- [PyQt6](https://pypi.org/project/PyQt6/) for the UI
- [PyInstaller](https://pyinstaller.org/) for packaging
- [Frankfurter](https://frankfurter.dev) for exchange rates

## License

[MIT](LICENSE)
