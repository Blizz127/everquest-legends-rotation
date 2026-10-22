"""Linux/XWayland input bridge. All injected keys pass the game-focus gate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import selectors
import time
from dataclasses import asdict, is_dataclass

from rotation_core import (Catalog, LogTail, Rotation, Settings, StancePlan, SLOTS, STATE_FILE,
                           bar_fraction, level_from_message, message_body, stance_bindings_match)

DEVICE_NAME = "eql-paladin-cleric-rotation"
HOTKEYS = ("F6", "F8", "F9", "F10")

CONSIDER_REACTIONS = (
    ("ally", "regards you as an ally"),
    ("warmly", "looks upon you warmly"),
    ("kindly", "kindly considers you"),
    ("amiable", "judges you amiably"),
    ("indifferent", "regards you indifferently"),
    ("scowls", "scowls at you, ready to attack"),
    ("threatening", "glares at you threateningly"),
    ("dubious", "glowers at you dubiously"),
    ("apprehensive", "looks your way apprehensively"),
)
FRIENDLY_REACTIONS = {"ally", "warmly", "kindly", "amiable"}
HOSTILE_REACTIONS = {"scowls", "threatening"}
PROTECTED_TARGET_WORDS = re.compile(
    r"\b(?:guard|merchant|banker|guildmaster|trainer|vendor|innkeeper|"
    r"bartender|shopkeeper|stablemaster|gatekeeper|watchman|sentinel|deputy|"
    r"citizen|priest|healer|scribe|blacksmith|armorer|weaponsmith|brewer)\b",
    re.IGNORECASE,
)


def consider_target(body: str) -> tuple[str, str, int | None] | None:
    """Extract target name, faction reaction, and level from a /consider line."""
    folded = body.casefold()
    level_match = re.search(r"\(Lvl:\s*(\d+)\)", body, re.IGNORECASE)
    target_level = int(level_match.group(1)) if level_match else None
    for reaction, phrase in CONSIDER_REACTIONS:
        marker = " " + phrase
        offset = folded.rfind(marker)
        if offset > 0:
            return body[:offset].strip(), reaction, target_level
    return None


def safe_leveling_target(name: str, reaction: str, kind: str | None = None,
                         target_level: int | None = None,
                         player_level: int | None = None, *,
                         retaliating: bool = False) -> bool:
    """Conservatively allow monsters while refusing friendly/service NPCs."""
    kind = (kind or "unknown").casefold()
    if kind not in {"npc", "unknown"}:
        return False
    if reaction in FRIENDLY_REACTIONS or PROTECTED_TARGET_WORDS.search(name):
        return False
    # The owner chooses the difficulty. Level is informational; protection
    # depends on NPC identity/faction, never the level difference.
    generic_monster = name.casefold().startswith(("a ", "an "))
    if generic_monster:
        return True
    # Live Crushbone /con names omit the article: "Orc taskmaster", etc.
    # Hostility is required here; player/service/friendly checks above win.
    if name.casefold().startswith("orc ") and reaction in HOSTILE_REACTIONS:
        return True
    # Named targets are allowed only when EQ identified them as NPCs and their
    # faction reaction is explicitly kill-on-sight. Unknown proper names stay
    # protected, which favors a harmless false refusal over attacking a quest NPC.
    return kind == "npc" and (retaliating or reaction in HOSTILE_REACTIONS)


def game_identity(classes: tuple[str, ...], title: str, command: str = "") -> bool:
    normalized = " ".join(classes).casefold()
    if "eqgame" in normalized:
        return True
    # Some Wine builds publish only a generic class. Accept the executable
    # associated with the window's own PID, never its title alone.
    executable = command.replace("\\", "/").casefold().split("\0", 1)[0].strip('"')
    return executable.rsplit("/", 1)[-1] == "eqgame.exe" and "everquest" in title.casefold()


class WindowGate:
    def __init__(self):
        from Xlib import display, X, XK
        self.display = display.Display()
        self.X, self.XK = X, XK
        self.root = self.display.screen().root
        self.grabbed = set()
        self.grab_errors = []

    def identity(self, window):
        try:
            classes = tuple(window.get_wm_class() or ())
            title = window.get_wm_name() or ""
            pid_prop = window.get_full_property(self.display.intern_atom("_NET_WM_PID"), self.X.AnyPropertyType)
            command = ""
            if pid_prop is not None and len(pid_prop.value):
                try:
                    command = (Path("/proc") / str(int(pid_prop.value[0])) / "cmdline").read_bytes().decode(errors="replace")
                except OSError:
                    pass
            return game_identity(classes, title, command)
        except Exception:
            return False

    def focused_window(self):
        try:
            candidates = []
            prop = self.root.get_full_property(self.display.intern_atom("_NET_ACTIVE_WINDOW"), self.X.AnyPropertyType)
            if prop is not None and len(prop.value) and int(prop.value[0]):
                candidates.append(self.display.create_resource_object("window", int(prop.value[0])))

            # KWin/XWayland can publish an internal proxy as _NET_ACTIVE_WINDOW
            # while XGetInputFocus still points at the real fullscreen EQ window.
            # Accept that window only after applying the same executable-backed
            # identity check used for the normal active-window path.
            focused = self.display.get_input_focus().focus
            if getattr(focused, "id", 0):
                candidates.append(focused)
            elif isinstance(focused, int) and focused > 1:
                candidates.append(self.display.create_resource_object("window", focused))

            for window in candidates:
                if self.identity(window):
                    return window
            return None
        except Exception:
            return None

    def focused(self) -> bool:
        return self.focused_window() is not None

    def windows(self):
        try:
            prop = self.root.get_full_property(self.display.intern_atom("_NET_CLIENT_LIST"), self.X.AnyPropertyType)
            values = prop.value if prop is not None else []
            result = []
            for value in values:
                window = self.display.create_resource_object("window", int(value))
                if self.identity(window):
                    result.append(window)
            return result
        except Exception:
            return []

    def game_session(self):
        """Identify one live EQ process strongly enough to survive helper restarts."""
        windows = self.windows()
        if len(windows) != 1:
            return None
        try:
            prop = windows[0].get_full_property(self.display.intern_atom("_NET_WM_PID"), self.X.AnyPropertyType)
            if prop is None or not len(prop.value):
                return None
            pid = int(prop.value[0])
            # Field 22 is the kernel start-time tick. Parsing after the final
            # parenthesis handles process names containing spaces safely.
            tail = (Path("/proc") / str(pid) / "stat").read_text().rpartition(") ")[2].split()
            return {"pid": pid, "start_ticks": tail[19]}
        except (OSError, ValueError, IndexError):
            return None

    def refresh_grabs(self):
        # Consume the helper keys in EQ itself: the game's default F8 must not
        # also retarget a nearby NPC when the user arms the tool.
        for window in self.windows():
            if window.id in self.grabbed:
                continue
            for name in HOTKEYS:
                code = self.display.keysym_to_keycode(self.XK.string_to_keysym(name))
                window.grab_key(code, self.X.AnyModifier, False,
                                self.X.GrabModeAsync, self.X.GrabModeAsync,
                                onerror=lambda error, request: self.grab_errors.append(str(error)))
            self.display.sync()
            if not self.grab_errors:
                self.grabbed.add(window.id)
        while self.display.pending_events():
            self.display.next_event()

    def controls_ready(self) -> bool:
        window = self.focused_window()
        return window is not None and window.id in self.grabbed and not self.grab_errors

    def capture(self):
        from PIL import Image
        windows = self.windows()
        if not windows:
            raise RuntimeError("Enter the game on your character first, then try calibration again.")
        window = self.focused_window() or windows[0]
        geometry = window.get_geometry()
        raw = window.get_image(0, 0, geometry.width, geometry.height, self.X.ZPixmap, 0xFFFFFFFF)
        if raw is None:
            raise RuntimeError("The game window did not provide an image. Use windowed/borderless mode.")
        stride = len(raw.data) // geometry.height
        if stride < geometry.width * 3:
            raise RuntimeError("Unsupported game-window image format.")
        mode = "BGRX" if stride >= geometry.width * 4 else "BGR"
        return Image.frombytes("RGB", (geometry.width, geometry.height), raw.data, "raw", mode, stride)

    def read_gauges(self, hp_region, mana_region):
        if not hp_region and not mana_region:
            return None, None
        try:
            image = self.capture()
            values = []
            for region, channel in [(hp_region, "red"), (mana_region, "blue")]:
                if not region or tuple(region.get("window_size", [])) != image.size:
                    values.append(None)
                    continue
                box = region.get("box", [])
                if len(box) != 4 or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                    values.append(None)
                    continue
                values.append(bar_fraction(image.crop(tuple(box)), channel))
            return tuple(values)
        except Exception:
            return None, None

    def close(self):
        try:
            self.display.close()  # Releases all of this client's passive grabs.
        except Exception:
            pass


class KeySender:
    def __init__(self, gate: WindowGate, allowed):
        import evdev
        from evdev import ecodes
        self.codes = ecodes
        self.gate, self.allowed = gate, allowed
        self.ui = evdev.UInput({ecodes.EV_KEY: list(range(1, 256))}, name=DEVICE_NAME)
        self.held = set()
        self.unfinished = False
        # udev/libinput must discover a newly created keyboard before its
        # first command. Live checks lost that first command without a pause.
        time.sleep(1.0)

    def check(self):
        if not self.allowed() or not self.gate.controls_ready():
            raise InterruptedError("Input stopped: game lost focus, chat opened, or stop was pressed.")

    def tap(self, code, release_delay=0.020):
        self.check()
        self.ui.write(self.codes.EV_KEY, code, 1)
        self.ui.syn()
        self.held.add(code)
        try:
            # Keep the full key-down interval: the old 8 ms sequence lost
            # letters in the live client.
            time.sleep(0.020)
        finally:
            self.ui.write(self.codes.EV_KEY, code, 0)
            self.ui.syn()
            self.held.discard(code)
        if release_delay:
            time.sleep(release_delay)

    def character(self, char):
        if char.isalpha() and char.isascii():
            code = getattr(self.codes, "KEY_" + char.upper())
        elif char.isdigit():
            code = getattr(self.codes, "KEY_" + char)
        else:
            code = {" ": self.codes.KEY_SPACE, "/": self.codes.KEY_SLASH,
                    "-": self.codes.KEY_MINUS, ".": self.codes.KEY_DOT}.get(char)
        if code is None:
            raise ValueError(f"Unsupported command character: {char!r}")
        # Different letters already leave each previous key released while
        # the next is held. Only adjacent repeats (e.g. "off") need an extra
        # release interval so EQ observes two separate presses of that key.
        if getattr(self, "last_character_code", None) == code:
            time.sleep(0.020)
        self.tap(code, release_delay=0)
        self.last_character_code = code

    def command(self, text):
        # These are game commands, not chat messages. Keep the command surface
        # narrow; character/account names are never interpolated into a command.
        if not re.fullmatch(r"/(?:consider|attack (?:on|off)|cast [1-8]|alt activate 6001|doability (?:Bash|Smite)|outputfile spellbook eql-rotation-spellbook.txt|memspellslot [1-8] \d+)", text):
            raise ValueError("Command is outside the rotation's supported command set")
        # The installed client's eqstr_us.txt lists /con (string 6668).
        # Keep the engine's canonical command and safety gate unchanged.
        if text == "/consider":
            text = "/con"
        self.unfinished = False
        self.last_character_code = None
        for char in text:
            self.character(char)
            # A held movement key can block the very first slash. In that
            # case there is no draft to dismiss: Escape would clear the mob.
            self.unfinished = True
        self.tap(self.codes.KEY_ENTER)
        self.unfinished = False

    def stance(self, role):
        # These exact unused chords must first be assigned and verified in
        # the client's Stances/Invocations key-binding page.
        keys = {"balanced": self.codes.KEY_1, "defensive": self.codes.KEY_2,
                "divine": self.codes.KEY_3}
        if role not in keys:
            raise ValueError("Unsupported stance control")
        modifiers = (self.codes.KEY_LEFTCTRL, self.codes.KEY_LEFTSHIFT)
        try:
            for code in modifiers:
                self.check()
                self.ui.write(self.codes.EV_KEY, code, 1)
                self.ui.syn()
                self.held.add(code)
            time.sleep(.05)
            self.tap(keys[role])
            time.sleep(.05)
        finally:
            for code in reversed(modifiers):
                if code in self.held:
                    self.ui.write(self.codes.EV_KEY, code, 0)
                    self.ui.syn()
                    self.held.discard(code)

    def cancel_unfinished(self):
        """Dismiss a partial EQ chat command once the input gate is safe."""
        if not self.unfinished:
            return False
        self.tap(self.codes.KEY_ESC)
        self.unfinished = False
        return True

    def close(self):
        for code in list(self.held):
            self.ui.write(self.codes.EV_KEY, code, 0)
        self.ui.syn()
        self.ui.close()


class Engine:
    def __init__(self, settings: Settings, notify, capture_ready):
        self.settings, self.notify, self.capture_ready = settings, notify, capture_ready
        self.jobs = queue.SimpleQueue()
        self.stopping = False
        self.active = False
        self.preparing = False
        self.cancelled = False
        self.cancel_generation = 0
        self.sender = None
        self.gate = None
        self.keys = set()
        self.prepared = False
        self.prepared_level = None
        self.prepared_state_path = STATE_FILE.parent / "prepared.json"
        self.profile = {}
        self.failed_mem = False
        self.known = None
        self.hp = self.mana = None
        self.rotation = None
        self.stances = StancePlan()
        self.status = "Enter EverQuest Legends, then press F6 to prepare your spell bar."
        self.next_job_at = 0.0
        self.deferred = None
        self.focused = False
        self.last_grabs = self.last_gauge = self.last_devices = 0.0
        self.hotkey_releases = {}
        self.last_action_role = None
        # None means one safety probe is pending. False means no target or a
        # blocked target was already observed, so persistent combat waits
        # silently until EQ logs a new owner-selected target.
        self.target_ready = None
        self.target_name = None
        self.target_kind = None
        self.attackers_seen = set()
        self.recent_attackers = {}
        self.target_retaliation = False
        self.attack_started = False
        self.native_attack_off_pending = False
        self.next_target_probe = 0.0
        # Slash-command injection must not type over an in-progress spell cast.
        # Keep this separate from Rotation.busy_until because no-target log
        # handling can reset rotation retries while the cast still owns input.
        self.command_pause_until = 0.0
        self.mana_blocked_until = 0.0
        # A focus or movement interruption can leave a partially typed slash
        # command in EQ's chat entry. Keep combat armed, then clear that draft
        # once input is safe again before sending any other command.
        self.command_recovery_pending = False
        self.selector = selectors.DefaultSelector()
        trace_path = os.environ.get("EQL_ROTATION_TRACE")
        self.trace_path = Path(trace_path) if trace_path else None

    def trace(self, event, **values):
        """Optional local event trace for diagnosing a live input device."""
        if not self.trace_path:
            return
        record = {"time": time.time(), "event": event, **values}
        try:
            with self.trace_path.open("a", encoding="utf-8") as target:
                target.write(json.dumps(record, sort_keys=True,
                                       default=lambda value: asdict(value) if is_dataclass(value) else str(value)) + "\n")
        except OSError:
            self.trace_path = None  # Diagnostics must not stop combat assistance.

    def post(self, name, value=None):
        self.jobs.put((name, value))

    def emit(self, text=None):
        if text:
            self.status = text
            self.trace("status", message=text, active=self.active,
                       hp=self.hp, mana=self.mana, focused=self.focused,
                       target_ready=self.target_ready)
        self.notify({"status": self.status, "active": self.active,
                     "preparing": self.preparing, "level": self.settings.level,
                     "profile": self.profile, "prepared": self.prepared,
                     "known": len(self.known) if self.known is not None else None,
                     "stance_keys_verified": self.settings.stance_keys_verified,
                     "hp": self.hp, "mana": self.mana, "focused": self.focused})

    def allowed(self):
        self.input_events()  # Honor F9/chat during a typed command, not just between commands.
        return not self.stopping and not self.cancelled and not self.blocked_keys()

    def blocked_keys(self):
        from evdev import ecodes as e
        return bool(self.keys & {e.KEY_W, e.KEY_A, e.KEY_S, e.KEY_D, e.KEY_UP, e.KEY_DOWN,
                                 e.KEY_LEFT, e.KEY_RIGHT, e.KEY_SPACE, e.KEY_LEFTCTRL,
                                 e.KEY_RIGHTCTRL, e.KEY_LEFTALT, e.KEY_RIGHTALT,
                                 e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT, e.KEY_F9,
                                 e.KEY_ESC, e.KEY_ENTER, e.KEY_KPENTER, e.KEY_SLASH})

    def stop_keys_held(self):
        """Keys that make arming unsafe, unlike movement/modifier pauses."""
        from evdev import ecodes as e
        return bool(self.keys & {e.KEY_F9, e.KEY_ESC, e.KEY_ENTER,
                                 e.KEY_KPENTER, e.KEY_SLASH})

    def open_devices(self):
        import evdev
        from evdev import ecodes as e
        registered = {key.fileobj.path for key in self.selector.get_map().values()}
        for path in evdev.list_devices():
            if path in registered:
                continue
            try:
                device = evdev.InputDevice(path)
                keys = device.capabilities().get(e.EV_KEY, [])
                if device.name == DEVICE_NAME or e.KEY_F8 not in keys:
                    device.close()
                else:
                    self.selector.register(device, selectors.EVENT_READ)
                    self.trace("keyboard_opened", path=path, name=device.name)
            except (OSError, PermissionError):
                continue

    def stop_action(self, reason):
        self.trace("stopped", reason=reason, active=self.active,
                   attack_started=self.attack_started)
        if self.active or self.attack_started:
            self.native_attack_off_pending = True
        self.active = False
        self.recent_attackers.clear()
        self.target_retaliation = False
        self.attack_started = False
        self.last_action_role = None
        self.cancelled = True
        self.command_recovery_pending = False
        self.cancel_generation += 1
        self.deferred = None
        self.emit(reason)

    def handle_input_failure(self, exc):
        """Pause transient input failures without turning persistent combat off."""
        if isinstance(exc, InterruptedError) and self.active:
            draft = bool(self.sender and self.sender.unfinished)
            self.trace("input_paused", reason=str(exc),
                       unfinished=draft)
            if draft:
                self.attack_started = False
                self.native_attack_off_pending = True
                self.last_action_role = None
                self.command_recovery_pending = True
            self.emit("Combat ON · paused during an interrupted command · "
                      "resumes safely when EverQuest is focused")
            return True
        self.stop_action(str(exc))
        return False

    def recover_interrupted_command(self):
        """Clear a partial command before persistent combat sends more input."""
        if not self.command_recovery_pending:
            return False
        if (not self.active or self.blocked_keys()
                or not self.gate.controls_ready()):
            return False
        if self.sender and self.sender.unfinished:
            self.sender.cancel_unfinished()
        self.command_recovery_pending = False
        self.target_ready = None
        self.target_name = None
        self.target_kind = None
        self.attack_started = False
        self.native_attack_off_pending = True
        self.next_target_probe = time.monotonic() + 0.25
        self.emit("Combat ON · interrupted command cleared · "
                  "waiting to safety-check your target")
        return True

    def accept_hotkey(self, code, now=None):
        """Collapse one physical release reported by multiple input devices."""
        now = time.monotonic() if now is None else now
        previous = self.hotkey_releases.get(code, float("-inf"))
        self.hotkey_releases[code] = now
        return now - previous >= 0.35

    def input_events(self):
        from evdev import ecodes as e
        for key, _ in self.selector.select(timeout=0):
            device = key.fileobj
            try:
                events = list(device.read())
            except OSError:
                self.selector.unregister(device)
                device.close()
                self.keys.clear()
                self.stop_action("Keyboard disconnected. Reconnect it and press F8 when ready.")
                continue
            for event in events:
                if event.type != e.EV_KEY:
                    continue
                if event.code in {e.KEY_F6, e.KEY_F7, e.KEY_F8, e.KEY_F9, e.KEY_F10,
                                  e.KEY_ESC, e.KEY_ENTER, e.KEY_KPENTER, e.KEY_SLASH}:
                    self.trace("key", code=event.code, value=event.value,
                               active=self.active, preparing=self.preparing,
                               held=sorted(self.keys))
                if event.value == 1:
                    self.keys.add(event.code)
                    if (event.code in {e.KEY_ESC, e.KEY_ENTER, e.KEY_KPENTER, e.KEY_SLASH}
                            and self.gate is not None and not self.gate.focused()):
                        # Chat shortcuts in Codex/another app must not change
                        # EQ's armed state or target. F9 remains a global stop.
                        continue
                    if (event.code in {e.KEY_ENTER, e.KEY_KPENTER}
                            and self.keys & {e.KEY_LEFTALT, e.KEY_RIGHTALT}):
                        # Alt+Enter switches the game window mode; it does
                        # not open chat. Modifiers still pause injected keys.
                        continue
                    if event.code in {e.KEY_F9, e.KEY_ENTER, e.KEY_KPENTER, e.KEY_SLASH}:
                        if self.sender and event.code in {e.KEY_ENTER, e.KEY_KPENTER}:
                            self.sender.unfinished = False
                        reason = ("Stopped by F9. Press F8 when you are ready again."
                                  if event.code == e.KEY_F9 else
                                  "Stopped because chat input opened. Press F8 after closing chat.")
                        self.stop_action(reason)
                    elif event.code == e.KEY_ESC:
                        if self.sender and self.sender.unfinished:
                            self.sender.unfinished = False
                            if not self.active:
                                self.stop_action("Command cancelled by Escape. Press F6 when ready.")
                        if self.active:
                            # Escape is EQ's normal clear-target key. Keep the
                            # persistent toggle armed and wait for a new target.
                            self.target_ready = False
                            self.target_name = None
                            self.target_kind = None
                            self.attackers_seen.clear()
                            self.attack_started = False
                            self.native_attack_off_pending = True
                            self.last_action_role = None
                            self.emit("Combat ON · target cleared · waiting for your target · F9 stop")
                elif event.value == 0:
                    self.keys.discard(event.code)
                    if event.code in {e.KEY_F6, e.KEY_F7, e.KEY_F8, e.KEY_F9, e.KEY_F10} and not self.accept_hotkey(event.code):
                        continue
                    if event.code == e.KEY_F7 and not self.preparing:
                        # Single toggle (Legion Go 2 Y1 arrives as F7): F9 while
                        # combat is on, F8 while it is off.
                        if self.active:
                            if self.gate.controls_ready():
                                self.jobs.put(("attack_off", self.cancel_generation))
                        elif not self.stop_keys_held():
                            self.trace("arm_queued", generation=self.cancel_generation, source="F7")
                            self.jobs.put(("arm", self.cancel_generation))
                        else:
                            self.trace("arm_ignored", reason="stop_key_held",
                                       held=sorted(self.keys))
                        continue
                    if event.code == e.KEY_F8 and not self.preparing:
                        if not self.stop_keys_held():
                            self.trace("arm_queued", generation=self.cancel_generation)
                            self.jobs.put(("arm", self.cancel_generation))
                        else:
                            self.trace("arm_ignored", reason="stop_key_held",
                                       held=sorted(self.keys))
                    elif event.code == e.KEY_F6 and self.gate.controls_ready() and not self.preparing:
                        self.jobs.put(("prepare", self.cancel_generation))
                    elif event.code == e.KEY_F10 and self.gate.controls_ready() and not self.preparing:
                        self.jobs.put(("heal", self.cancel_generation))
                    elif event.code == e.KEY_F9 and self.gate.controls_ready() and not self.preparing:
                        self.jobs.put(("attack_off", self.cancel_generation))

    def read_log(self):
        for line in self.tail.poll():
            level = level_from_message(line)
            if level is not None:
                self.settings.level = level
                self.settings.save()
                self.prepared_level = None
                self.emit(f"Level {level}! Stop between fights, then press F6 to refresh learned spell upgrades.")
            body = message_body(line)
            now = time.monotonic()
            stance = re.fullmatch(r"You assume (?:a|an) (.+?) stance\.", body)
            if stance:
                self.stances.stance = {"balanced": "balanced", "defensive": "defensive"}.get(stance.group(1))
                self.stances.stance_ready_at = now + 6
                self.trace("stance_confirmed", stance=stance.group(1))
            invocation = re.fullmatch(r"You begin reciting the (.+?) invocation\.", body)
            if invocation:
                self.stances.invocation = invocation.group(1)
                self.stances.invocation_ready_at = now + 6
                self.trace("invocation_confirmed", invocation=invocation.group(1))
            if re.match(r"^You smite .+ for \d+", body) and self.rotation:
                self.rotation.landed_smite()

            targeted = re.match(r"^Targeted \(([^)]+)\):\s*(.+)$", body)
            if targeted:
                self.target_retaliation = False
                self.target_kind = targeted.group(1)
                self.target_name = targeted.group(2).strip()
                self.target_ready = (None
                                     if self.target_kind.casefold() == "npc"
                                     else False)
                self.attack_started = False
                self.native_attack_off_pending = True
                self.next_target_probe = now
                if self.active:
                    if self.target_kind.casefold() == "npc":
                        self.emit(f"Combat ON · checking {self.target_name} before attacking · F9 stop")
                    else:
                        self.emit(f"Protected {self.target_kind.lower()} target blocked · select a leveling mob")

            considered = consider_target(body)
            if considered:
                name, reaction, target_level = considered
                same_target = (self.target_name is not None
                               and self.target_name.casefold() == name.casefold())
                previously_approved = same_target and self.target_ready is True
                kind = self.target_kind if same_target else None
                self.target_name = name
                self.target_kind = kind or "Unknown"
                if not previously_approved:
                    self.attack_started = False
                ordinary = safe_leveling_target(name, reaction, kind, target_level,
                                                self.settings.level)
                retaliation = self.is_recent_attacker(name, now) or previously_approved
                permitted = ordinary or (retaliation and safe_leveling_target(
                    name, reaction, kind, target_level, self.settings.level,
                    retaliating=True))
                self.target_retaliation = bool(permitted and not ordinary)
                if permitted:
                    self.target_ready = True
                    if self.active:
                        self.emit(f"Combat ON · defending against attacker: {name} · F9 stop"
                                  if self.target_retaliation else
                                  f"Combat ON · leveling mob verified: {name} · F9 stop")
                else:
                    self.target_ready = False
                    self.native_attack_off_pending = True
                    self.next_target_probe = now + 2.0
                    if self.active:
                        if (retaliation and (kind or "unknown").casefold() == "unknown"
                                and not PROTECTED_TARGET_WORDS.search(name)
                                and reaction not in FRIENDLY_REACTIONS):
                            self.emit(f"Click {name} once to confirm it is an NPC; healing stays ON")
                        else:
                            self.emit(f"Protected target blocked: {name} · select a clear leveling mob")

            if body.startswith("You have slain "):
                killed = body.removeprefix("You have slain ").rstrip("!.").casefold()
                self.recent_attackers.pop(killed, None)
                self.target_retaliation = False
                self.attackers_seen.clear()
                self.target_ready = False
                self.target_name = None
                self.target_kind = None
                self.attack_started = False
                self.native_attack_off_pending = True
                self.last_action_role = None
                self.next_target_probe = now + 0.5
                if self.active:
                    self.emit("Combat ON · waiting for your target · F9 stop")
            incoming = re.match(
                r"^([A-Za-z][A-Za-z '\-]{0,79}) (?:[a-z]+ YOU for \d+ points? of damage|tries to [a-z ]+ YOU, but misses!)",
                body)
            if self.active and incoming:
                attacker = incoming.group(1).casefold()
                self.recent_attackers[attacker] = now
                fresh = attacker not in self.attackers_seen
                self.attackers_seen.add(attacker)
                if fresh and self.target_ready is False:
                    # EQ can auto-select an add without a Targeted log line.
                    # Wake one /consider of the CURRENT target; never select
                    # an attacker or infer attack permission from damage.
                    self.target_ready = None
                    self.attack_started = False
                    self.native_attack_off_pending = True
                    self.next_target_probe = now
                    self.trace("incoming_target_check", attacker=incoming.group(1))
                    self.emit("Combat ON · incoming attacker · rechecking current target safely")
            if re.match(r"^(?:You have been slain |You died|You die[.!])", body):
                self.stop_action("You died. Combat stopped; press F8 when you are ready again.")
                if self.rotation:
                    for role in ("armor", "yaulp", "proc"):
                        self.rotation.last.pop(role, None)
            if re.match(r"^(?:LOADING, PLEASE WAIT|You have entered )", body):
                self.stop_action("Zone changed. Combat stopped; press F8 when you are ready again.")
            if re.match(r"^(?:Consider whom\?|You no longer have a target|You must first (?:select|click)|You do not have a target)", body):
                self.target_ready = False
                self.target_name = None
                self.target_kind = None
                self.attack_started = False
                self.native_attack_off_pending = True
                self.next_target_probe = max(self.next_target_probe, now + 2.0)
                if self.rotation and self.last_action_role:
                    self.rotation.last.pop(self.last_action_role, None)
                    self.rotation.busy_until = 0.0
                self.last_action_role = None
                if self.active:
                    self.emit("Combat ON · waiting for your target · F9 stop")
            if re.match(r"^(?:You cannot see your target|Your target is out of range|Your target is too far away)", body):
                # Range and visibility errors prove a target exists, but not
                # that it is a safe leveling mob. Never promote an unverified
                # target from one of these messages alone.
                if self.target_ready is True:
                    self.attack_started = False
                if self.active:
                    if (self.target_ready is True and self.rotation
                            and self.last_action_role in {"nuke", "undead", "stun", "smite_ability", "bash"}):
                        self.rotation.last.pop(self.last_action_role, None)
                        self.rotation.busy_until = now + 1.0
                    self.emit("Verified mob is approaching or line of sight is blocked; combat stays ON and will retry."
                              if self.target_ready is True else
                              "Target remains protected until its safety check completes.")
            if re.match(r"^Your (?:spell|.+? spell) (?:fizzles|is interrupted)", body) and self.rotation:
                self.rotation.busy_until = now + 1.5
                if self.last_action_role:
                    self.rotation.last.pop(self.last_action_role, None)
                self.command_pause_until = now + 1.5
            faded = re.fullmatch(r"Your (.+?) spell has worn off[.!]", body)
            if faded and self.rotation:
                for role in ("armor", "yaulp", "proc"):
                    spell = self.profile.get(role)
                    if spell and spell.name.casefold() == faded.group(1).casefold():
                        self.rotation.last.pop(role, None)
            if re.match(r"^(?:You cannot memorize|You are not high enough level to memorize|You do not have that spell|You do not have this spell)", body):
                self.failed_mem = True
            if "Insufficient Mana" in body and self.active:
                self.mana_blocked_until = now + 5.0
                self.emit("Combat ON · low mana · melee continues; spell retry in 5 seconds · F9 stops")

    def pump(self):
        self.input_events()
        self.read_log()
        was_focused = self.focused
        self.focused = self.gate.focused()
        if self.preparing and not self.focused:
            self.stop_action("Preparation stopped because EverQuest lost focus. Press F6 after returning.")
        elif self.active and not self.focused:
            # The game-focus gate already prevents all injected input. Keep the
            # toggle armed so a temporary alt-tab does not require another F8.
            if was_focused or "paused" not in self.status.casefold():
                self.emit("Combat ON · paused while EverQuest is unfocused · resumes when you return")
        elif self.active and self.focused and not was_focused:
            if self.blocked_keys():
                self.emit("Combat ON · paused while a movement or modifier key is held")
            else:
                self.emit("Combat ON · verified leveling mob · F9 stop"
                          if self.target_ready is True else
                          "Combat ON · waiting to safety-check your target · F9 stop")

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump()
            if not self.allowed() or not self.gate.controls_ready():
                raise InterruptedError("Preparation stopped. Focus the game and press F6 to retry.")
            time.sleep(0.025)

    def is_recent_attacker(self, name, now=None):
        now = time.monotonic() if now is None else now
        return (name is not None
                and now - self.recent_attackers.get(name.casefold(), float("-inf")) <= 12.0)

    def send(self, command):
        self.pump()
        if command in {"/attack on", "/cast 3", "/cast 4", "/cast 5",
                       "/doability Bash", "/doability Smite"}:
            if not self.active or self.target_ready is not True or self.native_attack_off_pending:
                raise InterruptedError("Target changed before attack; a fresh safety check is required.")
        if self.sender is None:
            self.sender = KeySender(self.gate, self.allowed)
        self.sender.command(command)

    def flush_native_attack_off(self):
        """Turn off EQ melee without changing whether persistent combat is armed."""
        if (not self.native_attack_off_pending or self.blocked_keys()
                or not self.gate.controls_ready()):
            return False
        self.native_attack_off_pending = False
        self.cancelled = False
        try:
            self.send("/attack off")
            self.attack_started = False
            return True
        except Exception:
            self.native_attack_off_pending = True
            raise
        finally:
            if not self.active:
                self.cancelled = True

    def probe_target(self, now):
        """Identify a player-selected target without selecting or attacking it."""
        if (not self.active or self.target_ready is not None
                or now < max(self.next_target_probe, self.command_pause_until)):
            return False
        self.send("/consider")
        self.target_ready = None
        self.attack_started = False
        self.next_target_probe = now + 2.0
        self.emit("Combat ON · checking that your selected target is a leveling mob · F9 stops")
        return True

    def make_rotation(self, profile):
        return Rotation(profile, self.settings.level,
                        mode=self.settings.mode,
                        damage_interval=self.settings.damage_interval,
                        smart_heal=self.settings.smart_heal,
                        use_stuns=self.settings.use_stuns,
                        use_bash=self.settings.use_bash)

    def prepared_marker(self):
        session = self.gate.game_session() if self.gate else None
        if not session or not self.profile:
            return None
        return {
            "character": self.settings.character,
            "server": self.settings.server,
            "level": self.settings.level,
            "game_dir": self.settings.game_dir,
            "session": session,
            "spell_ids": sorted(spell.id for spell in self.profile.values()),
        }

    def save_prepared_state(self):
        marker = self.prepared_marker()
        if marker is None:
            return
        try:
            self.prepared_state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.prepared_state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(marker, indent=2))
            temporary.chmod(0o600)
            temporary.replace(self.prepared_state_path)
        except OSError:
            pass  # Preparation remains valid for this running helper.

    def restore_prepared_state(self):
        if self.prepared and self.prepared_level == self.settings.level:
            return True
        try:
            marker = json.loads(self.prepared_state_path.read_text())
            expected = {
                "character": self.settings.character,
                "server": self.settings.server,
                "game_dir": self.settings.game_dir,
                "session": self.gate.game_session(),
            }
            if any(marker.get(key) != value for key, value in expected.items()) or expected["session"] is None:
                return False
            prepared_level = marker.get("level")
            if type(prepared_level) is not int or not 1 <= prepared_level <= self.settings.level:
                return False
            export = Path(self.settings.game_dir) / "eql-rotation-spellbook.txt"
            known = self.catalog.parse_book(export.read_text(errors="replace"))
            # A level-up does not erase memorized gems. Restore the exact old
            # profile in the same live session, without assuming new upgrades.
            profile = self.catalog.profile(prepared_level, known)
            if "quick_heal" not in profile or "nuke" not in profile:
                return False
            if marker.get("spell_ids") != sorted(spell.id for spell in profile.values()):
                # Older valid bars left gem 2 unused. Restore those exact gems
                # for immediate healing; F6 adds the new optional HP/AC buff.
                without_armor = {role: spell for role, spell in profile.items() if role != "armor"}
                if marker.get("spell_ids") != sorted(spell.id for spell in without_armor.values()):
                    return False
                profile = without_armor
            self.known, self.profile = known, profile
            self.prepared = True
            self.prepared_level = self.settings.level
            self.rotation = self.make_rotation(profile)
            self.status = "Prepared spell bar restored for this live EQ session. Select an enemy and press F8."
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

    def prepare(self):
        if not self.gate.controls_ready():
            self.emit("Enter the game, focus its window, and press F6 to prepare.")
            return
        self.active = False
        self.preparing = True
        self.cancelled = False
        self.prepared = False
        try:
            self.emit("Preparing: export your learned spellbook…")
            export = Path(self.settings.game_dir) / "eql-rotation-spellbook.txt"
            previous = export.stat().st_mtime_ns if export.exists() else None
            self.send("/attack off")
            self.send("/outputfile spellbook eql-rotation-spellbook.txt")
            deadline = time.monotonic() + 6
            while not export.exists() or export.stat().st_mtime_ns == previous:
                if time.monotonic() > deadline:
                    raise RuntimeError("No fresh spellbook export. In EQ, run /outputfile spellbook eql-rotation-spellbook.txt and retry F6.")
                self.wait(0.10)
            self.wait(0.20)
            known = self.catalog.parse_book(export.read_text(errors="replace"))
            profile = self.catalog.profile(self.settings.level, known)
            if "quick_heal" not in profile or "nuke" not in profile:
                raise RuntimeError("The fresh spellbook did not contain a usable heal and damage spell for this level. Check your level and Paladin/Cleric loadout.")
            self.known, self.profile = known, profile
            # Never try to memorize the same ID in two slots.
            assert len({spell.id for spell in profile.values()}) == len(profile)
            for role, spell in sorted(profile.items(), key=lambda item: SLOTS[item[0]]):
                self.failed_mem = False
                self.emit(f"Preparing gem {SLOTS[role]}: {spell.name}. F9 cancels.")
                self.send(f"/memspellslot {SLOTS[role]} {spell.id}")
                # Legacy EQ memorization can scale with level. Be deliberately
                # conservative; this runs between fights, not inside combat.
                self.wait(4.0 + spell.level * 0.18)
                if self.failed_mem:
                    raise RuntimeError(f"EQ could not memorize {spell.name}. Scribe it and retry preparation.")
            self.prepared = True
            self.prepared_level = self.settings.level
            self.rotation = self.make_rotation(profile)
            self.save_prepared_state()
            self.emit("Spell bar ready. Select an enemy, then press F8. F10 requests a heal.")
        except (InterruptedError, OSError, ValueError, RuntimeError) as exc:
            self.emit(str(exc))
        finally:
            self.preparing = False
            self.cancelled = False
            self.emit()

    def handle_job(self, name, value):
        self.trace("job", name=name, value=value,
                   generation=self.cancel_generation, held=sorted(self.keys))
        if name in {"arm", "prepare", "heal", "attack_off"} and isinstance(value, int) and value != self.cancel_generation:
            return  # A later stop/chat/focus event invalidated this key release.
        if name in {"arm", "prepare", "heal", "attack_off"} and self.sender and self.sender.unfinished:
            self.emit("A command was interrupted. Press Escape in the game to clear its draft, then retry F6/F8.")
            return
        if name == "stop":
            self.stop_action("Stopped.")
        elif name == "attack_off":
            self.native_attack_off_pending = True
            self.flush_native_attack_off()
        elif name == "quit":
            self.stopping = True
        elif name == "settings":
            if self.active or self.preparing:
                self.stop_action("Settings changed. Press F8 when ready.")
            old = self.settings
            self.settings = value
            identity_changed = (old.character, old.server) != (value.character, value.server)
            level_changed = old.level != value.level
            if level_changed or identity_changed:
                self.prepared_level = None
                self.prepared = False
                if identity_changed:
                    self.known = None
                self.profile = self.catalog.profile(value.level, self.known)
                self.rotation = None
                self.tail = self.make_tail()
                self.tail.poll()
            if self.rotation:
                self.rotation.mode = value.mode
                self.rotation.damage_interval = value.damage_interval
                self.rotation.smart_heal = value.smart_heal
                self.rotation.use_stuns = value.use_stuns
                self.rotation.use_bash = value.use_bash
            self.emit()
        elif name == "prepare_later":
            self.stop_action("Switch to your game within 4 seconds; spell preparation will then start.")
            self.deferred = "prepare"
            self.next_job_at = time.monotonic() + 4
        elif name == "capture":
            self.stop_action("Choose the inner colored part of your full gauge in the captured game image.")
            try:
                self.capture_ready(value, self.gate.capture())
            except Exception as exc:
                self.emit(str(exc))
        elif name == "prepare":
            self.prepare()
        elif name == "arm":
            if self.stop_keys_held():
                return
            if self.active:
                if self.target_ready is False:
                    self.target_ready = None
                    self.attack_started = False
                    self.native_attack_off_pending = True
                    self.next_target_probe = time.monotonic()
                    self.emit("Combat already ON · refreshing current target safety check · F9 stops")
                else:
                    self.emit("Combat already ON · select an enemy · F9 stops")
                return
            if not self.prepared or self.prepared_level != self.settings.level:
                if not self.restore_prepared_state():
                    self.emit("Prepare the spell bar first with the app button or F6; F8 only toggles combat.")
                    return
            self.cancelled = False
            self.active = True
            self.target_ready = None
            # Retain a real Targeted(NPC/PC) identity observed before F8;
            # /consider must still verify this target before any attack.
            self.attackers_seen.clear()
            self.attack_started = False
            self.native_attack_off_pending = True
            self.next_target_probe = time.monotonic()
            if not self.gate.controls_ready():
                self.emit("Combat ON · paused while EverQuest is unfocused · resumes when you return")
                return
            if self.blocked_keys():
                self.emit("Combat ON · paused while a movement or modifier key is held")
                return
            self.emit("Combat ON · waiting for a leveling mob; safety check runs before attack · F9 stops")
        elif name == "heal":
            if not self.prepared or not self.gate.controls_ready():
                self.emit("Prepare your bar with F6 before using F10.")
                return
            self.cancelled = False
            # Some EQ keymaps bind native F10 to auto-attack even though the
            # helper also grabs it. Force that side effect off before healing.
            self.native_attack_off_pending = True
            self.send("/attack off")
            self.native_attack_off_pending = False
            self.attack_started = False
            busy_until = time.monotonic() + self.profile["quick_heal"].busy_seconds
            self.command_pause_until = max(self.command_pause_until, busy_until)
            self.send("/cast 1")
            if self.rotation:
                self.rotation.busy_until = max(self.rotation.busy_until, busy_until)
            self.emit("Heal requested on the target's implied friendly target (normally you while solo tanking).")

    def make_tail(self):
        name = f"eqlog_{self.settings.character}_{self.settings.server}.txt"
        return LogTail(Path(self.settings.game_dir) / "Logs" / name)

    def perform_action(self, action):
        self.send(action.command)
        committed_at = time.monotonic()
        self.rotation.committed(action, committed_at)
        self.command_pause_until = max(
            self.command_pause_until, committed_at + action.busy_seconds)
        self.last_action_role = action.role
        self.trace("action", role=action.role, command=action.command,
                   hp=self.hp, mana=self.mana, target_ready=self.target_ready)
        self.emit(f"Combat ON · {action.role.replace('_', ' ')}")

    def combat_tick(self, now):
        """Self support is independent of the permission to attack a target."""
        if (not self.active or not self.rotation or now < self.command_pause_until
                or self.blocked_keys() or not self.gate.controls_ready()):
            return
        if self.native_attack_off_pending:
            self.flush_native_attack_off()
            return
        if self.target_ready is True and not self.attack_started:
            # Keep melee running alongside support for every verified mob.
            # Approval lasts until target change, refusal, death or stop.
            self.send("/attack on")
            self.attack_started = True
        if (self.target_ready is None and now >= self.rotation.busy_until
                and (self.hp is None or self.hp > .25)):
            # One short safety check must not be starved by repeated heals
            # or startup buffs. Critical healing still takes precedence.
            if self.probe_target(now):
                return
        if now < self.mana_blocked_until:
            # Mana exhaustion must never disable verified melee. Lay on Hands
            # is still available while mana-consuming casts wait to retry.
            emergency = self.rotation.choose(now, self.hp, 0.0, allow_offense=False)
            if emergency and emergency.role == "lay_hands":
                self.perform_action(emergency)
            return
        if (self.settings.auto_stance and self.settings.stance_keys_verified
                and now >= self.rotation.busy_until):
            role = self.stances.choose(now, self.hp)
            if role:
                self.pump()
                if self.sender is None:
                    self.sender = KeySender(self.gate, self.allowed)
                self.sender.stance(role)
                self.stances.requested(role, time.monotonic())
                self.command_pause_until = time.monotonic() + .25
                self.trace("stance_requested", stance=role, hp=self.hp)
                self.emit(f"Combat ON · {role} requested")
                return
        support = self.rotation.choose(now, self.hp, self.mana, allow_offense=False)
        if support:
            self.perform_action(support)
            return
        if now < self.rotation.busy_until:
            return
        if self.target_ready is None:
            self.probe_target(now)
            return
        if self.target_ready is not True:
            return
        action = self.rotation.choose(now, self.hp, self.mana)
        if action:
            self.perform_action(action)

    def run(self):
        try:
            self.catalog = Catalog.load(Path(self.settings.game_dir))
            self.profile = self.catalog.profile(self.settings.level)
            self.gate = WindowGate()
            self.tail = self.make_tail()
            self.tail.poll()
            self.open_devices()
            if not self.selector.get_map():
                raise RuntimeError("No readable keyboard. The existing input-device permissions need to be restored.")
            self.restore_prepared_state()
            self.settings.stance_keys_verified = stance_bindings_match(Path(self.settings.game_dir))
            self.emit()
            while not self.stopping:
                now = time.monotonic()
                if now - self.last_grabs >= 0.5:
                    self.gate.refresh_grabs()
                    self.last_grabs = now
                if now - self.last_devices >= 5:
                    self.open_devices()
                    self.settings.stance_keys_verified = stance_bindings_match(Path(self.settings.game_dir))
                    self.last_devices = now
                self.pump()
                if self.deferred and now >= self.next_job_at:
                    self.jobs.put((self.deferred, None))
                    self.deferred = None
                while not self.jobs.empty():
                    name, value = self.jobs.get()
                    try:
                        self.handle_job(name, value)
                    except (InterruptedError, OSError, ValueError, RuntimeError) as exc:
                        self.handle_input_failure(exc)
                if self.command_recovery_pending:
                    try:
                        self.recover_interrupted_command()
                    except (InterruptedError, OSError, ValueError, RuntimeError) as exc:
                        self.handle_input_failure(exc)
                    time.sleep(0.025)
                    continue
                if now - self.last_gauge >= 0.5:
                    if self.active:
                        self.hp, self.mana = self.gate.read_gauges(self.settings.hp_region, self.settings.mana_region)
                    self.last_gauge = now
                    self.emit()
                try:
                    self.combat_tick(time.monotonic())
                except (InterruptedError, OSError, ValueError, RuntimeError) as exc:
                    self.handle_input_failure(exc)
                time.sleep(0.025)
        except Exception as exc:
            self.trace("fatal", exception=type(exc).__name__, message=str(exc))
            self.emit(f"Helper stopped: {type(exc).__name__}: {exc}")
        finally:
            self.trace("engine_exit", active=self.active,
                       sender_unfinished=bool(self.sender and self.sender.unfinished))
            self.active = False
            if self.sender:
                self.sender.close()
            for key in list(self.selector.get_map().values()):
                key.fileobj.close()
            self.selector.close()
            if self.gate:
                self.gate.close()
