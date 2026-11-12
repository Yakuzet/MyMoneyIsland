# Island Tracker

A small floating "island" for Windows that sits at the top of your screen and tracks how long you've worked and how much you've earned, live.

Set your hourly wage, hit start, and watch your session earnings tick up. Everything is saved locally, and you can see your history by day, week or month.

> The app's interface is in Turkish.

<!-- Add a screenshot: save it as docs/screenshot.png and uncomment the line below -->
<!-- ![Island Tracker](docs/screenshot.png) -->

## Features

- **Live earnings island**: a compact, always-on-top bar showing your current session's earnings (and optionally its duration)
- **Start / pause / finish**: from the island itself or from the system tray menu
- **Smart pausing**: if the computer sleeps or locks, that gap isn't counted
- **Add time manually**: log work you did while the app was closed, as a total duration or a start–end time range
- **History**: view, edit and delete entries, with totals for today, this week, this month and all time
- **Multiple currencies**: TRY, USD, EUR and GBP, with an optional second currency shown alongside
- **Live exchange rates**: fetched hourly from the free [Frankfurter API](https://frankfurter.dev) (no API key needed)
- **Dark theme** with a native dark title bar
- **Local data only**: everything is stored in a JSON file on your computer, with automatic backups if it ever gets corrupted

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

Your data lives in your user config folder (on Windows, usually `%LOCALAPPDATA%\IslandTracker\`):

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
