from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import sys
import threading
import time
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from PyQt6.QtCore import (
    QDate,
    QEasingCurve,
    QLocale,
    QLockFile,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QStandardPaths,
    Qt,
    QTime,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "IslandTracker"
STATE_VERSION = 2

CURRENCY_NAMES = {
    "USD": "US dollar",
    "EUR": "Euro",
    "GBP": "British pound",
    "TRY": "Turkish lira",
    "CHF": "Swiss franc",
    "JPY": "Japanese yen",
    "CAD": "Canadian dollar",
    "AUD": "Australian dollar",
    "CNY": "Chinese yuan",
    "INR": "Indian rupee",
    "BRL": "Brazilian real",
    "MXN": "Mexican peso",
    "KRW": "South Korean won",
}
SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "TRY": "₺",
    "CHF": "CHF ",
    "JPY": "¥",
    "CAD": "C$",
    "AUD": "A$",
    "CNY": "CN¥",
    "INR": "₹",
    "BRL": "R$",
    "MXN": "MX$",
    "KRW": "₩",
}
CURRENCIES = tuple(CURRENCY_NAMES)
FOREIGN = tuple(c for c in CURRENCIES if c != "USD")

ZERO = Decimal("0")
HOUR = Decimal("3600")
DAY_SECONDS = 24 * 3600

INTERRUPTION_SECONDS = 30

RATE_URL = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=" + ",".join(FOREIGN)
RATE_REFRESH_MS = 60 * 60 * 1000
RATE_RETRY_MS = 2 * 60 * 1000

KIND_LABELS = {"timer": "Timer", "manual": "Manual", "legacy": "Legacy"}

BG = "#16161a"
SURFACE = "#1e1e24"
SURFACE_HI = "#26262d"
BORDER = "#2c2c34"
TEXT = "#ececf1"
MUTED = "#8a8c96"
FAINT = "#5f616b"
ACCENT = "#5ed6a0"
ACCENT_HI = "#7fe3b6"
ACCENT_TEXT = "#0e1a14"
DANGER = "#f07178"


def D(value, default=ZERO):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
    if not result.is_finite() or result < 0:
        return default
    return result


def fmt_number(value, places=2):
    quant = Decimal(1).scaleb(-places)
    return f"{D(value).quantize(quant, ROUND_HALF_UP):,.{places}f}"


def fmt_money(amount, currency):
    return f"{SYMBOLS[currency]}{fmt_number(amount)}"


def fmt_clock(seconds):
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def fmt_span(seconds):
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    return f"{minutes} min"


def today_iso():
    return date.today().isoformat()


def parse_iso_date(text):
    try:
        return date.fromisoformat(str(text))
    except ValueError:
        return None


def new_id():
    return uuid.uuid4().hex


def dark_titlebar(widget):
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attribute in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
    except Exception:
        pass


def make_icon_image(size=256):
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    s = size / 256
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#3a3a45"), 5 * s))
    p.setBrush(QColor("#141418"))
    p.drawRoundedRect(QRectF(12 * s, 52 * s, 232 * s, 152 * s), 76 * s, 76 * s)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ACCENT))
    p.drawEllipse(QRectF(43 * s, 94 * s, 68 * s, 68 * s))
    p.setBrush(QColor(ACCENT_TEXT))
    p.drawPolygon(QPolygonF([
        QPointF(68 * s, 111 * s), QPointF(68 * s, 145 * s), QPointF(93 * s, 128 * s),
    ]))
    p.setBrush(QColor("#f3f3f8"))
    p.drawRoundedRect(QRectF(132 * s, 106 * s, 80 * s, 15 * s), 7 * s, 7 * s)
    p.setBrush(QColor("#8b90a0"))
    p.drawRoundedRect(QRectF(132 * s, 139 * s, 57 * s, 12 * s), 6 * s, 6 * s)
    p.end()
    return image


