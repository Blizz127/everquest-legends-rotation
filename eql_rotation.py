#!/usr/bin/env python3
"""One-button solo Paladin/Cleric assistant for EverQuest Legends on Lutris."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from rotation_core import (Catalog, DEFAULT_GAME, FAMILIES, LABELS, Settings,
                           SLOTS, STATE_FILE, bar_fraction, profile_report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    parser.add_argument("--level", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Read game data and print a plan; never open input devices")
    parser.add_argument("--all-levels", action="store_true", help="Print spell choices from 1 to 50; no input")
    parser.add_argument("--book", type=Path, help="Use this exported spellbook for a dry run")
    parser.add_argument("--gui-smoke-test", type=Path, help="Render the GUI to PNG without starting the input engine")
    args = parser.parse_args()
    settings = Settings.load()
    settings.game_dir = str(args.game_dir)
    if args.level is not None:
        if not 1 <= args.level <= 50:
            parser.error("--level must be between 1 and 50")
        settings.level = args.level
    try:
        catalog = Catalog.load(args.game_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Cannot load the installed client data: {exc}\n")
    if args.dry_run or args.all_levels:
        known = catalog.parse_book(args.book.read_text(errors="replace")) if args.book else None
        reports = [profile_report(catalog, level, known) for level in (range(1, 51) if args.all_levels else [settings.level])]
        print(json.dumps(reports if args.all_levels else reports[0], indent=2))
        return
    if not args.gui_smoke_test:
        import fcntl
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        instance_lock = (STATE_FILE.parent / "instance.lock").open("a")
        try:
            fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, "EQ Legends Solo Assist is already running.\n")
    run_gui(settings, catalog, args.gui_smoke_test)


def run_gui(settings, catalog, smoke_path=None):
    from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF
    from PySide6.QtGui import QColor, QImage, QPixmap, QPen, QPainter
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
        QGridLayout, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
        QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QProgressBar,
        QDialog, QDialogButtonBox, QGraphicsScene, QGraphicsView, QMessageBox,
        QPlainTextEdit, QTabWidget,
    )
    from rotation_engine import Engine

    class Worker(QThread):
        updated = Signal(object)
        captured = Signal(str, object)

        def __init__(self, value):
            super().__init__()
            self.engine = Engine(value, self.updated.emit, self.captured.emit)

        def run(self):
            self.engine.run()

    class SelectionView(QGraphicsView):
        selection = Signal(object)

        def __init__(self, scene):
            super().__init__(scene)
            self.start = None
            self.rectangle = None
            self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        def mousePressEvent(self, event):
            self.start = self.mapToScene(event.position().toPoint())
            if self.rectangle:
                self.scene().removeItem(self.rectangle)
            self.rectangle = self.scene().addRect(QRectF(self.start, self.start), QPen(QColor("#f5ca72"), 2))

        def mouseMoveEvent(self, event):
            if self.start is not None and self.rectangle:
                self.rectangle.setRect(QRectF(self.start, self.mapToScene(event.position().toPoint())).normalized())

        def mouseReleaseEvent(self, event):
            if self.start is None:
                return
            rect = QRectF(self.start, self.mapToScene(event.position().toPoint())).normalized()
            rect = rect.intersected(self.sceneRect())
            self.start = None
            self.selection.emit([int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom())])

    class Calibration(QDialog):
        def __init__(self, image, channel, parent):
            super().__init__(parent)
            self.image, self.channel, self.region = image, channel, None
            self.setWindowTitle("Calibrate health" if channel == "red" else "Calibrate mana")
            self.resize(1100, 720)
            layout = QVBoxLayout(self)
            instruction = QLabel(
                f"At full {'health' if channel == 'red' else 'mana'}, drag a rectangle across the INNER colored gauge, from its left edge to its right edge.\n"
                "Leave out the frame, percentage text, portrait, and any other bars. Recalibrate after changing game resolution or UI layout.")
            instruction.setWordWrap(True)
            layout.addWidget(instruction)
            data = image.tobytes("raw", "RGB")
            qimage = QImage(data, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888).copy()
            self.scene = QGraphicsScene(self)
            self.scene.addPixmap(QPixmap.fromImage(qimage))
            self.view = SelectionView(self.scene)
            self.view.selection.connect(self.selected)
            layout.addWidget(self.view, 1)
            self.reading = QLabel("Select the gauge to preview its reading.")
            layout.addWidget(self.reading)
            self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
            self.buttons.accepted.connect(self.accept)
            self.buttons.rejected.connect(self.reject)
            layout.addWidget(self.buttons)
            QTimer.singleShot(0, lambda: self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio))

        def selected(self, box):
            fraction = bar_fraction(self.image.crop(tuple(box)), self.channel)
            valid = fraction is not None and fraction >= 0.85
            self.region = {"box": box, "window_size": list(self.image.size)} if valid else None
            self.reading.setText(f"Preview: {round(fraction * 100)}%. Save if this is your full gauge." if valid else
                                 "Cannot validate a full gauge here. Select only the inner red/blue bar while it is full.")
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(valid)

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.settings = settings
            self.worker = None
            self.last_state = {}
            self.table_signature = None
            self.setWindowTitle("EQ Legends · Paladin + Cleric Solo")
            self.resize(920, 790)
            body = QWidget()
            self.setCentralWidget(body)
            layout = QVBoxLayout(body)
            layout.setContentsMargins(24, 20, 24, 20)
            layout.setSpacing(14)
            eyebrow = QLabel("EVERQUEST LEGENDS  /  SOLO ASSIST")
            eyebrow.setObjectName("eyebrow")
            layout.addWidget(eyebrow)
            title = QLabel("Paladin + Cleric")
            title.setObjectName("title")
            layout.addWidget(title)
            subtitle = QLabel("One combat key. Your learned spells. Level 1–50.")
            subtitle.setObjectName("muted")
            layout.addWidget(subtitle)
            banner = QFrame()
            banner.setObjectName("banner")
            banner_layout = QHBoxLayout(banner)
            banner_layout.setContentsMargins(16, 14, 16, 14)
            self.state_badge = QLabel("●  STOPPED")
            self.state_badge.setObjectName("state")
            banner_layout.addWidget(self.state_badge)
            banner_layout.addStretch()
            banner_layout.addWidget(QLabel("F8  COMBAT ON     F9  COMBAT OFF     F10  HEAL"))
            layout.addWidget(banner)
            controls = QGridLayout()
            self.character = QComboBox()
            characters = sorted({p.name.split("_")[0] for p in Path(settings.game_dir).glob("*_LO*.ini") if not p.name.startswith("UI_")})
            self.character.addItems(sorted(set(characters + [settings.character])))
            self.character.setCurrentText(settings.character)
            self.level = QSpinBox()
            self.level.setRange(1, 50)
            self.level.setValue(settings.level)
            self.level.setToolTip("Set your current level once. New level-up messages update it automatically while the app runs.")
            self.mode = QComboBox()
            self.mode.addItem("General solo", "balanced")
            self.mode.addItem("Undead camp", "undead")
            self.mode.setCurrentIndex(1 if settings.mode == "undead" else 0)
            self.interval = QDoubleSpinBox()
            self.interval.setRange(4, 30)
            self.interval.setSingleStep(1)
            self.interval.setSuffix(" s")
            self.interval.setValue(settings.damage_interval)
            self.interval.setToolTip("Minimum delay between damage spells. 10 seconds conserves mana; 4 seconds favors damage.")
            for column, (label, widget) in enumerate([("Character", self.character), ("Current level", self.level),
                                                       ("Target type", self.mode), ("Damage cadence", self.interval)]):
                controls.addWidget(QLabel(label), 0, column)
                controls.addWidget(widget, 1, column)
            layout.addLayout(controls)
            self.tabs = QTabWidget()
            combat = QWidget()
            tab_layout = QVBoxLayout(combat)
            tab_layout.setContentsMargins(12, 16, 12, 12)
            self.status = QLabel("Stopped. Enter the game, then press F6 to prepare your learned spells.")
            self.status.setWordWrap(True)
            self.status.setMinimumHeight(42)
            tab_layout.addWidget(self.status)
            self.book_status = QLabel("Preview only until your spellbook is exported in-game.")
            self.book_status.setObjectName("muted")
            tab_layout.addWidget(self.book_status)
            self.table = QTableWidget(0, 5)
            self.table.setHorizontalHeaderLabels(["Gem", "Role", "Spell", "Level", "Mana"])
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
            tab_layout.addWidget(self.table, 1)
            gauges = QHBoxLayout()
            self.hp = QProgressBar()
            self.hp.setObjectName("hp")
            self.hp.setRange(0, 100)
            self.hp.setFormat("HP · calibrate for automatic healing")
            self.hp.setValue(0)
            self.mana = QProgressBar()
            self.mana.setRange(0, 100)
            self.mana.setFormat("Mana · optional calibration")
            self.mana.setValue(0)
            gauges.addWidget(self.hp)
            gauges.addWidget(self.mana)
            tab_layout.addLayout(gauges)
            toggles = QHBoxLayout()
            self.smart_heal = QCheckBox("Healing priority with calibrated HP")
            self.smart_heal.setChecked(settings.smart_heal)
            self.stuns = QCheckBox("Use control stuns during the rotation")
            self.stuns.setChecked(settings.use_stuns)
            self.bash = QCheckBox("Use Bash (shield equipped)")
            self.bash.setChecked(settings.use_bash)
            toggles.addWidget(self.smart_heal)
            toggles.addWidget(self.stuns)
            toggles.addWidget(self.bash)
            tab_layout.addLayout(toggles)
            self.auto_stance = QCheckBox("Automatic Balanced / Defense + Divine invocation")
            self.auto_stance.setChecked(settings.auto_stance)
            self.auto_stance.setEnabled(settings.stance_keys_verified)
            self.auto_stance.setToolTip("Requires verified in-game bindings: Ctrl+Shift+1 Balanced, Ctrl+Shift+2 Defense, Ctrl+Shift+3 Divine.")
            self.auto_stance.toggled.connect(self.changed)
            tab_layout.addWidget(self.auto_stance)
            buttons = QHBoxLayout()
            prep = QPushButton("Prepare spell bar  ·  F6")
            prep.setObjectName("primary")
            prep.clicked.connect(lambda: self.post("prepare_later"))
            hp_button = QPushButton("Calibrate HP")
            hp_button.clicked.connect(lambda: self.post("capture", "red"))
            mana_button = QPushButton("Calibrate mana")
            mana_button.clicked.connect(lambda: self.post("capture", "blue"))
            stop = QPushButton("STOP")
            stop.setObjectName("stop")
            stop.clicked.connect(lambda: self.post("stop"))
            for button in [prep, hp_button, mana_button, stop]:
                buttons.addWidget(button)
            tab_layout.addLayout(buttons)
            self.tabs.addTab(combat, "Combat")
            guide = QPlainTextEdit()
            guide.setReadOnly(True)
            guide.setPlainText(GUIDE)
            self.tabs.addTab(guide, "Solo setup & spells")
            progression = QTableWidget(0, 4)
            progression.setHorizontalHeaderLabels(["Level", "Quick heal", "Direct heal", "General / undead damage"])
            progression.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            progression.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            progression.verticalHeader().setVisible(False)
            progression.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            previous = None
            for level in range(1, 51):
                profile = catalog.profile(level)
                values = [profile.get(role).name if role in profile else "—" for role in ["quick_heal", "heal", "nuke", "undead"]]
                if values == previous:
                    continue
                previous = values
                row = progression.rowCount()
                progression.insertRow(row)
                for col, text in enumerate([str(level), values[0], values[1], values[2] + " / " + values[3]]):
                    progression.setItem(row, col, QTableWidgetItem(text))
            self.tabs.addTab(progression, "1–50 progression")
            layout.addWidget(self.tabs, 1)
            footer = QLabel("F6 prepares  ·  F8 turns persistent combat on  ·  F9 turns it off")
            footer.setWordWrap(True)
            footer.setObjectName("muted")
            layout.addWidget(footer)
            self.render_profile(catalog.profile(settings.level))
            for widget in [self.level, self.interval]:
                widget.valueChanged.connect(self.changed)
            for widget in [self.character, self.mode]:
                widget.currentIndexChanged.connect(self.changed)
            for widget in [self.smart_heal, self.stuns, self.bash]:
                widget.toggled.connect(self.changed)
            if smoke_path is None:
                self.worker = Worker(settings)
                self.worker.updated.connect(self.update_state)
                self.worker.captured.connect(self.calibrate)
                self.worker.start()

        def post(self, name, value=None):
            if self.worker:
                if name in {"stop", "capture", "prepare_later"}:
                    # Cancel a preparation's wait immediately, even while the
                    # worker is inside a command job rather than its main loop.
                    self.worker.engine.cancelled = True
                self.worker.engine.post(name, value)

        def changed(self, *_):
            data = asdict(self.settings)
            data.update(character=self.character.currentText(), level=self.level.value(),
                        mode=self.mode.currentData(), damage_interval=self.interval.value(),
                        smart_heal=self.smart_heal.isChecked(), use_stuns=self.stuns.isChecked(),
                        use_bash=self.bash.isChecked(), auto_stance=self.auto_stance.isChecked())
            self.settings = Settings(**data)
            self.settings.save()
            self.post("settings", self.settings)
            self.render_profile(catalog.profile(self.settings.level))

        def render_profile(self, profile):
            signature = tuple((role, spell.id) for role, spell in sorted(profile.items()))
            if signature == self.table_signature:
                return
            self.table_signature = signature
            rows = sorted(profile.items(), key=lambda item: SLOTS[item[0]])
            self.table.setRowCount(len(rows))
            for row, (role, spell) in enumerate(rows):
                for col, text in enumerate([str(SLOTS[role]), LABELS[role], spell.name, str(spell.level), str(spell.mana)]):
                    item = QTableWidgetItem(text)
                    if col == 2:
                        item.setForeground(QColor("#f5ca72"))
                    self.table.setItem(row, col, item)
            self.table.resizeColumnsToContents()

        def update_state(self, state):
            self.last_state = state
            self.settings.stance_keys_verified = state.get("stance_keys_verified", False)
            self.auto_stance.setEnabled(self.settings.stance_keys_verified and not state["preparing"])
            self.status.setText(state["status"])
            active, preparing = state["active"], state["preparing"]
            self.state_badge.setText("●  COMBAT ON" if active else "●  PREPARING" if preparing else "●  STOPPED")
            self.state_badge.setStyleSheet("color: #7addac;" if active else "color: #f5ca72;" if preparing else "color: #a9b5c5;")
            known = state["known"]
            self.book_status.setText(f"{known} learned Paladin/Cleric spells read · Bar {'prepared' if state['prepared'] else 'needs preparation'}" if known is not None else
                                     "Spell preview · F6 exports your learned spellbook before preparing the bar.")
            self.level.blockSignals(True)
            self.level.setValue(state["level"])
            self.level.blockSignals(False)
            self.settings.level = state["level"]
            self.render_profile(state["profile"])
            for bar, value, name in [(self.hp, state["hp"], "HP"), (self.mana, state["mana"], "Mana")]:
                bar.setValue(round(value * 100) if value is not None else 0)
                bar.setFormat(f"{name} · {round(value * 100)}%" if value is not None else f"{name} · no calibrated reading")
            for widget in [self.level, self.character, self.mode, self.interval,
                           self.smart_heal, self.stuns, self.bash]:
                widget.setEnabled(not preparing)

        def calibrate(self, channel, image):
            dialog = Calibration(image, channel, self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.region:
                data = asdict(self.settings)
                data["hp_region" if channel == "red" else "mana_region"] = dialog.region
                self.settings = Settings(**data)
                self.settings.save()
                self.post("settings", self.settings)
                self.status.setText("Calibration saved. Focus your game and press F8 when ready.")

        def closeEvent(self, event):
            if self.worker:
                self.worker.engine.stopping = True
                self.worker.engine.cancelled = True
                if not self.worker.wait(5000):
                    event.ignore()
                    self.status.setText("Stopping input… close again in a moment.")
                    return
            event.accept()

    app = QApplication(sys.argv[:1])
    app.setApplicationName("EQ Legends Solo Assist")
    app.setStyleSheet(STYLE)
    window = Window()
    import signal
    signal.signal(signal.SIGTERM, lambda *_: window.close())
    signal.signal(signal.SIGINT, lambda *_: window.close())
    window.show()
    if smoke_path:
        def render():
            smoke_path.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(smoke_path))
            app.quit()
        QTimer.singleShot(400, render)
    app.exec()


GUIDE = """QUICK START
1. Enter your Paladin + Cleric loadout. A third class is optional; this profile does not depend on one.
2. Choose your character and current level above. Set the starting level once; future level-up log messages update it while this helper runs.
3. Stand somewhere safe, out of combat. Focus EverQuest and press F6. Preparation exports your learned spellbook and memorizes ONLY spells you own and can use at your selected level. This takes time; F9 cancels.
4. Press F8 to turn combat on, heal low HP, and maintain prepared buffs even with no enemy selected. Repeated F8 presses leave it on. It checks for the enemy you select, fights it, then waits for your next selection after the kill. F9 turns combat off. The helper does not select or pull enemies for you.
5. Optional: at full health, click Calibrate HP and select just the inside of your red HP gauge. Automatic healing requires this reading. F10 requests your fast heal even without calibration.
6. Optional: calibrate the blue mana bar. Below 25% mana the assistant saves mana for healing; below 35% it stops using Smite.