def save_icon(path):
    if not make_icon_image(256).save(str(path), "ICO"):
        raise SystemExit(f"Could not save icon: {path}")


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "state.json"
        self.data = self.defaults()

        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Invalid state file.")
            if raw.get("version") == STATE_VERSION:
                self.data = self.normalize(raw)
            else:
                self.backup("state-v1-backup.json")
                self.data = self.migrate_v1(raw)
                self.save()
        except Exception:
            logging.exception("Could not read the state file, starting with defaults.")
            self.backup(f"state-corrupt-{time.time_ns()}.json", move=True)

    def backup(self, name, move=False):
        try:
            target = self.directory / name
            if move:
                self.path.replace(target)
            elif not target.exists():
                target.write_bytes(self.path.read_bytes())
        except OSError:
            logging.exception("Backup failed.")

    @staticmethod
    def defaults():
        return {
            "version": STATE_VERSION,
            "wage": "0",
            "currency": "USD",
            "alternate": "EUR",
            "rates": {"USD": "1", **dict.fromkeys(FOREIGN)},
            "fx_date": None,
            "fx_fetched_at": None,
            "show_clock": False,
            "position": None,
            "session_seconds": "0",
            "session_amount": "0",
            "current_entry": None,
            "entries": [],
        }

    @staticmethod
    def clean_rates(raw):
        rates = {"USD": "1"}
        raw = raw if isinstance(raw, dict) else {}
        for currency in CURRENCIES:
            if currency == "USD":
                continue
            value = D(raw.get(currency)) if raw.get(currency) is not None else ZERO
            rates[currency] = str(value) if value > 0 else None
        return rates

    @staticmethod
    def clean_entry(raw):
        if not isinstance(raw, dict):
            return None
        day = parse_iso_date(raw.get("date"))
        kind = raw.get("kind")
        if day is None or kind not in KIND_LABELS:
            return None
        entry = {
            "id": str(raw.get("id") or new_id()),
            "date": day.isoformat(),
            "seconds": str(D(raw.get("seconds"))),
            "amount": str(D(raw.get("amount"))),
            "kind": kind,
            "note": str(raw.get("note") or "")[:200],
        }
        if raw.get("rate") is not None:
            entry["rate"] = str(D(raw.get("rate")))
        return entry

    @classmethod
    def normalize(cls, raw):
        data = cls.defaults()
        data["rates"] = cls.clean_rates(raw.get("rates"))
        if raw.get("currency") in CURRENCIES:
            data["currency"] = raw["currency"]
        alt = raw.get("alternate")
        data["alternate"] = alt if alt in CURRENCIES else None
        data["wage"] = str(D(raw.get("wage")))
        data["show_clock"] = bool(raw.get("show_clock", False))
        data["fx_date"] = raw.get("fx_date") if isinstance(raw.get("fx_date"), str) else None
        data["fx_fetched_at"] = (
            raw.get("fx_fetched_at") if isinstance(raw.get("fx_fetched_at"), str) else None
        )
        pos = raw.get("position")
        if isinstance(pos, list) and len(pos) == 2 and all(isinstance(v, int) for v in pos):
            data["position"] = pos
        data["session_seconds"] = str(D(raw.get("session_seconds")))
        data["session_amount"] = str(D(raw.get("session_amount")))
        entries = raw.get("entries") if isinstance(raw.get("entries"), list) else []
        data["entries"] = [e for e in map(cls.clean_entry, entries) if e]
        current = raw.get("current_entry")
        if any(e["id"] == current and e["kind"] == "timer" for e in data["entries"]):
            data["current_entry"] = current
        return data

    @classmethod
    def migrate_v1(cls, raw):
        data = cls.defaults()
        rates = cls.clean_rates(raw.get("rates"))
        data["rates"] = rates

        currency = raw.get("currency")
        if currency not in CURRENCIES or rates.get(currency) is None:
            currency = "USD"
        factor = D(rates[currency], Decimal(1))

        data["currency"] = currency
        alt = raw.get("alternate")
        data["alternate"] = alt if alt in CURRENCIES and alt != currency else None
        data["wage"] = str(D(raw.get("hourly_usd")) * factor)
        data["show_clock"] = bool(raw.get("show_clock", False))
        pos = raw.get("position")
        if isinstance(pos, list) and len(pos) == 2 and all(isinstance(v, int) for v in pos):
            data["position"] = pos
        data["session_seconds"] = str(D(raw.get("session_seconds")))
        data["session_amount"] = str(D(raw.get("session_usd")) * factor)

        fx_dates = raw.get("fx_dates")
        if isinstance(fx_dates, dict) and fx_dates:
            data["fx_date"] = max(str(v) for v in fx_dates.values())
        if isinstance(raw.get("fx_fetched_at"), str):
            data["fx_fetched_at"] = raw["fx_fetched_at"]

        total_seconds = D(raw.get("total_seconds"))
        if total_seconds > 0:
            data["entries"].append({
                "id": new_id(),
                "date": today_iso(),
                "seconds": str(total_seconds),
                "amount": str(D(raw.get("total_usd")) * factor),
                "kind": "legacy",
                "note": "Imported from previous version",
            })
        return data

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(self.data, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass


class Tracker:
    def __init__(self, store: Store):
        self.store = store
        self.running = False
        self.last = time.monotonic()

    @property
    def data(self):
        return self.store.data

    def current_entry(self, create=False):
        wanted = self.data.get("current_entry")
        if wanted:
            for entry in self.data["entries"]:
                if entry["id"] == wanted:
                    return entry
        if not create:
            return None
        entry = {
            "id": new_id(), "date": today_iso(), "seconds": "0", "amount": "0",
            "kind": "timer", "note": "",
        }
        self.data["entries"].append(entry)
        self.data["current_entry"] = entry["id"]
        return entry

    def has_work(self):
        return self.running or D(self.data["session_seconds"]) > 0

    def accrue(self):
        now = time.monotonic()
        elapsed = now - self.last
        self.last = now
        if not self.running:
            return False
        if elapsed < 0 or elapsed > INTERRUPTION_SECONDS:
            self.running = False
            return True

        seconds = Decimal(str(round(elapsed, 6)))
        earned = seconds * D(self.data["wage"]) / HOUR

        self.data["session_seconds"] = str(D(self.data["session_seconds"]) + seconds)
        self.data["session_amount"] = str(
            (D(self.data["session_amount"]) + earned).quantize(Decimal("1e-10"))
        )
        entry = self.current_entry(create=True)
        entry["seconds"] = str(D(entry["seconds"]) + seconds)
        entry["amount"] = str((D(entry["amount"]) + earned).quantize(Decimal("1e-10")))
        return False

    def toggle(self):
        self.accrue()
        self.running = not self.running
        self.last = time.monotonic()

    def finish(self):
        self.accrue()
        seconds = D(self.data["session_seconds"])
        self.running = False
        self.data["current_entry"] = None
        self.data["session_seconds"] = "0"
        self.data["session_amount"] = "0"
        return seconds


def summarize(entries, start=None, end=None):
    seconds = ZERO
    amount = ZERO
    for entry in entries:
        day = parse_iso_date(entry["date"])
        if day is None:
            continue
        if start and day < start:
            continue
        if end and day > end:
            continue
        seconds += D(entry["seconds"])
        amount += D(entry["amount"])
    return seconds, amount


class Bridge(QObject):
    rates_ready = pyqtSignal(object)
    rates_failed = pyqtSignal(str)


class RateService:
    def __init__(self, bridge: Bridge):
        self.bridge = bridge
        self.lock = threading.Lock()

    def refresh(self):
        if not self.lock.acquire(blocking=False):
            return

        def worker():
            try:
                request = urllib.request.Request(
                    RATE_URL,
                    headers={"User-Agent": "IslandTracker/3.0", "Accept": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=12) as response:
                    body = response.read(200_001)
                if len(body) > 200_000:
                    raise ValueError("Response too large.")
                payload = json.loads(body.decode("utf-8"))
                if payload.get("base") != "USD":
                    raise ValueError("Unexpected rate response.")
                raw = payload.get("rates") or {}
                rates = {"USD": "1"}
                for currency in FOREIGN:
                    value = D(raw.get(currency))
                    if value <= 0:
                        raise ValueError(f"Missing rate for {currency}.")
                    rates[currency] = str(value)
                fx_date = str(payload.get("date"))
                if parse_iso_date(fx_date) is None:
                    raise ValueError("Missing rate date.")
                self.bridge.rates_ready.emit({
                    "rates": rates,
                    "date": fx_date,
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                })
            except Exception as exc:
                logging.warning("Rate update failed: %s", exc)
                self.bridge.rates_failed.emit(str(exc))
            finally:
                self.lock.release()

        threading.Thread(target=worker, name="IslandRates", daemon=True).start()


STYLE = f"""
* {{ font-family: "Segoe UI"; font-size: 10pt; }}
QDialog {{ background: {BG}; color: {TEXT}; }}
QLabel {{ color: {TEXT}; background: transparent; }}
QLabel#title {{ font-size: 14pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#small {{ color: {MUTED}; font-size: 9pt; }}
QLabel#preview {{
    color: {TEXT}; background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 10px 12px;
}}
QLabel#cardValue {{ font-size: 13pt; font-weight: 600; }}
QLabel#cardSub {{ color: {MUTED}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}

QLineEdit, QAbstractSpinBox, QComboBox {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 6px 10px; min-height: 20px;
    selection-background-color: {ACCENT}; selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    background: transparent; border: none; width: 28px;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: url(ARROW_PATH); width: 10px; height: 10px;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
    selection-background-color: {SURFACE_HI}; selection-color: {TEXT}; outline: 0;
}}

QPushButton {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 7px 16px;
}}
QPushButton:hover {{ background: {SURFACE_HI}; }}
QPushButton:disabled {{ color: {FAINT}; }}
QPushButton#primary {{
    background: {ACCENT}; color: {ACCENT_TEXT}; border: none; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_HI}; }}
QPushButton#danger {{ color: {DANGER}; }}
QPushButton#danger:disabled {{ color: {FAINT}; }}

QRadioButton, QCheckBox {{ color: {TEXT}; spacing: 8px; }}

QTableWidget {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 12px; outline: 0;
}}
QTableWidget::item {{ padding: 4px 8px; border: none; }}
QTableWidget::item:selected {{ background: #253029; color: {TEXT}; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: transparent; color: {MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 8px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{
    background: #1b1b20; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 10px; padding: 6px;
}}
QMenu::item {{ padding: 7px 28px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_HI}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QToolTip {{
    background: {SURFACE_HI}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px;
}}
QMessageBox {{ background: {BG}; }}
QCalendarWidget QWidget {{ alternate-background-color: {SURFACE}; }}
QCalendarWidget QToolButton {{ color: {TEXT}; background: transparent; padding: 4px; }}
QCalendarWidget #qt_calendar_navigationbar {{ background: {SURFACE_HI}; }}
"""


def app_stylesheet(directory: Path):
    arrow = directory / "arrow.png"
    try:
        size = 30
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(MUTED), 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(7, 11), QPointF(15, 19), QPointF(23, 11)]))
        p.end()
        image.save(str(arrow), "PNG")
    except Exception:
        logging.exception("Could not create the arrow image.")
    return STYLE.replace("ARROW_PATH", arrow.as_posix())


def dark_palette():
    palette = QPalette()
    roles = QPalette.ColorRole
    for role, color in (
        (roles.Window, BG), (roles.WindowText, TEXT), (roles.Base, SURFACE),
        (roles.AlternateBase, SURFACE_HI), (roles.Text, TEXT), (roles.Button, SURFACE),
        (roles.ButtonText, TEXT), (roles.Highlight, ACCENT),
        (roles.HighlightedText, ACCENT_TEXT), (roles.ToolTipBase, SURFACE_HI),
        (roles.ToolTipText, TEXT), (roles.PlaceholderText, FAINT), (roles.Link, ACCENT),
    ):
        palette.setColor(role, QColor(color))
    for role in (roles.Text, roles.WindowText, roles.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(FAINT))
    return palette


class Dialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

    def showEvent(self, event):
        dark_titlebar(self)
        super().showEvent(event)


def ask(parent, title, text, ok_text="OK", cancel_text=None, destructive=False):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.NoIcon)
    ok = box.addButton(ok_text, QMessageBox.ButtonRole.AcceptRole)
    ok.setObjectName("danger" if destructive else "primary")
    if cancel_text:
        box.addButton(cancel_text, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(ok)
    dark_titlebar(box)
    box.exec()
    return box.clickedButton() is ok


def no_buttons(spin):
    spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    editor = spin.findChild(QLineEdit)
    if editor is not None:
        editor.setTextMargins(4, 0, 0, 0)
    return spin


def header(layout, title, subtitle=None):
    label = QLabel(title)
    label.setObjectName("title")
    layout.addWidget(label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        layout.addWidget(sub)


def button_row(layout, *buttons, stretch_first=True):
    row = QHBoxLayout()
    row.setSpacing(8)
    if stretch_first:
        row.addStretch(1)
    for button in buttons:
        if button is None:
            row.addStretch(1)
        else:
            row.addWidget(button)
    layout.addLayout(row)
    return row


def wage_spin(currency, value):
    spin = no_buttons(QDoubleSpinBox())
    spin.setRange(0, 1_000_000)
    spin.setDecimals(2)
    spin.setValue(float(value))
    spin.setSuffix(f" {SYMBOLS[currency].strip()}/h")
    return spin


def spin_decimal(spin):
    return Decimal(str(round(spin.value(), 2)))


class AddTimeDialog(Dialog):
    def __init__(self, island, parent, entry=None):
        super().__init__(parent, "Edit entry" if entry else "Add time")
        self.island = island
        self.entry = entry
        self.result_entry = None
        self.currency = island.data["currency"]
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        header(
            layout,
            "Edit entry" if entry else "Add time",
            "Log time you worked while the app was closed.",
        )

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(form)

        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setMaximumDate(QDate.currentDate())
        self.date.setDisplayFormat("d MMMM yyyy, dddd")
        form.addRow("Date", self.date)

        self.by_duration = QRadioButton("Duration")
        self.by_range = QRadioButton("Time range")
        self.by_duration.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.by_duration)
        group.addButton(self.by_range)
        modes = QHBoxLayout()
        modes.setSpacing(18)
        modes.addWidget(self.by_duration)
        modes.addWidget(self.by_range)
        modes.addStretch(1)
        form.addRow("Mode", modes)

        self.stack = QStackedWidget()
        duration_page = QWidget()
        row = QHBoxLayout(duration_page)
        row.setContentsMargins(0, 0, 0, 0)
        self.hours = no_buttons(QSpinBox())
        self.hours.setRange(0, 24)
        self.hours.setSuffix(" h")
        self.minutes = no_buttons(QSpinBox())
        self.minutes.setRange(0, 59)
        self.minutes.setSuffix(" min")
        row.addWidget(self.hours)
        row.addWidget(self.minutes)
        self.stack.addWidget(duration_page)

        range_page = QWidget()
        row = QHBoxLayout(range_page)
        row.setContentsMargins(0, 0, 0, 0)
        self.start = QTimeEdit(QTime(9, 0))
        self.end = QTimeEdit(QTime(17, 0))
        for widget in (self.start, self.end):
            widget.setDisplayFormat("HH:mm")
            no_buttons(widget)
        dash = QLabel("–")
        dash.setObjectName("muted")
        row.addWidget(self.start)
        row.addWidget(dash)
        row.addWidget(self.end)
        self.stack.addWidget(range_page)
        form.addRow("Time", self.stack)

        self.wage = wage_spin(self.currency, D(island.data["wage"]))
        form.addRow("Hourly wage", self.wage)

        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional")
        self.note.setMaxLength(200)
        form.addRow("Note", self.note)

        self.preview = QLabel()
        self.preview.setObjectName("preview")
        layout.addWidget(self.preview)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save" if entry else "Add")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self.accept_entry)
        button_row(layout, cancel, save)

        if entry:
            self.prefill(entry)
        else:
            self.hours.setValue(1)

        self.by_duration.toggled.connect(self.switch_mode)
        for signal in (
            self.hours.valueChanged, self.minutes.valueChanged,
            self.start.timeChanged, self.end.timeChanged, self.wage.valueChanged,
        ):
            signal.connect(self.update_preview)
        self.switch_mode()
        QTimer.singleShot(0, lambda: (self.hours.setFocus(), self.hours.selectAll()))

    def prefill(self, entry):
        self.date.setDate(QDate.fromString(entry["date"], Qt.DateFormat.ISODate))
        seconds = int(D(entry["seconds"]))
        minutes = round(seconds / 60)
        self.hours.setValue(min(24, minutes // 60))
        self.minutes.setValue(minutes % 60)
        if entry.get("rate") is not None:
            self.wage.setValue(float(D(entry["rate"])))
        elif seconds:
            self.wage.setValue(float(D(entry["amount"]) * HOUR / Decimal(seconds)))
        self.note.setText(entry.get("note", ""))

    def switch_mode(self):
        self.stack.setCurrentIndex(0 if self.by_duration.isChecked() else 1)
        self.update_preview()

    def seconds(self):
        if self.by_duration.isChecked():
            return self.hours.value() * 3600 + self.minutes.value() * 60
        start = self.start.time().msecsSinceStartOfDay() // 1000
        end = self.end.time().msecsSinceStartOfDay() // 1000
        if end <= start:
            end += DAY_SECONDS
        return end - start

    def amount(self, seconds):
        return Decimal(seconds) * spin_decimal(self.wage) / HOUR

    def update_preview(self):
        seconds = self.seconds()
        if seconds <= 0:
            self.preview.setText("Enter a duration.")
            return
        extra = ""
        if self.by_range.isChecked() and (
            self.end.time().msecsSinceStartOfDay() <= self.start.time().msecsSinceStartOfDay()
        ):
            extra = "  (ends next day)"
        self.preview.setText(
            f"{fmt_span(seconds)}  ·  {fmt_money(self.amount(seconds), self.currency)}{extra}"
        )

    def accept_entry(self):
        seconds = self.seconds()
        if seconds <= 0:
            ask(self, "Add time", "Duration must be greater than zero.")
            return
        if seconds > DAY_SECONDS:
            ask(self, "Add time", "A single entry can't be longer than 24 hours.")
            return
        self.result_entry = {
            "id": self.entry["id"] if self.entry else new_id(),
            "date": self.date.date().toString(Qt.DateFormat.ISODate),
            "seconds": str(seconds),
            "amount": str(self.amount(seconds).quantize(Decimal("1e-6"))),
            "kind": "manual",
            "note": self.note.text().strip()[:200],
            "rate": str(spin_decimal(self.wage)),
        }
        self.accept()


class SettingsDialog(Dialog):
    def __init__(self, island):
        super().__init__(island, "Settings")
        self.island = island
        self.values = None
        data = island.data
        self.previous_currency = data["currency"]
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        header(layout, "Settings")

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        layout.addLayout(form)

        self.currency = QComboBox()
        for code in CURRENCIES:
            self.currency.addItem(f"{code} · {CURRENCY_NAMES[code]}", code)
        self.currency.setCurrentIndex(CURRENCIES.index(data["currency"]))

        self.wage = wage_spin(data["currency"], D(data["wage"]))

        self.alternate = QComboBox()
        self.alternate.addItem("None", None)
        for code in CURRENCIES:
            self.alternate.addItem(f"{code} · {CURRENCY_NAMES[code]}", code)
        alt = data["alternate"]
        self.alternate.setCurrentIndex(0 if alt is None else CURRENCIES.index(alt) + 1)

        self.clock = QCheckBox("Show elapsed time under earnings")
        self.clock.setChecked(data["show_clock"])

        form.addRow("Hourly wage", self.wage)
        form.addRow("Currency", self.currency)
        form.addRow("Second currency", self.alternate)
        form.addRow("", self.clock)

        hint = QLabel("Hover over the island for a moment to see the second currency.")
        hint.setObjectName("small")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        rates_card = QFrame()
        rates_card.setObjectName("card")
        card = QVBoxLayout(rates_card)
        card.setContentsMargins(14, 12, 14, 12)
        card.setSpacing(6)
        title = QLabel("Exchange rates")
        title.setStyleSheet("font-weight: 600;")
        self.rate_text = QLabel()
        self.rate_text.setObjectName("muted")
        self.rate_text.setWordWrap(True)
        refresh = QPushButton("Refresh rates")
        refresh.clicked.connect(island.rates.refresh)
        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(refresh)
        card.addLayout(top)
        card.addWidget(self.rate_text)
        layout.addWidget(rates_card)

        quit_button = QPushButton("Quit app")
        quit_button.setObjectName("danger")
        quit_button.clicked.connect(self.quit_app)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self.accept_settings)
        button_row(layout, quit_button, None, cancel, save, stretch_first=False)

        self.currency.currentIndexChanged.connect(self.currency_changed)

        timer = QTimer(self)
        timer.timeout.connect(self.refresh_rates)
        timer.start(1000)
        self.refresh_rates()

    def refresh_rates(self):
        data = self.island.data
        rates = data["rates"]
        parts = [
            f"{fmt_number(rates[c], 4 if D(rates[c]) < 10 else 2)} {c}"
            for c in FOREIGN if rates.get(c)
        ]
        if not parts:
            text = "Not downloaded yet. Check your connection and refresh."
        else:
            text = "1 USD = " + "  ·  ".join(parts)
            if data.get("fx_date"):
                day = QDate.fromString(data["fx_date"], Qt.DateFormat.ISODate)
                text += f"\nECB reference rate, {QLocale().toString(day, 'd MMMM yyyy')}"
        if self.island.rate_error:
            text += "\nLast refresh failed, using saved rates."
        self.rate_text.setText(text)

    def currency_changed(self):
        new = self.currency.currentData()
        converted = self.island.convert(spin_decimal(self.wage), self.previous_currency, new)
        if converted is not None:
            self.wage.setValue(float(converted))
        self.wage.setSuffix(f" {SYMBOLS[new].strip()}/h")
        self.previous_currency = new

    def accept_settings(self):
        data = self.island.data
        currency = self.currency.currentData()
        if currency != data["currency"] and self.island.convert(
            Decimal(1), data["currency"], currency
        ) is None:
            ask(
                self, "Settings",
                f"No exchange rate for {currency} yet. Refresh rates first.\n"
                "Existing entries are converted to the new currency at that rate.",
            )
            return
        alternate = self.alternate.currentData()
        if alternate == currency:
            alternate = None
        self.values = {
            "wage": str(spin_decimal(self.wage)),
            "currency": currency,
            "alternate": alternate,
            "show_clock": self.clock.isChecked(),
        }
        self.accept()

    def quit_app(self):
        self.reject()
        self.island.shutdown()


class HistoryDialog(Dialog):
    COLUMNS = ("Date", "Type", "Duration", "Earned", "Note")

    def __init__(self, island):
        super().__init__(island, "History")
        self.island = island
        self.row_ids = []
        self.resize(700, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        header(layout, "History")

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.cards = {}
        for key, title in (
            ("today", "Today"), ("week", "This week"), ("month", "This month"), ("all", "All time"),
        ):
            frame = QFrame()
            frame.setObjectName("card")
            box = QVBoxLayout(frame)
            box.setContentsMargins(14, 12, 14, 12)
            box.setSpacing(2)
            name = QLabel(title)
            name.setObjectName("small")
            value = QLabel()
            value.setObjectName("cardValue")
            sub = QLabel()
            sub.setObjectName("cardSub")
            box.addWidget(name)
            box.addWidget(value)
            box.addWidget(sub)
            cards.addWidget(frame, 1)
            self.cards[key] = (value, sub)
        layout.addLayout(cards)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(36)
        head = self.table.horizontalHeader()
        head.setHighlightSections(False)
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column, mode in enumerate((
            QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.Stretch,
        )):
            head.setSectionResizeMode(column, mode)
        self.table.itemSelectionChanged.connect(self.update_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self.edit_selected())
        layout.addWidget(self.table, 1)

        self.empty = QLabel("No entries yet. Start the timer, or use “Add time” to log past work.")
        self.empty.setObjectName("muted")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        add = QPushButton("Add time")
        add.setObjectName("primary")
        add.clicked.connect(self.add)
        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("danger")
        self.delete_button.clicked.connect(self.delete_selected)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        button_row(layout, add, self.edit_button, self.delete_button, None, close,
                   stretch_first=False)

        timer = QTimer(self)
        timer.timeout.connect(self.refresh)
        timer.start(1000)
        self.refresh()

    def ordered(self):
        entries = self.island.data["entries"]
        order = sorted(range(len(entries)), key=lambda i: (entries[i]["date"], i), reverse=True)
        return [entries[i] for i in order]

    def refresh(self):
        self.island.tracker.accrue()
        entries = self.island.data["entries"]
        currency = self.island.data["currency"]
        today = date.today()
        ranges = {
            "today": (today, today),
            "week": (today - timedelta(days=today.weekday()), today),
            "month": (today.replace(day=1), today),
            "all": (None, None),
        }
        for key, (start, end) in ranges.items():
            seconds, amount = summarize(entries, start, end)
            value, sub = self.cards[key]
            value.setText(fmt_span(seconds))
            sub.setText(fmt_money(amount, currency))
        self.refresh_table()

    def refresh_table(self):
        rows = self.ordered()
        ids = [e["id"] for e in rows]
        currency = self.island.data["currency"]
        rebuild = ids != self.row_ids

        if rebuild:
            selected = self.selected_entry()
            self.table.setRowCount(len(rows))
            self.row_ids = ids

        locale = QLocale()
        for row, entry in enumerate(rows):
            day = QDate.fromString(entry["date"], Qt.DateFormat.ISODate)
            values = (
                locale.toString(day, "d MMM yyyy, ddd"),
                KIND_LABELS[entry["kind"]],
                fmt_span(D(entry["seconds"])),
                fmt_money(D(entry["amount"]), currency),
                entry.get("note", ""),
            )
            for column, text in enumerate(values):
                item = self.table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, column, item)
                if item.text() != text:
                    item.setText(text)
                if column == 1:
                    item.setForeground(QColor(ACCENT if entry["kind"] == "manual" else MUTED))

        if rebuild and selected is not None and selected["id"] in ids:
            self.table.selectRow(ids.index(selected["id"]))

        has_rows = bool(rows)
        self.table.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        self.update_buttons()

    def selected_entry(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.row_ids) or not self.table.selectedItems():
            return None
        wanted = self.row_ids[row]
        return next((e for e in self.island.data["entries"] if e["id"] == wanted), None)

    def update_buttons(self):
        entry = self.selected_entry()
        self.edit_button.setEnabled(entry is not None and entry["kind"] == "manual")
        self.delete_button.setEnabled(entry is not None)

    def add(self):
        self.island.open_add(parent=self)
        self.refresh()

    def edit_selected(self):
        entry = self.selected_entry()
        if entry is None:
            return
        if entry["kind"] != "manual":
            ask(self, "Edit", "Only manually added entries can be edited.")
            return
        self.island.open_add(entry=entry, parent=self)
        self.refresh()

    def delete_selected(self):
        entry = self.selected_entry()
        if entry is None:
            return
        day = QLocale().toString(QDate.fromString(entry["date"], Qt.DateFormat.ISODate), "d MMMM yyyy")
        text = (
            f"Delete the {KIND_LABELS[entry['kind']].lower()} entry from {day} "
            f"({fmt_span(D(entry['seconds']))})?\nThis can't be undone."
        )
        if not ask(self, "Delete entry", text, "Delete", "Cancel", destructive=True):
            return
        self.island.tracker.accrue()
        self.island.data["entries"] = [
            e for e in self.island.data["entries"] if e["id"] != entry["id"]
        ]
        self.island.save()
        self.refresh()


class HoverBar(QWidget):
    HEIGHT = 26

    def __init__(self, owner):
        super().__init__(
            owner,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.parts = []
        self.wanted = False
        self.font_ = QFont("Segoe UI", 9)
        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade.setDuration(170)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade.finished.connect(self._fade_done)
        self.setFixedSize(60, self.HEIGHT)

    def set_parts(self, parts):
        if parts == self.parts:
            return
        self.parts = parts
        metrics = QFontMetrics(self.font_)
        width = sum(metrics.horizontalAdvance(t) for t, _ in parts) + 22
        if width != self.width():
            self.setFixedSize(width, self.HEIGHT)
        self.update()

    def reveal(self):
        self.wanted = True
        self.fade.stop()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
        self.fade.setStartValue(self.windowOpacity())
        self.fade.setEndValue(1.0)
        self.fade.start()

    def dismiss(self, immediate=False):
        self.wanted = False
        self.fade.stop()
        if immediate or not self.isVisible():
            self.hide()
            return
        self.fade.setStartValue(self.windowOpacity())
        self.fade.setEndValue(0.0)
        self.fade.start()

    def _fade_done(self):
        if not self.wanted:
            self.hide()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(BORDER), 1))
        p.setBrush(QColor(20, 20, 24, 246))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setFont(self.font_)
        metrics = QFontMetrics(self.font_)
        x = 11.0
        for text, color in self.parts:
            p.setPen(QColor(color))
            w = metrics.horizontalAdvance(text)
            p.drawText(QRectF(x, 0, w + 1, self.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            x += w


class ActionBubble(QWidget):
    clicked = pyqtSignal()
    hovered = pyqtSignal(bool)

    def __init__(self, owner, size):
        super().__init__(
            owner,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode = "quit"
        self.hot = False
        self.wanted = False
        self.anchor = QPoint()
        self.slide = 10
        self.t = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(170)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._step)
        self.anim.finished.connect(self._done)

    def set_mode(self, mode):
        if mode != self.mode:
            self.mode = mode
            self.update()
        self.setToolTip(
            "Finish and save" if mode == "finish" else "Quit"
        )

    def set_anchor(self, point, slide):
        self.anchor = point
        self.slide = slide
        self._apply()

    def _apply(self):
        self.move(self.anchor.x() + int(round((1 - self.t) * self.slide)), self.anchor.y())
        self.setWindowOpacity(self.t)

    def _step(self, value):
        self.t = float(value)
        self._apply()

    def _done(self):
        if not self.wanted:
            self.hide()

    def reveal(self):
        if self.wanted and self.isVisible():
            return
        self.wanted = True
        self.anim.stop()
        if not self.isVisible():
            self.t = 0.0
            self._apply()
            self.show()
        self.anim.setStartValue(self.t)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def dismiss(self, immediate=False):
        self.wanted = False
        self.hot = False
        self.anim.stop()
        if immediate or not self.isVisible():
            self.t = 0.0
            self.hide()
            return
        self.anim.setStartValue(self.t)
        self.anim.setEndValue(0.0)
        self.anim.start()

    def enterEvent(self, event):
        self.hot = True
        self.update()
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hot = False
        self.update()
        self.hovered.emit(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(BORDER), 1))
        p.setBrush(QColor(20, 20, 24, 246))
        p.drawEllipse(r)
        c = r.center()
        inner = 14
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#33333b" if self.hot else SURFACE_HI))
        p.drawEllipse(c, inner, inner)
        if self.mode == "finish":
            p.setBrush(QColor(TEXT))
            p.drawRoundedRect(QRectF(c.x() - 5, c.y() - 5, 10, 10), 2, 2)
        else:
            pen = QPen(QColor(DANGER), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(c.x() - 4.5, c.y() - 4.5), QPointF(c.x() + 4.5, c.y() + 4.5))
            p.drawLine(QPointF(c.x() + 4.5, c.y() - 4.5), QPointF(c.x() - 4.5, c.y() + 4.5))


class Island(QWidget):
    HEIGHT = 42

    def __init__(self, store: Store, bridge: Bridge):
        super().__init__()
        self.store = store
        self.bridge = bridge
        self.tracker = Tracker(store)
        self.rates = RateService(bridge)
        self.rate_error = ""
        self.quitting = False
        self.save_error_shown = False

        self.hovered = False
        self.hover_target = None
        self.press = None
        self.dragging = False
        self.text_width = 0
        self.save_phase = None
        self.save_old = ("", None)
        self.save_anim = QVariantAnimation(self)
        self.save_anim.setDuration(1600)
        self.save_anim.setStartValue(0.0)
        self.save_anim.setEndValue(1.0)
        self.save_anim.valueChanged.connect(self._save_step)
        self.save_anim.finished.connect(self._save_done)
        self.mix = 0.0

        self.setWindowTitle("Island Tracker")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        self.fade = QVariantAnimation(self)
        self.fade.setDuration(280)
        self.fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.fade.valueChanged.connect(self._set_mix)

        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(2000)
        self.hover_timer.timeout.connect(self.show_secondary)

        self.total_bar = HoverBar(self)
        self.time_bar = HoverBar(self)
        self.bubble = ActionBubble(self, self.HEIGHT)
        self.bubble.clicked.connect(self.finish_or_quit)
        self.bubble.hovered.connect(self.bubble_hovered)
        self.bubble_side = "left"

        self.leave_timer = QTimer(self)
        self.leave_timer.setSingleShot(True)
        self.leave_timer.setInterval(160)
        self.leave_timer.timeout.connect(self.check_leave)
        self.bubble_timer = QTimer(self)
        self.bubble_timer.setSingleShot(True)
        self.bubble_timer.setInterval(260)
        self.bubble_timer.timeout.connect(self.check_bubble)

        self.menu = self.build_menu()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(250)

        self.save_timer = QTimer(self)
        self.save_timer.timeout.connect(self.save)
        self.save_timer.start(10_000)

        self.rate_timer = QTimer(self)
        self.rate_timer.timeout.connect(self.rates.refresh)
        self.rate_timer.start(RATE_REFRESH_MS)
        self.retry_timer = QTimer(self)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.setInterval(RATE_RETRY_MS)
        self.retry_timer.timeout.connect(self.rates.refresh)

        bridge.rates_ready.connect(self.apply_rates, Qt.ConnectionType.QueuedConnection)
        bridge.rates_failed.connect(self.rates_failed, Qt.ConnectionType.QueuedConnection)

        self.tray = None
        self.relayout()
        self.restore_position()
        QTimer.singleShot(0, self.rates.refresh)

    @property
    def data(self):
        return self.store.data

    def rate(self, currency):
        value = self.data["rates"].get(currency)
        value = D(value) if value is not None else ZERO
        return value if value > 0 else None

    def convert(self, amount, source, target):
        if source == target:
            return amount
        a, b = self.rate(source), self.rate(target)
        if a is None or b is None:
            return None
        return amount / a * b

    def secondary_currency(self):
        alt = self.data["alternate"]
        if alt and alt != self.data["currency"] and self.convert(
            Decimal(1), self.data["currency"], alt
        ) is not None:
            return alt
        return None

    def money(self, amount, currency=None):
        base = self.data["currency"]
        currency = currency or base
        value = self.convert(amount, base, currency)
        return "—" if value is None else fmt_money(value, currency)

    def fonts(self):
        amount = QFont("Segoe UI", 12)
        amount.setWeight(QFont.Weight.DemiBold)
        sub = QFont("Segoe UI", 8)
        return amount, sub

    def relayout(self, reset=False):
        if reset:
            self.text_width = 0
        amount_font, sub_font = self.fonts()
        session = D(self.data["session_amount"])
        texts = [self.money(session)]
        alt = self.secondary_currency()
        if alt:
            texts.append(self.money(session, alt))
        need = max(QFontMetrics(amount_font).horizontalAdvance(t) for t in texts)
        if self.data["show_clock"]:
            need = max(need, QFontMetrics(sub_font).horizontalAdvance(self.session_text()))
        self.text_width = max(self.text_width, need + 2)
        text_width = self.text_width

        h = self.HEIGHT
        x = 42
        right = x + text_width + 8
        self.menu_rect = QRectF(right, (h - 20) / 2, 18, 20)
        width = int(right + 18 + 9)
        self.play_rect = QRectF(7, (h - 28) / 2, 28, 28)
        self.amount_rect = QRectF(x, 4, text_width, 21)
        self.amount_center = QRectF(x, 0, text_width, h)
        self.sub_rect = QRectF(x, 24, text_width, 14)
        if self.width() != width or self.height() != h:
            self.setFixedSize(width, h)
            self.position_bars()

    def session_text(self):
        return fmt_clock(D(self.data["session_seconds"]))

    def subtitle(self):
        if self.data["show_clock"]:
            return self.session_text()
        return None

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        h = self.HEIGHT
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        p.setPen(QPen(QColor(BORDER), 1))
        p.setBrush(QColor(20, 20, 24, 246))
        p.drawRoundedRect(rect, h / 2, h / 2)

        running = self.tracker.running
        hot = self.hover_target == "play"
        p.setPen(Qt.PenStyle.NoPen)
        if running:
            p.setBrush(QColor(ACCENT_HI if hot else ACCENT))
        else:
            p.setBrush(QColor("#33333b" if hot else SURFACE_HI))
        p.drawEllipse(self.play_rect)
        c = self.play_rect.center()
        if running:
            p.setBrush(QColor(ACCENT_TEXT))
            p.drawRoundedRect(QRectF(c.x() - 4.5, c.y() - 5.5, 3.2, 11), 1.2, 1.2)
            p.drawRoundedRect(QRectF(c.x() + 1.3, c.y() - 5.5, 3.2, 11), 1.2, 1.2)
        else:
            p.setBrush(QColor(ACCENT))
            p.drawPolygon(QPolygonF([
                QPointF(c.x() - 3, c.y() - 6),
                QPointF(c.x() - 3, c.y() + 6),
                QPointF(c.x() + 6, c.y()),
            ]))

        amount_font, sub_font = self.fonts()
        session = D(self.data["session_amount"])
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        subtitle = self.subtitle()
        amount_rect = self.amount_rect if subtitle else self.amount_center

        if self.save_phase is not None:
            self.paint_save(p, amount_font, sub_font, subtitle)
        else:
            p.setFont(amount_font)
            p.setPen(QColor(TEXT))
            primary = self.money(session)
            alt = self.secondary_currency()
            mix = self.mix if alt else 0.0
            if mix < 1:
                p.setOpacity(1 - mix)
                p.drawText(amount_rect.translated(0, -6 * mix), align, primary)
            if mix > 0:
                p.setOpacity(mix)
                p.drawText(amount_rect.translated(0, 6 * (1 - mix)), align, self.money(session, alt))
            p.setOpacity(1)

            if subtitle:
                p.setFont(sub_font)
                p.setPen(QColor(ACCENT if running else MUTED))
                p.drawText(self.sub_rect, align, subtitle)

        mc = self.menu_rect.center()
        p.setPen(Qt.PenStyle.NoPen)
        if self.hover_target == "menu":
            p.setBrush(QColor(SURFACE_HI))
            p.drawEllipse(mc, 11, 11)
        p.setBrush(QColor(TEXT if self.hover_target == "menu" else MUTED))
        for dy in (-4.5, 0, 4.5):
            p.drawEllipse(QPointF(mc.x(), mc.y() + dy), 1.5, 1.5)

    def play_save(self):
        self.save_anim.stop()
        self.mix = 0.0
        self.save_phase = 0.0
        self.save_anim.start()

    def _save_step(self, value):
        self.save_phase = float(value)
        self.update()

    def _save_done(self):
        self.save_phase = None
        self.relayout(reset=True)
        self.update()

    @staticmethod
    def _seg(phase, start, end):
        t = min(1.0, max(0.0, (phase - start) / (end - start)))
        return 1 - (1 - t) ** 3

    def paint_save(self, p, amount_font, sub_font, subtitle):
        phase = self.save_phase
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        amount_rect = self.amount_rect if subtitle else self.amount_center
        old_amount, old_sub = self.save_old
        p.setClipRect(QRectF(self.amount_center.left() - 2, 4,
                             self.amount_center.width() + 4, self.HEIGHT - 8))

        def draw_texts(amount, sub, dy, opacity, sub_color):
            if opacity <= 0:
                return
            p.setOpacity(opacity)
            p.setFont(amount_font)
            p.setPen(QColor(TEXT))
            p.drawText(amount_rect.translated(0, dy), align, amount)
            if sub:
                p.setFont(sub_font)
                p.setPen(QColor(sub_color))
                p.drawText(self.sub_rect.translated(0, dy), align, sub)
            p.setOpacity(1)

        out = self._seg(phase, 0.0, 0.18)
        draw_texts(old_amount, old_sub, -16 * out, 1 - out, ACCENT)

        d_in = self._seg(phase, 0.14, 0.34)
        d_out = self._seg(phase, 0.72, 0.88)
        if d_in > 0 and d_out < 1:
            pop = 1 + 0.14 * math.sin(math.pi * self._seg(phase, 0.34, 0.5))
            fill = self._seg(phase, 0.38, 0.68)
            center = QPointF(
                self.amount_center.left() + 10,
                self.HEIGHT / 2 + 16 * (1 - d_in) - 16 * d_out,
            )
            p.setOpacity(d_in * (1 - d_out))
            self.draw_floppy(p, center, 18 * pop, fill)
            p.setOpacity(1)

        new_in = self._seg(phase, 0.82, 1.0)
        draw_texts(
            self.money(D(self.data["session_amount"])), subtitle,
            16 * (1 - new_in), new_in, MUTED,
        )
        p.setClipping(False)

    @staticmethod
    def draw_floppy(p, center, size, fill):
        s = size
        x, y = center.x() - s / 2, center.y() - s / 2
        cut = s * 0.2
        body = QPolygonF([
            QPointF(x, y), QPointF(x + s - cut, y), QPointF(x + s, y + cut),
            QPointF(x + s, y + s), QPointF(x, y + s),
        ])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT))
        p.drawPolygon(body)
        p.setBrush(QColor(ACCENT_TEXT))
        p.drawRect(QRectF(x + s * 0.24, y, s * 0.46, s * 0.3))
        p.setBrush(QColor(ACCENT))
        p.drawRect(QRectF(x + s * 0.52, y + s * 0.05, s * 0.1, s * 0.2))
        label = QRectF(x + s * 0.16, y + s * 0.48, s * 0.68, s * 0.42)
        p.setBrush(QColor("#f3f3f8"))
        p.drawRoundedRect(label, s * 0.04, s * 0.04)
        p.setBrush(QColor(MUTED))
        for i, row in enumerate((0.3, 0.62)):
            progress = min(1.0, max(0.0, fill * 2 - i))
            if progress > 0:
                w = (label.width() - s * 0.16) * progress
                p.drawRect(QRectF(label.left() + s * 0.08, label.top() + label.height() * row - s * 0.03,
                                  w, s * 0.07))

    def _set_mix(self, value):
        self.mix = float(value)
        self.update()

    def animate_mix(self, target):
        self.fade.stop()
        self.fade.setStartValue(self.mix)
        self.fade.setEndValue(float(target))
        self.fade.start()

    def show_secondary(self):
        if self.hovered and self.secondary_currency():
            self.animate_mix(1.0)

    def tick(self):
        if self.tracker.accrue():
            self.save()
        self.relayout()
        if self.hovered:
            self.update_bars()
            self.position_bars()
            if self.bubble.isVisible():
                self.bubble.set_mode("finish" if self.tracker.has_work() else "quit")
        self.update()
        if self.tray is not None and int(time.monotonic()) % 5 == 0:
            self.tray.setToolTip(
                f"Island Tracker: {self.money(D(self.data['session_amount']))}"
                f" · {fmt_clock(D(self.data['session_seconds']))}"
            )

    def toggle_work(self):
        self.tracker.toggle()
        self.update()
        self.save()

    def hit(self, pos):
        point = QPointF(pos)
        if self.play_rect.adjusted(-3, -3, 3, 3).contains(point):
            return "play"
        if self.menu_rect.adjusted(-3, -3, 3, 3).contains(point):
            return "menu"
        return "body"

    def update_bars(self):
        seconds, amount = summarize(self.data["entries"])
        self.total_bar.set_parts([
            ("Total  ", MUTED),
            (fmt_money(amount, self.data["currency"]), TEXT),
            ("  ·  ", FAINT),
            (fmt_clock(seconds), TEXT),
        ])
        self.time_bar.set_parts([
            (self.session_text(), ACCENT if self.tracker.running else TEXT),
        ])

    def position_bars(self):
        if not hasattr(self, "bubble"):
            return
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        gap = 6

        size = self.bubble.width()
        bx = self.x() - size - 4
        self.bubble_side = "left"
        if bx < area.left():
            bx = self.x() + self.width() + 4
            self.bubble_side = "right"
        self.bubble.set_anchor(QPoint(bx, self.y()), 10 if self.bubble_side == "left" else -10)

        bar = self.total_bar
        x = self.x() + (self.width() - bar.width()) // 2
        x = max(area.left(), min(x, area.right() - bar.width() + 1))
        y = self.y() + self.height() + gap
        if y + bar.height() > area.bottom() + 1:
            y = self.y() - bar.height() - gap
        bar.move(x, y)

        bar = self.time_bar
        x = self.x() + self.width() + gap
        if self.bubble_side == "right":
            x += size + 4
        if x + bar.width() > area.right() + 1:
            x = self.x() - bar.width() - gap
            if self.bubble_side == "left":
                x -= size + 4
        bar.move(x, self.y() + (self.height() - bar.height()) // 2)

    def set_hover(self, enabled, immediate=False):
        self.hovered = enabled
        self.leave_timer.stop()
        if enabled:
            self.update_bars()
            self.position_bars()
            self.total_bar.reveal()
            if not self.data["show_clock"]:
                self.time_bar.reveal()
            self.hover_timer.start()
        else:
            self.hover_target = None
            self.hover_timer.stop()
            self.bubble_timer.stop()
            self.animate_mix(0.0)
            self.total_bar.dismiss(immediate)
            self.time_bar.dismiss(immediate)
            self.bubble.dismiss(immediate)
        self.update()

    def cursor_inside(self):
        pos = QCursor.pos()
        return self.frameGeometry().contains(pos) or (
            self.bubble.isVisible() and self.bubble.frameGeometry().contains(pos)
        )

    def check_leave(self):
        if not self.cursor_inside():
            self.set_hover(False)

    def show_bubble(self):
        self.bubble_timer.stop()
        self.bubble.set_mode("finish" if self.tracker.has_work() else "quit")
        self.position_bars()
        self.bubble.reveal()

    def check_bubble(self):
        if not self.bubble.hot and self.hover_target != "play":
            self.bubble.dismiss()

    def bubble_hovered(self, inside):
        if inside:
            self.leave_timer.stop()
            self.bubble_timer.stop()
        else:
            self.bubble_timer.start()
            self.leave_timer.start()

    def finish_or_quit(self):
        if self.tracker.has_work():
            self.finish_work()
        else:
            self.shutdown()

    def enterEvent(self, event):
        self.leave_timer.stop()
        if not self.hovered:
            self.set_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_target = None
        self.update()
        self.bubble_timer.start()
        self.leave_timer.start()
        super().leaveEvent(event)

    def moveEvent(self, event):
        self.position_bars()
        super().moveEvent(event)

    def hideEvent(self, event):
        self.set_hover(False, immediate=True)
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press = (event.globalPosition().toPoint(), self.pos(), self.hit(event.position().toPoint()))
            self.dragging = False
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        target = self.hit(event.position().toPoint())
        if target != self.hover_target:
            self.hover_target = target
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if target in ("play", "menu")
                else Qt.CursorShape.ArrowCursor
            )
            self.update()
        if target == "play" and self.press is None:
            self.show_bubble()
        elif self.bubble.wanted:
            self.bubble_timer.start()
        if self.press is None:
            return
        origin, window_origin, _ = self.press
        delta = event.globalPosition().toPoint() - origin
        if not self.dragging and delta.manhattanLength() >= QApplication.startDragDistance():
            self.dragging = True
        if self.dragging:
            self.move(window_origin + delta)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.press is None:
            return
        _, _, target = self.press
        released_on = self.hit(event.position().toPoint())
        was_dragging = self.dragging
        self.press = None
        self.dragging = False
        if was_dragging:
            self.save()
        elif target == released_on == "play":
            self.toggle_work()
        elif target == released_on == "menu":
            self.show_menu(self.mapToGlobal(self.menu_rect.bottomLeft().toPoint() + QPoint(-8, 8)))

    def mouseDoubleClickEvent(self, event):
        if self.hit(event.position().toPoint()) == "body":
            self.open_history()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.toggle_work()
        elif event.key() == Qt.Key.Key_Q and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.shutdown()
        else:
            super().keyPressEvent(event)

    def build_menu(self):
        menu = QMenu(self)
        menu.setWindowFlags(
            menu.windowFlags() | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.act_toggle = menu.addAction("Start", self.toggle_work)
        menu.addSeparator()
        menu.addAction("Add time…", self.open_add)
        menu.addAction("History…", self.open_history)
        menu.addAction("Settings…", self.open_settings)
        menu.addSeparator()
        self.act_finish = menu.addAction("Finish session", self.finish_work)
        self.act_visibility = menu.addAction("Hide", self.toggle_visibility)
        menu.addSeparator()
        menu.addAction("Quit", self.shutdown)

        def refresh_labels():
            self.act_toggle.setText("Pause" if self.tracker.running else "Start")
            self.act_visibility.setText("Hide" if self.isVisible() else "Show")
            self.act_finish.setEnabled(self.tracker.has_work())

        menu.aboutToShow.connect(refresh_labels)
        return menu

    def show_menu(self, global_pos):
        self.hover_target = None
        self.menu.popup(global_pos)

    def start_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon(QPixmap.fromImage(make_icon_image(64))), self)
        self.tray.setToolTip("Island Tracker")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
            self.save()
        else:
            self.show()
            self.raise_()

    def modal_busy(self):
        self.set_hover(False, immediate=True)
        active = QApplication.activeModalWidget()
        if active is not None:
            active.raise_()
            active.activateWindow()
            return True
        return False

    def open_add(self, entry=None, parent=None):
        if parent is None and self.modal_busy():
            return False
        dialog = AddTimeDialog(self, parent or self, entry)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.tracker.accrue()
        if entry is not None:
            entry.clear()
            entry.update(dialog.result_entry)
        else:
            self.data["entries"].append(dialog.result_entry)
        self.save()
        return True

    def open_history(self):
        if self.modal_busy():
            return
        HistoryDialog(self).exec()

    def open_settings(self):
        if self.modal_busy():
            return
        dialog = SettingsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values
        self.tracker.accrue()
        old = self.data["currency"]
        new = values["currency"]
        if new != old:
            factor = self.convert(Decimal(1), old, new)
            if factor is not None:
                self.data["session_amount"] = str(D(self.data["session_amount"]) * factor)
                for entry in self.data["entries"]:
                    entry["amount"] = str(D(entry["amount"]) * factor)
                    if entry.get("rate") is not None:
                        entry["rate"] = str((D(entry["rate"]) * factor).quantize(Decimal("0.01")))
        self.data.update(values)
        self.mix = 0.0
        self.relayout(reset=True)
        self.update()
        self.save()

    def finish_work(self):
        if not self.tracker.has_work():
            return
        self.tracker.accrue()
        self.save_old = (self.money(D(self.data["session_amount"])), self.subtitle())
        self.tracker.finish()
        self.play_save()
        self.bubble.set_mode("quit")
        self.update_bars()
        self.save()

    def apply_rates(self, payload):
        if self.quitting:
            return
        self.tracker.accrue()
        self.data["rates"] = payload["rates"]
        self.data["fx_date"] = payload["date"]
        self.data["fx_fetched_at"] = payload["fetched_at"]
        self.rate_error = ""
        self.retry_timer.stop()
        self.relayout()
        self.save()

    def rates_failed(self, message):
        if self.quitting:
            return
        self.rate_error = message
        self.retry_timer.start()

    def restore_position(self):
        saved = self.data.get("position")
        primary = QApplication.primaryScreen().availableGeometry()
        position = QPoint(*saved) if saved else QPoint(
            primary.center().x() - self.width() // 2, primary.top() + 16
        )
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = max(area.left(), min(position.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(position.y(), area.bottom() - self.height() + 1))
        self.move(x, y)

    def save(self):
        self.tracker.accrue()
        self.data["position"] = [self.x(), self.y()]
        try:
            self.store.save()
            self.save_error_shown = False
        except OSError:
            logging.exception("Could not save state.")
            if not self.save_error_shown:
                self.save_error_shown = True
                ask(
                    self, "Save failed",
                    "The timer is still running but your data couldn't be saved.\n"
                    "Check disk space and folder permissions.",
                )

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
        else:
            event.ignore()
            self.hide()
            self.save()

    def shutdown(self):
        if self.quitting:
            return
        self.quitting = True
        for timer in (self.tick_timer, self.save_timer, self.rate_timer, self.retry_timer,
                      self.hover_timer, self.leave_timer, self.bubble_timer):
            timer.stop()
        self.total_bar.dismiss(immediate=True)
        self.time_bar.dismiss(immediate=True)
        self.bubble.dismiss(immediate=True)
        self.tracker.accrue()
        self.tracker.running = False
        self.save()
        if self.tray is not None:
            self.tray.hide()
        QApplication.instance().quit()


def main():
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(QIcon(QPixmap.fromImage(make_icon_image(64))))

    directory = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    ))
    directory.mkdir(parents=True, exist_ok=True)
    app.setStyleSheet(app_stylesheet(directory))

    logging.basicConfig(
        filename=str(directory / "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )

    lock = QLockFile(str(directory / "instance.lock"))
    if not lock.tryLock(100):
        ask(None, APP_NAME, "Island Tracker is already running.\nCheck the system tray.")
        return 0

    store = Store(directory)
    bridge = Bridge()
    island = Island(store, bridge)

    def report_exception(exc_type, exc_value, tb):
        logging.error("Unexpected error", exc_info=(exc_type, exc_value, tb))
        try:
            ask(island, "Unexpected error", f"{exc_value}\n\nDetails: {directory / 'app.log'}")
        except Exception:
            pass

    sys.excepthook = report_exception
    app.commitDataRequest.connect(lambda _manager: island.save())
    app.aboutToQuit.connect(island.shutdown)

    island.show()
    island.start_tray()

    try:
        return app.exec()
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