IMPORTANT SOLO SETUP
Use implied healing (Options → Combat) so a heal while targeting your enemy heals its friendly target — normally you while solo tanking. The installer enables this for your existing offline Blizz/Legira character files, with backups. If you use a different character, enable this option there too.
Keep /log on for automatic level detection and encounter stops. The selected character's log filename must match the character you are playing.
When you ding, the current fight finishes using its existing bar. Before the next fight, press F6 or the Prepare spell bar button to refresh learned spells and load upgrades. F8 only toggles combat and never starts preparation. New spells still need to be scribed normally. Mote upgrades apply in the game as usual.
Calibrated readings are only valid for the captured resolution and UI layout. An unavailable/invalid HP reading disables automatic healing; F10 remains available.

ONE-BUTTON PRIORITY
• Critical HP (25% or lower): try Lay on Hands, followed by the fast heal if still needed.
• HP 65% or lower: Cleric Echo/fast-heal line.
• HP 82% or lower: available Celestial heal over time, refreshed no more than once per 24 seconds.
• Paladin Smite ability from level 9, about every 15 seconds; landed Smites reduce the estimated Lay on Hands cooldown.
• Optional Bash about every 8 seconds. Leave it off unless a shield is equipped. Auto-attack supplies sustained melee damage.
• Optional control stun. Off by default to conserve mana.
• A damage spell every 10 seconds by default. Use 4 seconds for faster kills if your mana can sustain it.
Movement keys temporarily pause spell input. A kill or Escape returns the armed helper to waiting. Enter, slash, F9, death, or zoning disarms it. Switching windows pauses input and automatically resumes when EverQuest regains focus.

SPELL GEMS
1: Best learned Echo heal, or your normal heal before level 8.
2: Learned Courage-line HP/AC buff while this slot is vacant; best learned large direct heal once two different heals are available.
3: Strike → Furor (5) → Smite SPELL (14) → Wrath (29) → Retribution (44).
4: Ward Undead (Paladin 1) → Expulse Undead (13) → Dismiss Undead (23) → Expel Undead (33) → Banish Undead (43).
5: Best learned control stun. Triggered only if the stun option is enabled.
6: Celestial Remedy (19) → Celestial Health (29) → Celestial Healing (44).
7: Yaulp → Yaulp II (Cleric 16) → Yaulp III (Cleric 41). Applied once after preparing the bar, and again after a logged death; this permanent buff is not spammed.
8: Instrument of Nife (Paladin 15) → Divine Might (45). Applied once after preparing, and again after a logged death; weapon procs supply extra melee damage.
Smite the Paladin ability and Smite the level-14 Cleric damage spell are different actions. This assistant knows the difference.

SOLO BUFFS AND SPELL PURCHASES
Keep the strongest learned Courage/Center/Daring/Bravery/Valor/Resolution buff active. A Symbol spell can stack with that line but uses a reagent. Use your normal saved buff bar and Quick Buff, then F6 to restore combat gems.
From 8 onward, prioritize scribing the Echo heal upgrades. Buy Healing at 10, Greater Healing at 20 and Superior Healing at 30. Undead nukes matter most when you deliberately choose an undead camp.
Promised Renewal (39) is powerful planned healing, but is delayed and expensive; keep it as a separate manual option rather than an emergency heal in this basic solo rotation.
Automatic stances require verified native bindings in Options → Controls → Stances/Invocations: Ctrl+Shift+1 Balanced, Ctrl+Shift+2 Defense, Ctrl+Shift+3 Divine. The helper reads saved bindings and enables the checkbox only when all match without conflicts. Defense is requested at <=65% HP, Balanced again at >=85%, with Divine invocation. Disable the checkbox for manual choice. Do not bind Ctrl+Shift+F1/F2/F3: KDE desktop shortcuts conflict. The mercenary-only /stance command is never sent.
At low levels, prioritize a useful weapon, shield/armor, and heal efficiency over dumping all mana into damage. At higher levels, raise damage cadence only as sustain allows. The tool does not claim a simulated best-in-slot DPS rotation; it favors a simple, durable solo setup.

SOURCE OF SPELL LEVELS
The installed client's spells_us.txt is authoritative for this installation. The progression tab is a preview; your live bar is filtered against a fresh /outputfile spellbook export. No third-class skills are assumed.
"""

STYLE = """
QWidget { background: #101820; color: #e4eaf2; font-family: 'Noto Sans'; font-size: 13px; }
QLabel#eyebrow { color: #8dacc1; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
QLabel#title { color: #f5ca72; font-size: 32px; font-weight: 700; }
QLabel#muted { color: #93a4b7; font-size: 12px; }
QFrame#banner { background: #1a2934; border: 1px solid #324552; border-radius: 9px; }
QFrame#banner QLabel { background: transparent; }
QLabel#state { font-size: 14px; font-weight: 700; }
QComboBox, QSpinBox, QDoubleSpinBox { background: #1c2a36; border: 1px solid #3b4c5b; border-radius: 5px; padding: 7px; min-height: 22px; }
QPushButton { background: #223440; border: 1px solid #415668; border-radius: 5px; padding: 10px 12px; }
QPushButton:hover { background: #304959; }
QPushButton#primary { background: #e2bc70; color: #17212b; border-color: #e2bc70; font-weight: 700; }
QPushButton#stop { background: #482a32; color: #ffb9c2; border-color: #7f3b4b; }
QTabWidget::pane { border: 1px solid #304452; border-radius: 6px; }
QTabBar::tab { background: #192631; color: #9bb0c1; padding: 10px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #f5ca72; border-bottom-color: #f5ca72; }
QTableWidget { background: #131e28; border: 1px solid #2b3b48; gridline-color: #263643; alternate-background-color: #1b2935; }
QTableWidget::item { padding: 8px; }
QHeaderView::section { background: #20313f; border: 0; border-bottom: 1px solid #344855; padding: 8px; color: #a6bfd0; font-size: 12px; }
QProgressBar { background: #1b2a37; border: 1px solid #304859; border-radius: 5px; text-align: center; min-height: 25px; font-size: 11px; }
QProgressBar::chunk { background: #284e78; border-radius: 4px; }
QProgressBar#hp::chunk { background: #783d4a; }
QPlainTextEdit { background: #131e28; border: none; padding: 12px; font-size: 13px; }
QCheckBox { padding: 5px 0; }
"""


if __name__ == "__main__":
    main()
