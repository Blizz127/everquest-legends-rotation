from pathlib import Path
import json
import time
from types import SimpleNamespace

import pytest

from rotation_core import (Catalog, Spell, Rotation, Settings, LogTail,
                           bar_fraction, level_from_message, StancePlan, stance_bindings_match)
from rotation_engine import (Engine, KeySender, WindowGate, consider_target,
                             game_identity, safe_leveling_target)
from install_leveling_maps import (LEVELING_SPOTS, PACK_NAME, install_pack,
                                   render_overlays)


def spell(id, name, clr, pal=255, cast=1500, mana=10, duration=0):
    return Spell(id, name, clr, pal, cast, 1500, 1500, mana, duration, 51)


def test_primary_leveling_route_covers_every_level():
    covered = {
        level
        for spot in LEVELING_SPOTS
        if spot.primary
        for level in range(spot.minimum, spot.maximum + 1)
    }
    assert covered == set(range(1, 51))


def test_leveling_overlays_use_valid_eq_map_points(tmp_path):
    overlays = render_overlays(tmp_path)
    assert overlays
    for path in overlays:
        assert path.name.endswith("_3.txt")
        for line in path.read_text().splitlines():
            fields = [field.strip() for field in line.removeprefix("P ").split(",")]
            assert line.startswith("P ")
            assert len(fields) == 8
            assert fields[3:7] == ["0", "255", "127", "3"]
            assert fields[7].startswith("L")


def test_leveling_map_install_creates_separate_complete_pack(tmp_path):
    stock = tmp_path / "maps"
    stock.mkdir()
    (stock / "butcher.txt").write_text("L 0, 0, 0, 1, 1, 1, 255, 255, 255\n")
    (stock / "unrelated.txt").write_text("P 0, 0, 0, 1, 2, 3, 2, Stock\n")
    result = install_pack(stock)

    target = stock / PACK_NAME
    assert result == target
    assert (target / "butcher.txt").read_text() == (stock / "butcher.txt").read_text()
    assert (target / "unrelated.txt").exists()
    assert (target / "butcher_3.txt").read_text().startswith("P ")
    assert not (stock / "butcher_3.txt").exists()


@pytest.fixture
def catalog():
    return Catalog([
        spell(200, "Minor Healing", 1, 1), spell(14, "Strike", 1, 1),
        spell(17, "Light Healing", 4, 10), spell(12, "Healing", 10, 20),
        spell(15, "Greater Healing", 20, 30), spell(9, "Superior Healing", 30, 46),
        spell(74001, "Echo of Health", 8), spell(74002, "Echoing Light", 14),
        spell(74003, "Renewing Echo", 24), spell(74004, "Celestial Echo", 34),
        spell(74005, "Sacred Echo", 43), spell(560, "Furor", 5, 8),
        spell(16, "Smite", 14, 19), spell(329, "Wrath", 29, 34),
        spell(672, "Retribution", 44, 49), spell(218, "Ward Undead", 4, 1),
        spell(233, "Expulse Undead", 13, 30), spell(117, "Dismiss Undead", 23, 46),
        spell(662, "Expel Undead", 33, 54), spell(118, "Banish Undead", 43),
        spell(210, "Yaulp", 1, 9), spell(43, "Yaulp II", 16, 38),
        spell(44, "Yaulp III", 41, 56), spell(2583, "Instrument of Nife", 255, 15),
        spell(693, "Divine Might", 255, 45), spell(2581, "Cease", 255, 7),
        spell(2582, "Desist", 255, 13), spell(216, "Stun", 2, 28),
        spell(123, "Holy Might", 16, 42), spell(124, "Force", 31, 52),
        spell(2502, "Celestial Remedy", 19, duration=4),
    ])


def test_progression_respects_levels_and_only_learned_spells(catalog):
    for level in range(1, 51):
        profile = catalog.profile(level)
        assert all(s.level <= level for s in profile.values())
        assert len({s.id for s in profile.values()}) == len(profile)
    assert catalog.profile(1)["quick_heal"].name == "Minor Healing"
    assert "heal" not in catalog.profile(1)
    assert catalog.profile(8)["quick_heal"].name == "Echo of Health"
    assert catalog.profile(20)["heal"].name == "Greater Healing"
    assert catalog.profile(30)["heal"].name == "Superior Healing"
    assert catalog.profile(44)["nuke"].name == "Retribution"
    profile = catalog.profile(50, {200, 14})
    assert {s.id for s in profile.values()} == {200, 14}
    assert catalog.profile(50, set()) == {}


def test_stun_does_not_downgrade_to_later_shorter_paladin_spell(catalog):
    assert catalog.profile(13)["stun"].name == "Stun"
    assert catalog.profile(16)["stun"].name == "Holy Might"


def test_book_names_not_arbitrary_numeric_columns(catalog):
    known = catalog.parse_book("1\t200\tMinor Healing\n5\tFuror\n16\tYaulp II\n14\tUnknown Spell\n")
    assert known == {200, 560, 43}
    assert 14 not in known
    assert catalog.resolve_name("Minor Healing III").id == 200
    assert catalog.resolve_name("Yaulp II").id == 43


def test_client_schema_and_npc_duplicate_filter(tmp_path):
    def row(id, name, cleric, paladin, cast=1500):
        f = ["0"] * 174
        f[0], f[1], f[8], f[9], f[10] = str(id), name, str(cast), "1500", "1500"
        f[37], f[38] = str(cleric), str(paladin)
        return "^".join(f)
    p = tmp_path / "spells_us.txt"
    p.write_text("\n".join([row(200, "Minor Healing", 1, 1), row(14, "Strike", 1, 1),
                             row(999, "Strike", 254, 255)]))
    result = Catalog.load(tmp_path)
    assert result.by_name["strike"].id == 14
    p.write_text(row(200, "Different Layout", 1, 1))
    with pytest.raises(ValueError, match="sanity check"):
        Catalog.load(tmp_path)


def test_health_priority_then_cooldown_fallback(catalog):
    r = Rotation(catalog.profile(30), 30)
    emergency = r.choose(1000, .20, .90)
    assert emergency.role == "lay_hands"
    r.committed(emergency, 1000)
    assert r.choose(1000.1, .20, .90) is None
    assert r.choose(1001, .20, .90).role == "quick_heal"
    old = r.loh_ready_at
    r.landed_smite()
    assert r.loh_ready_at == old - 60


@pytest.mark.parametrize("target_ready", [None, False, True])
def test_noncritical_target_probe_precedes_healing_and_verified_melee_stays_on(catalog, target_ready):
    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(controls_ready=lambda: True)
    engine.blocked_keys = lambda: False
    engine.send = sent.append
    engine.profile = catalog.profile(4)
    engine.rotation = Rotation(engine.profile, 4)
    engine.active = True
    engine.hp, engine.mana = .40, .80
    engine.target_ready = target_ready
    engine.combat_tick(time.monotonic())
    assert sent == (["/attack on", "/cast 1"] if target_ready is True else
                    ["/consider"] if target_ready is None else ["/cast 1"])
    assert engine.attack_started is (target_ready is True)
    assert not engine.probe_target(time.monotonic())


@pytest.mark.parametrize("target_ready", [None, False])
def test_waiting_or_protected_target_permits_buffs_but_never_damage(catalog, target_ready):
    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(controls_ready=lambda: True)
    engine.blocked_keys = lambda: False
    engine.send = sent.append
    engine.profile = catalog.profile(4)
    engine.rotation = Rotation(engine.profile, 4)
    engine.active = True
    engine.hp, engine.mana = .95, .80
    engine.target_ready = target_ready
    engine.combat_tick(time.monotonic())
    assert sent == (["/consider"] if target_ready is None else ["/cast 7"])
    engine.rotation.busy_until = 0
    engine.command_pause_until = 0
    engine.combat_tick(time.monotonic())
    assert all(command in {"/cast 7", "/consider"} for command in sent)
    assert not engine.attack_started


@pytest.mark.parametrize("blocked,focused,active", [(True, True, True), (False, False, True), (False, True, False)])
def test_self_support_obeys_input_and_stop_gates(catalog, blocked, focused, active):
    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(controls_ready=lambda: focused)
    engine.blocked_keys = lambda: blocked
    engine.send = sent.append
    engine.rotation = Rotation(catalog.profile(4), 4)
    engine.active = active
    engine.hp, engine.mana = .40, .80
    engine.combat_tick(time.monotonic())
    assert sent == []


def test_courage_uses_vacant_large_heal_slot_without_displacing_heals(catalog):
    c = Catalog(list(catalog.spells.values()) + [spell(202, "Courage", 1, duration=270)])
    profile = c.profile(4, {14, 17, 202, 210})
    assert profile["armor"].name == "Courage"
    assert profile["quick_heal"].name == "Light Healing"
    assert "heal" not in profile
    assert "armor" not in c.profile(8)  # Echo + direct heal already use slots 1 and 2.


def test_timed_buff_refreshes_after_expiry():
    r = Rotation({"proc": spell(2583, "Instrument of Nife", 255, 15, duration=10)}, 15)
    buff = r.choose(1000, .95, .8, allow_offense=False)
    r.committed(buff, 1000)
    assert r.choose(1010, .95, .8, allow_offense=False) is None
    assert r.choose(1061, .95, .8, allow_offense=False).role == "proc"


def test_heal_cooldown_never_starts_a_buff_or_damage_at_low_hp(catalog):
    r = Rotation(catalog.profile(4), 4)
    heal = r.choose(1000, .4, .8)
    r.committed(heal, 1000)
    r.busy_until = 0
    assert r.choose(1001, .4, .8) is None


def test_failed_buff_is_retried_and_faded_buff_is_reapplied(catalog):
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.profile = catalog.profile(4)
    engine.rotation = Rotation(engine.profile, 4)
    engine.rotation.last["yaulp"] = time.monotonic()
    engine.last_action_role = "yaulp"
    engine.tail = SimpleNamespace(poll=lambda: ["Your spell fizzles!"])
    engine.read_log()
    assert "yaulp" not in engine.rotation.last
    engine.rotation.last["yaulp"] = time.monotonic()
    engine.tail = SimpleNamespace(poll=lambda: ["Your Yaulp spell has worn off."])
    engine.read_log()
    assert "yaulp" not in engine.rotation.last


@pytest.mark.parametrize("line", ["Your Light Healing spell fizzles!", "Your Light Healing spell is interrupted."])
def test_named_failed_heal_is_retried_without_full_cast_cooldown(catalog, line):
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.profile = catalog.profile(4)
    engine.rotation = Rotation(engine.profile, 4)
    engine.rotation.last["quick_heal"] = time.monotonic()
    engine.last_action_role = "quick_heal"
    engine.tail = SimpleNamespace(poll=lambda: [line])
    engine.read_log()
    assert "quick_heal" not in engine.rotation.last
    assert engine.command_pause_until < time.monotonic() + 2


def test_solo_stance_reduces_damage_at_low_hp_and_avoids_flapping():
    plan = StancePlan()
    assert plan.choose(100, .45) == "defensive"
    plan.requested("defensive", 100)
    assert plan.choose(101, .45) == "divine"
    plan.requested("divine", 101)
    assert plan.choose(110, .75) is None
    assert plan.choose(111, .90) == "balanced"
    plan.requested("balanced", 111)
    assert plan.choose(112, .40) is None  # Native six-second switch cooldown.
    assert plan.choose(118, .40) == "defensive"


def test_native_stance_bindings_must_match_and_not_trigger_another_action(tmp_path):
    ini = tmp_path / "eqclient.ini"
    correct = ("[KeyMaps]\nKEYMAPPING_CMD_Balanced_Stance_1=1610612738\n"
               "KEYMAPPING_CMD_Defensive_Stance_1=1610612739\n"
               "KEYMAPPING_CMD_Divine_Invocation_1=1610612740\n")
    ini.write_text(correct)
    assert stance_bindings_match(tmp_path)
    ini.write_text(correct + "KEYMAPPING_ATTACK_1=1610612739\n")
    assert not stance_bindings_match(tmp_path)
    ini.write_text(correct.replace("1610612739", "1610612796"))
    assert not stance_bindings_match(tmp_path)


def test_unconfigured_stance_keys_never_send_a_guess(catalog):
    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(controls_ready=lambda: True)
    engine.blocked_keys = lambda: False
    engine.send = sent.append
    engine.profile = catalog.profile(4)
    engine.rotation = Rotation(engine.profile, 4)
    engine.active = True
    engine.target_ready = False
    engine.hp, engine.mana = .4, .8
    engine.combat_tick(time.monotonic())
    assert sent == ["/cast 1"]


def test_stance_key_chord_releases_modifiers_when_focus_is_lost():
    from evdev import ecodes as e
    sender = KeySender.__new__(KeySender)
    sender.codes = e
    sender.held = set()
    events = []
    sender.ui = SimpleNamespace(write=lambda *event: events.append(event), syn=lambda: None)
    checks = iter([True, False])
    def check():
        if not next(checks):
            raise InterruptedError("Focus lost")
    sender.check = check
    with pytest.raises(InterruptedError):
        sender.stance("defensive")
    assert sender.held == set()
    assert events[-1] == (e.EV_KEY, e.KEY_LEFTCTRL, 0)
    assert not any(code == e.KEY_2 for _, code, _ in events)


def test_verified_stance_keys_do_not_prevent_healing_or_attack_protected_target(catalog):
    events = []
    engine = Engine(Settings(level=4, stance_keys_verified=True), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(controls_ready=lambda: True)
    engine.blocked_keys = lambda: False
    engine.pump = lambda: None
    engine.sender = SimpleNamespace(stance=lambda role: events.append(role))
    engine.send = events.append
    engine.rotation = Rotation(catalog.profile(4), 4)
    engine.active = True
    engine.hp, engine.mana = .4, .8
    engine.target_ready = False
    engine.combat_tick(time.monotonic())
    assert events == ["defensive"]
    engine.command_pause_until = 0
    engine.combat_tick(time.monotonic())
    assert events == ["defensive", "divine"]
    engine.command_pause_until = 0
    engine.combat_tick(time.monotonic())
    assert events == ["defensive", "divine", "/cast 1"]
    assert not engine.attack_started


def test_unknown_health_never_fabricates_a_heal(catalog):
    r = Rotation(catalog.profile(30), 30)
    for now in range(1000, 1120):
        action = r.choose(now, None, .8)
        if action:
            assert action.role not in {"lay_hands", "quick_heal", "heal", "hot"}
            r.committed(action, now)


def test_low_mana_keeps_opted_in_bash_and_no_spells(catalog):
    r = Rotation(catalog.profile(30), 30, use_bash=True)
    action = r.choose(1000, .95, .10)
    assert action.role == "bash"
    r.committed(action, 1000)
    assert r.choose(1001, .95, .10) is None


def test_bash_is_disabled_by_default_without_a_shield(catalog):
    r = Rotation(catalog.profile(30), 30)
    assert r.choose(1000, .95, .10) is None


def test_undead_mode_and_smite_ability_are_distinct(catalog):
    r = Rotation(catalog.profile(14), 14, mode="undead")
    r.last.update(yaulp=1000, proc=1000, bash=1000)
    assert r.choose(1000, None, .90).command == "/doability Smite"
    r.last["smite_ability"] = 1000
    assert r.choose(1001, None, .90).command == "/cast 4"
    assert catalog.profile(14)["nuke"].id == 16  # The separate Smite spell.


def test_buffs_once_not_on_every_damage_pass(catalog):
    r = Rotation(catalog.profile(20), 20)
    first = r.choose(1000, None, .90)
    assert first.role == "yaulp"
    r.committed(first, 1000)
    second = r.choose(1005, None, .90)
    assert second.role == "proc"
    r.committed(second, 1005)
    assert r.choose(2000, None, .90).role not in {"yaulp", "proc"}


def test_level_message_cannot_be_spoofed_by_other_players_chat():
    assert level_from_message("[Sat Oct 17 20:00:00 2026] You have gained a level! Welcome to level 9!") == 9
    assert level_from_message("You have gained 2 levels! Welcome to level 12!") == 12
    assert level_from_message("Bob tells you, 'You have gained a level! Welcome to level 50!'") is None
    assert level_from_message("You have gained a level! Welcome to level 60!") is None


def test_log_tail_ignores_history_handles_partial_and_truncation(tmp_path):
    path = tmp_path / "game.log"
    path.write_text("old message\n")
    tail = LogTail(path)
    assert tail.poll() == []
    with path.open("a") as target:
        target.write("You have gained a level!")
    assert tail.poll() == []
    with path.open("a") as target:
        target.write(" Welcome to level 9!\n")
    assert level_from_message(tail.poll()[0]) == 9
    path.write_text("new\n")
    assert tail.poll() == ["new"]


def test_gauge_reader_full_half_noisy_wrong_color():
    from PIL import Image
    full = Image.new("RGB", (100, 8), (200, 20, 20))
    assert bar_fraction(full, "red") == 1
    half = Image.new("RGB", (100, 8), (20, 20, 20))
    half.paste((200, 20, 20), (0, 0, 50, 8))
    assert bar_fraction(half, "red") == .5
    assert bar_fraction(half, "blue") is None
    wrong = Image.new("RGB", (100, 8), (20, 20, 20))
    wrong.paste((200, 20, 20), (80, 0, 100, 8))
    assert bar_fraction(wrong, "red") is None
    assert bar_fraction(Image.new("RGB", (100, 8), "black"), "red") is None


def test_settings_atomic_roundtrip_and_clamp(tmp_path):
    p = tmp_path / "settings.json"
    value = Settings(level=30, character="Blizz")
    value.save(p)
    assert Settings.load(p).character == "Blizz"
    assert not p.with_suffix(".tmp").exists()
    p.write_text(json.dumps({"level": 999, "damage_interval": .01, "unknown": "ignored"}))
    actual = Settings.load(p)
    assert actual.level == 50 and actual.damage_interval == 4


def test_window_gate_rejects_browser_launcher_and_lookalike_title():
    assert game_identity(("eqgame.exe", "eqgame.exe"), "EverQuest Legends")
    assert game_identity(("Wine",), "EverQuest Legends", "C:\\Games\\eqgame.exe\0")
    assert not game_identity(("firefox",), "EverQuest Legends")
    assert not game_identity(("LaunchPad.exe",), "EverQuest Legends")
    assert not game_identity(("dolphin",), "EverQuest Legends", "dolphin\0/path/eqgame.exe\0")


def test_window_gate_uses_actual_x_input_focus_when_kwin_active_window_is_proxy():
    game = SimpleNamespace(id=0x7800001)
    proxy = SimpleNamespace(id=0x200000)

    class Root:
        def get_full_property(self, *_):
            return SimpleNamespace(value=[proxy.id])

    class Display:
        def intern_atom(self, *_):
            return 1

        def create_resource_object(self, _, window_id):
            assert window_id == proxy.id
            return proxy

        def get_input_focus(self):
            return SimpleNamespace(focus=game)

    gate = WindowGate.__new__(WindowGate)
    gate.display = Display()
    gate.root = Root()
    gate.X = SimpleNamespace(AnyPropertyType=0)
    gate.identity = lambda window: window is game

    assert gate.focused_window() is game


def test_panic_invalidates_queued_start_and_delayed_preparation():
    states = []
    engine = Engine(Settings(), states.append, lambda *_: None)
    generation = engine.cancel_generation
    engine.deferred = "prepare"
    engine.stop_action("panic")
    engine.handle_job("arm", generation)
    assert not engine.active
    assert engine.deferred is None
    assert engine.cancelled


def test_duplicate_hotkey_release_from_multiple_input_devices_is_debounced():
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    assert engine.accept_hotkey(66, 100.0)
    assert not engine.accept_hotkey(66, 100.01)
    assert engine.accept_hotkey(66, 100.40)


def test_escape_clears_target_without_disarming_but_chat_and_f9_stop():
    from evdev import ecodes as e

    class Device:
        def __init__(self, code):
            self.code = code

        def read(self):
            return [SimpleNamespace(type=e.EV_KEY, code=self.code, value=1)]

    class Selector:
        def __init__(self, code):
            self.device = Device(code)

        def select(self, timeout=0):
            return [(SimpleNamespace(fileobj=self.device), None)]

    escape = Engine(Settings(), lambda *_: None, lambda *_: None)
    escape.selector = Selector(e.KEY_ESC)
    escape.active = True
    escape.input_events()
    assert escape.active

    for code in (e.KEY_ENTER, e.KEY_SLASH, e.KEY_F9):
        stopped = Engine(Settings(), lambda *_: None, lambda *_: None)
        stopped.selector = Selector(code)
        stopped.active = True
        stopped.input_events()
        assert not stopped.active


@pytest.mark.parametrize("code", [1, 28, 53, 96])  # Escape, Enter, slash, keypad Enter.
def test_typing_in_another_app_does_not_disarm_combat(code):
    from evdev import ecodes as e
    device = SimpleNamespace(read=lambda: [SimpleNamespace(type=e.EV_KEY, code=code, value=1)])
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(focused=lambda: False)
    engine.selector = SimpleNamespace(select=lambda timeout=0: [(SimpleNamespace(fileobj=device), None)])
    engine.active = True
    engine.target_ready = True
    engine.input_events()
    assert engine.active
    assert engine.target_ready is True


@pytest.mark.parametrize("enter", [28, 96])
def test_alt_enter_window_shortcut_does_not_stop_combat(enter):
    from evdev import ecodes as e
    device = SimpleNamespace(read=lambda: [
        SimpleNamespace(type=e.EV_KEY, code=e.KEY_LEFTALT, value=1),
        SimpleNamespace(type=e.EV_KEY, code=enter, value=1)])
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(focused=lambda: True)
    engine.selector = SimpleNamespace(select=lambda timeout=0: [(SimpleNamespace(fileobj=device), None)])
    engine.active, engine.target_ready, engine.attack_started = True, True, True
    engine.input_events()
    assert engine.active and engine.target_ready and engine.attack_started
    assert not engine.native_attack_off_pending


def test_input_pause_before_command_starts_preserves_verified_melee():
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.active, engine.target_ready, engine.attack_started = True, True, True
    engine.sender = SimpleNamespace(unfinished=False)
    assert engine.handle_input_failure(InterruptedError("Movement held"))
    assert engine.active and engine.target_ready and engine.attack_started
    assert not engine.native_attack_off_pending


def test_critical_healing_still_precedes_unverified_target_probe(catalog):
    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(controls_ready=lambda: True)
    engine.blocked_keys = lambda: False
    engine.send = sent.append
    engine.rotation = Rotation(catalog.profile(4), 4)
    engine.active, engine.target_ready = True, None
    engine.hp, engine.mana = .10, .80
    engine.combat_tick(time.monotonic())
    assert sent == ["/alt activate 6001"]


@pytest.mark.parametrize("hp, expected", [(.50, []), (.10, ["/alt activate 6001"])])
def test_insufficient_mana_keeps_melee_on_and_only_pauses_mana_spells(catalog, hp, expected):
    engine = Engine(Settings(level=6), lambda *_: None, lambda *_: None)
    engine.active, engine.target_ready, engine.attack_started = True, True, True
    engine.gate = SimpleNamespace(controls_ready=lambda: True)
    engine.blocked_keys = lambda: False
    engine.rotation = Rotation(catalog.profile(4), 6)
    engine.hp, engine.mana = hp, None
    engine.tail = SimpleNamespace(poll=lambda: ["Insufficient Mana to cast this spell!"])
    engine.read_log()
    assert engine.active and engine.attack_started
    assert not engine.native_attack_off_pending
    sent = []
    engine.send = sent.append
    engine.combat_tick(time.monotonic())
    assert sent == expected


def test_escape_during_helper_command_keeps_combat_armed():
    from evdev import ecodes as e
    device = SimpleNamespace(read=lambda: [SimpleNamespace(type=e.EV_KEY, code=e.KEY_ESC, value=1)])
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(focused=lambda: True)
    engine.selector = SimpleNamespace(select=lambda timeout=0: [(SimpleNamespace(fileobj=device), None)])
    engine.sender = SimpleNamespace(unfinished=True)
    engine.active = True
    engine.attackers_seen.add("orc runner")
    engine.input_events()
    assert engine.active and not engine.cancelled
    assert not engine.sender.unfinished
    assert engine.native_attack_off_pending
    assert not engine.attackers_seen


def test_focus_loss_pauses_armed_combat_and_resumes_without_f8():
    class Gate:
        is_focused = False

        def focused(self):
            return self.is_focused

    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.gate = Gate()
    engine.input_events = lambda: None
    engine.read_log = lambda: None
    engine.active = True
    engine.target_ready = False
    engine.focused = True

    engine.pump()
    assert engine.active
    assert "paused" in engine.status.casefold()

    engine.gate.is_focused = True
    engine.pump()
    assert engine.active
    assert "waiting" in engine.status.casefold()


def test_mid_command_focus_loss_keeps_combat_armed_for_safe_recovery():
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.active = True
    engine.attack_started = True
    engine.sender = SimpleNamespace(unfinished=True)

    engine.handle_input_failure(
        InterruptedError("Input stopped: game lost focus, chat opened, or stop was pressed."))

    assert engine.active
    assert not engine.attack_started
    assert engine.native_attack_off_pending
    assert engine.command_recovery_pending
    assert "paused" in engine.status.casefold()


def test_interrupted_command_draft_is_cleared_before_combat_resumes():
    class Gate:
        @staticmethod
        def controls_ready():
            return True

    class Sender:
        unfinished = True
        cancelled = False

        def cancel_unfinished(self):
            self.cancelled = True
            self.unfinished = False
            return True

    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.gate = Gate()
    engine.sender = Sender()
    engine.blocked_keys = lambda: False
    engine.active = True
    engine.target_ready = True
    engine.attack_started = True
    engine.native_attack_off_pending = True
    engine.command_recovery_pending = True

    assert engine.recover_interrupted_command()

    assert engine.active
    assert engine.sender.cancelled
    assert not engine.sender.unfinished
    assert not engine.command_recovery_pending
    assert engine.target_ready is None
    assert not engine.attack_started
    assert engine.native_attack_off_pending
    assert "waiting" in engine.status.casefold()


def test_f8_never_starts_spell_preparation_when_bar_is_not_ready():
    class Gate:
        def controls_ready(self):
            return True

    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.gate = Gate()
    engine.blocked_keys = lambda: False
    engine.restore_prepared_state = lambda: False
    preparation_calls = []
    engine.prepare = lambda: preparation_calls.append(True)

    engine.handle_job("arm", None)

    assert preparation_calls == []
    assert "Prepare" in engine.status
    assert not engine.active


def test_level_setting_refreshes_unconfirmed_spell_preview(catalog):
    states = []
    engine = Engine(Settings(level=1), states.append, lambda *_: None)
    engine.catalog = catalog
    engine.profile = catalog.profile(1)

    engine.handle_job("settings", Settings(level=4))

    assert engine.profile["quick_heal"].name == "Light Healing"
    assert states[-1]["level"] == 4
    assert states[-1]["profile"]["quick_heal"].name == "Light Healing"


def test_prepared_bar_restores_only_for_same_live_game_session(catalog, tmp_path):
    book = tmp_path / "eql-rotation-spellbook.txt"
    book.write_text("Light Healing\nStrike\nWard Undead\nYaulp\n")
    settings = Settings(game_dir=str(tmp_path), character="Legira", server="freeport", level=4)

    class Gate:
        session = {"pid": 1234, "start_ticks": "5678"}

        def game_session(self):
            return self.session

    first = Engine(settings, lambda *_: None, lambda *_: None)
    first.catalog = catalog
    first.gate = Gate()
    first.prepared_state_path = tmp_path / "prepared.json"
    first.known = catalog.parse_book(book.read_text())
    first.profile = catalog.profile(4, first.known)
    first.prepared = True
    first.prepared_level = 4
    first.save_prepared_state()

    restored = Engine(settings, lambda *_: None, lambda *_: None)
    restored.catalog = catalog
    restored.gate = Gate()
    restored.prepared_state_path = first.prepared_state_path
    assert restored.restore_prepared_state()
    assert restored.prepared and restored.prepared_level == 4
    assert restored.profile["quick_heal"].name == "Light Healing"
    assert restored.rotation is not None

    settings.level = 6
    restored.prepared = False
    assert restored.restore_prepared_state()
    assert restored.prepared_level == 6
    assert restored.profile == first.profile  # Retain actual gems; do not assume upgrades were loaded.
    settings.level = 3
    restored.prepared = False
    assert not restored.restore_prepared_state()
    settings.level = 4

    restored.prepared = False
    restored.gate.session = {"pid": 1234, "start_ticks": "different"}
    assert not restored.restore_prepared_state()


def test_existing_prepared_bar_survives_new_optional_buff_without_casting_unloaded_gem(catalog, tmp_path):
    book = tmp_path / "eql-rotation-spellbook.txt"
    book.write_text("Light Healing\nStrike\nWard Undead\nYaulp\nCourage\n")
    settings = Settings(game_dir=str(tmp_path), level=4)
    engine = Engine(settings, lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(game_session=lambda: {"pid": 1234, "start_ticks": "5678"})
    engine.catalog = Catalog(list(catalog.spells.values()) + [spell(202, "Courage", 1, duration=270)])
    engine.prepared_state_path = tmp_path / "prepared.json"
    engine.profile = catalog.profile(4, catalog.parse_book(book.read_text()))
    engine.save_prepared_state()
    engine.profile = {}
    assert engine.restore_prepared_state()
    assert "armor" not in engine.profile
    assert engine.profile["quick_heal"].name == "Light Healing"


def test_kill_keeps_rotation_armed_for_next_manual_target(catalog):
    class Tail:
        def poll(self):
            return ["You have slain a skeleton!"]

    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.tail = Tail()
    engine.rotation = Rotation(catalog.profile(20), 20)
    engine.rotation.last.update(yaulp=123, proc=456)
    engine.active = True
    engine.attack_started = True

    engine.read_log()

    assert engine.active
    assert engine.target_ready is False
    assert not engine.attack_started
    assert engine.native_attack_off_pending
    assert engine.rotation.last["yaulp"] == 123
    assert engine.rotation.last["proc"] == 456
    assert "waiting" in engine.status.casefold()


def test_death_stops_rotation_and_resets_combat_buffs(catalog):
    class Tail:
        def poll(self):
            return ["You have been slain by a skeleton!"]

    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.tail = Tail()
    engine.rotation = Rotation(catalog.profile(20), 20)
    engine.rotation.last.update(yaulp=123, proc=456)
    engine.active = True
    engine.attack_started = True

    engine.read_log()

    assert not engine.active
    assert not engine.attack_started
    assert "yaulp" not in engine.rotation.last and "proc" not in engine.rotation.last


def test_stop_can_turn_off_native_attack_without_rearming():
    class Gate:
        def controls_ready(self):
            return True
    sent = []
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.gate = Gate()
    engine.blocked_keys = lambda: False
    engine.send = sent.append
    engine.stop_action("stopped")
    engine.handle_job("attack_off", engine.cancel_generation)
    assert sent == ["/attack off"]
    assert not engine.active and engine.cancelled


def test_f8_arms_persistently_while_waiting_for_manual_target():
    class Gate:
        def controls_ready(self):
            return True

    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = Gate()
    engine.blocked_keys = lambda: False
    engine.prepared = True
    engine.prepared_level = 4
    engine.send = sent.append
    engine.target_ready = None

    engine.handle_job("arm", None)

    assert sent == []
    assert engine.active
    assert not engine.attack_started
    assert "waiting" in engine.status.casefold()


def test_f8_can_arm_while_game_is_unfocused_and_waits_to_send():
    class Gate:
        def controls_ready(self):
            return False

    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = Gate()
    engine.blocked_keys = lambda: False
    engine.prepared = True
    engine.prepared_level = 4
    engine.send = sent.append

    engine.handle_job("arm", None)

    assert engine.active
    assert sent == []
    assert "paused" in engine.status.casefold()


def test_f8_arms_while_movement_key_is_held_and_waits_to_send():
    from evdev import ecodes as e

    class Gate:
        def controls_ready(self):
            return True

    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = Gate()
    engine.keys = {e.KEY_W}
    engine.prepared = True
    engine.prepared_level = 4
    engine.send = sent.append

    engine.handle_job("arm", None)

    assert engine.active
    assert sent == []
    assert "paused" in engine.status.casefold()


def test_repeated_f8_keeps_combat_on_instead_of_toggling_off():
    class Gate:
        def controls_ready(self):
            return True

    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = Gate()
    engine.blocked_keys = lambda: False
    engine.prepared = True
    engine.prepared_level = 4
    engine.send = sent.append
    engine.active = True
    engine.target_ready = None

    engine.handle_job("arm", None)

    assert engine.active
    assert sent == []
    assert "already on" in engine.status.casefold()


def test_armed_waiting_mode_considers_owner_selected_target_before_attack(catalog):
    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.profile = catalog.profile(4)
    engine.rotation = Rotation(engine.profile, 4)
    engine.send = sent.append
    engine.active = True
    engine.target_ready = None
    engine.next_target_probe = 0.0

    assert engine.probe_target(100.0)
    assert sent == ["/consider"]
    assert engine.target_ready is None
    assert not engine.attack_started
    assert engine.next_target_probe == 102.0
    assert not engine.probe_target(101.0)


def test_armed_waiting_with_confirmed_no_target_does_not_spam_consider(catalog):
    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.profile = catalog.profile(4)
    engine.rotation = Rotation(engine.profile, 4)
    engine.send = sent.append
    engine.active = True
    engine.target_ready = False
    engine.target_name = None
    engine.next_target_probe = 0.0

    assert not engine.probe_target(100.0)
    assert sent == []


def test_add_attacking_after_kill_wakes_one_safety_probe_without_selecting_or_attacking(catalog):
    lines = ["You have slain a goblin!", "You have slain a goblin whelp!",
             "A goblin whelp hits YOU for 3 points of damage."]
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.rotation = Rotation(catalog.profile(4), 4)
    engine.active = True
    engine.tail = SimpleNamespace(poll=lambda: lines)
    engine.read_log()
    assert engine.active and engine.target_ready is None
    sent = []
    engine.send = sent.append
    engine.command_pause_until = 0
    assert engine.probe_target(time.monotonic() + 1)
    assert sent == ["/consider"]
    engine.tail = SimpleNamespace(poll=lambda: ["Consider whom?", "A goblin whelp tries to hit YOU, but misses!"])
    engine.read_log()
    assert engine.target_ready is False
    assert not engine.probe_target(time.monotonic() + 10)
    assert sent == ["/consider"]


def test_incoming_guard_never_bypasses_safety_check():
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.active = True
    engine.target_ready = False
    engine.tail = SimpleNamespace(poll=lambda: ["Guard Dunn hits YOU for 50 points of damage."])
    engine.read_log()
    assert engine.target_ready is None
    engine.tail = SimpleNamespace(poll=lambda: ["Guard Dunn judges you amiably -- looks like quite a gamble. (Lvl: 40)"])
    engine.read_log()
    assert engine.target_ready is False
    assert not engine.attack_started


def test_chat_claiming_damage_does_not_wake_target_probe():
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.active = True
    engine.target_ready = False
    engine.tail = SimpleNamespace(poll=lambda: ["Bob tells General:2, 'A goblin hits YOU for 3 points of damage.'"])
    engine.read_log()
    assert engine.target_ready is False


def test_repeated_f8_requests_fresh_check_when_waiting():
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.active = True
    engine.target_ready = False
    engine.handle_job("arm", None)
    assert engine.active and engine.target_ready is None
    assert engine.native_attack_off_pending


def test_settings_trace_cannot_crash_engine(tmp_path):
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.trace_path = tmp_path / "runtime.jsonl"
    engine.trace("job", name="settings", value=Settings(level=4))
    record = json.loads(engine.trace_path.read_text())
    assert record["value"]["level"] == 4


@pytest.mark.parametrize("command", ["/attack on", "/cast 3", "/cast 4", "/cast 5", "/doability Bash", "/doability Smite"])
def test_target_change_while_pumping_prevents_stale_damage_command(command):
    sent = []
    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.active = True
    engine.target_ready = True
    engine.sender = SimpleNamespace(command=sent.append)
    engine.pump = lambda: setattr(engine, "target_ready", False)
    with pytest.raises(InterruptedError):
        engine.send(command)
    assert sent == []


def test_f10_suspends_target_probe_until_heal_cast_finishes(catalog):
    class Gate:
        def controls_ready(self):
            return True

    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = Gate()
    engine.profile = catalog.profile(4)
    engine.rotation = Rotation(engine.profile, 4)
    engine.prepared = True
    engine.prepared_level = 4
    engine.active = True
    engine.target_ready = None
    engine.next_target_probe = 0.0
    engine.send = sent.append

    engine.handle_job("heal", engine.cancel_generation)

    assert sent == ["/attack off", "/cast 1"]
    assert not engine.attack_started
    assert not engine.probe_target(time.monotonic())
    assert sent == ["/attack off", "/cast 1"]


def test_f8_requires_target_safety_check_without_mercenary_stance_command(catalog):
    class Gate:
        def controls_ready(self):
            return True

    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = Gate()
    engine.blocked_keys = lambda: False
    engine.prepared = True
    engine.prepared_level = 4
    engine.profile = catalog.profile(4)
    engine.rotation = Rotation(engine.profile, 4)
    engine.send = sent.append
    engine.target_ready = True

    engine.handle_job("arm", None)

    assert sent == []
    assert engine.active and not engine.attack_started
    assert engine.target_ready is None
    assert engine.native_attack_off_pending


def test_no_target_message_keeps_rotation_armed_and_retries_last_action(catalog):
    class Tail:
        def poll(self):
            return ["You must first select a target for this spell!"]

    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.tail = Tail()
    engine.rotation = Rotation(catalog.profile(4), 4)
    engine.rotation.last["yaulp"] = 1000
    engine.rotation.busy_until = 2000
    engine.last_action_role = "yaulp"
    engine.active = True
    engine.attack_started = True

    engine.read_log()

    assert engine.active
    assert engine.target_ready is False
    assert not engine.attack_started
    assert "yaulp" not in engine.rotation.last
    assert "waiting" in engine.status.casefold()


def test_manual_target_log_readies_armed_rotation(catalog):
    class Tail:
        def poll(self):
            return ["Targeted (NPC): a skeleton"]

    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.tail = Tail()
    engine.rotation = Rotation(catalog.profile(4), 4)
    engine.active = True
    engine.target_ready = False

    engine.read_log()

    assert engine.active
    assert engine.target_ready is None
    assert not engine.attack_started
    assert engine.native_attack_off_pending
    assert "checking" in engine.status.casefold()


def test_out_of_range_damage_retries_without_disarming(catalog):
    class Tail:
        def poll(self):
            return ["Your target is out of range, get closer!"]

    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.tail = Tail()
    engine.rotation = Rotation(catalog.profile(4), 4)
    engine.rotation.last["nuke"] = 1000
    engine.rotation.busy_until = 2000
    engine.last_action_role = "nuke"
    engine.active = True
    engine.target_ready = True
    before = time.monotonic()

    engine.read_log()

    assert engine.active
    assert engine.target_ready is True
    assert not engine.attack_started
    assert "nuke" not in engine.rotation.last
    assert before <= engine.rotation.busy_until <= before + 2
    assert "retry" in engine.status.casefold()


def test_consider_parser_and_conservative_mob_policy():
    body = "A bat regards you indifferently -- looks kind of risky, but you might win. (Lvl: 1)"
    assert consider_target(body) == ("A bat", "indifferent", 1)
    assert safe_leveling_target("A bat", "indifferent", "NPC")
    assert safe_leveling_target("Lord Grimrot", "scowls", "NPC")

    assert not safe_leveling_target("Guard Gabel", "scowls", "NPC")
    assert not safe_leveling_target("a city guard", "threatening", "NPC")
    assert not safe_leveling_target("Hanek Ogerbane", "indifferent", "Merchant")
    assert not safe_leveling_target("Hanek Ogerbane", "indifferent", "NPC")
    assert not safe_leveling_target("A bat", "amiable", "NPC")


def test_consider_policy_allows_mobs_regardless_of_level():
    body = "A giant scarab glowers at you dubiously -- looks like quite a gamble. (Lvl: 8)"
    name, reaction, target_level = consider_target(body)

    assert (name, reaction, target_level) == ("A giant scarab", "dubious", 8)
    assert safe_leveling_target(name, reaction, "NPC", target_level, player_level=4)
    assert safe_leveling_target("The Prophet", "scowls", "NPC", 19, player_level=4)
    assert safe_leveling_target("A large snake", "indifferent", "NPC", 5, player_level=4)


def test_hostile_orc_taskmaster_is_a_mob_without_an_article_or_targeted_log():
    body = "Orc taskmaster scowls at you, ready to attack -- what would you like your tombstone to say? (Lvl: 14)"
    name, reaction, level = consider_target(body)
    assert safe_leveling_target(name, reaction, None, level, 6)
    assert safe_leveling_target("Orc slaver", "scowls", "Unknown", 12, 6)
    assert not safe_leveling_target(name, reaction, "PC", level, 6)
    assert not safe_leveling_target("Orc guard", "scowls", None, 14, 6)
    assert not safe_leveling_target("Orc merchant", "scowls", None, 14, 6)
    assert not safe_leveling_target(name, "amiable", None, level, 6)
    assert not safe_leveling_target("Hanek Ogerbane", "scowls", None, 14, 6)

    engine = Engine(Settings(level=6), lambda *_: None, lambda *_: None)
    engine.active = True
    engine.tail = SimpleNamespace(poll=lambda: [body])
    engine.read_log()
    assert engine.target_ready is True


def test_approved_named_attacker_remains_allowed_after_incoming_hit_evidence_expires(monkeypatch):
    import rotation_engine
    clock = [100.0]
    monkeypatch.setattr(rotation_engine.time, "monotonic", lambda: clock[0])
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.active = True
    engine.target_name, engine.target_kind = "orc runner", "NPC"
    con = "Orc runner glowers at you dubiously -- looks like quite a gamble. (Lvl: 7)"
    engine.tail = SimpleNamespace(poll=lambda: [con])
    engine.read_log()
    assert engine.target_ready is False  # Named dubious NPC still needs attacker evidence.
    engine.tail = SimpleNamespace(poll=lambda: ["Orc runner slashes YOU for 11 points of damage.", con])
    engine.read_log()
    assert engine.target_ready is True
    assert engine.target_retaliation
    clock[0] = 120.0
    engine.tail = SimpleNamespace(poll=lambda: [con])
    engine.read_log()
    assert engine.target_ready is True


def test_any_level_mob_policy_still_blocks_guards_players_and_friendly_npcs():
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.active = True
    engine.tail = SimpleNamespace(poll=lambda: ["Orc runner slashes YOU for 11 points of damage.",
        "Targeted (NPC): a giant scarab", "A giant scarab glowers at you dubiously -- looks like quite a gamble. (Lvl: 7)"])
    engine.read_log()
    assert engine.target_ready is True
    assert not safe_leveling_target("Guard Dunn", "scowls", "NPC", 40, 4, retaliating=True)
    assert not safe_leveling_target("Orc runner", "scowls", "PC", 7, 4, retaliating=True)
    assert not safe_leveling_target("A friendly bat", "amiable", "NPC", 7, 4, retaliating=True)
    assert safe_leveling_target("A goblin", "scowls", "NPC", None, 4, retaliating=True)


def test_approved_mob_permission_does_not_expire_before_damage_is_sent():
    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.active = True
    engine.target_ready = True
    engine.target_name, engine.target_kind = "orc runner", "NPC"
    engine.target_retaliation = True
    engine.sender = SimpleNamespace(command=sent.append)
    engine.pump = lambda: None
    engine.send("/attack on")
    assert sent == ["/attack on"]


@pytest.mark.parametrize("retaliating", [False, True])
def test_verified_mob_starts_melee_even_when_healing_remains_top_spell_priority(catalog, retaliating):
    sent = []
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(controls_ready=lambda: True)
    engine.blocked_keys = lambda: False
    engine.send = sent.append
    engine.rotation = Rotation(catalog.profile(4), 4)
    engine.active = True
    engine.target_ready = True
    engine.target_retaliation = retaliating
    engine.target_name = "orc runner"
    engine.recent_attackers["orc runner"] = time.monotonic()
    engine.hp, engine.mana = .40, .80
    engine.combat_tick(time.monotonic())
    assert sent == ["/attack on", "/cast 1"]
    assert engine.attack_started


def test_command_whitelist_allows_consider_but_never_target_selection():
    sender = KeySender.__new__(KeySender)
    entered = []
    sender.codes = SimpleNamespace(KEY_ENTER="ENTER")
    sender.character = entered.append
    sender.tap = entered.append
    sender.unfinished = False

    sender.command("/consider")
    assert entered == list("/con") + ["ENTER"]
    assert not sender.unfinished
    with pytest.raises(ValueError, match="outside"):
        sender.command("/target Guard Gabel")


@pytest.mark.parametrize("command, expected_time", [("/consider", .12), ("/attack off", .30), ("/attack on", .26), ("/cast 1", .18)])
def test_command_typing_keeps_full_key_holds_without_idle_gaps(monkeypatch, command, expected_time):
    from evdev import ecodes as e
    clock = [0.0]
    events = []
    checks = []
    sender = KeySender.__new__(KeySender)
    sender.codes, sender.held, sender.unfinished = e, set(), False
    sender.check = lambda: checks.append(clock[0])
    sender.ui = SimpleNamespace(
        write=lambda kind, code, value: events.append((clock[0], code, value)),
        syn=lambda: None)
    monkeypatch.setattr("rotation_engine.time.sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))

    sender.command(command)

    previous_up = {}
    for down, up in zip(events[::2], events[1::2]):
        assert down[1] == up[1] and (down[2], up[2]) == (1, 0)
        assert up[0] - down[0] == pytest.approx(.020)
        if down[1] in previous_up:
            assert down[0] - previous_up[down[1]] >= .020 - 1e-9
        previous_up[up[1]] = up[0]
    assert len(checks) == len(events) // 2  # F9/focus checked before every key.
    assert not sender.held and not sender.unfinished
    assert clock[0] == pytest.approx(expected_time)


def test_fast_typing_stops_before_next_key_and_retains_draft_for_recovery(monkeypatch):
    from evdev import ecodes as e
    sender = KeySender.__new__(KeySender)
    sender.codes, sender.held, sender.unfinished = e, set(), False
    events = []
    allowed = [True]
    sender.allowed = lambda: allowed[0]
    sender.gate = SimpleNamespace(controls_ready=lambda: True)
    sender.ui = SimpleNamespace(write=lambda *event: events.append(event), syn=lambda: None)
    monkeypatch.setattr("rotation_engine.time.sleep", lambda _: allowed.__setitem__(0, False))
    with pytest.raises(InterruptedError):
        sender.command("/consider")
    assert events == [(e.EV_KEY, e.KEY_SLASH, 1), (e.EV_KEY, e.KEY_SLASH, 0)]
    assert not sender.held and sender.unfinished


def test_interruption_before_first_command_key_does_not_require_escape():
    sender = KeySender.__new__(KeySender)
    sender.unfinished = False
    sender.character = lambda _: (_ for _ in ()).throw(InterruptedError("Movement held"))
    with pytest.raises(InterruptedError):
        sender.command("/consider")
    assert not sender.unfinished


def test_arming_keeps_live_npc_identity_but_requires_new_consider():
    engine = Engine(Settings(level=4), lambda *_: None, lambda *_: None)
    engine.gate = SimpleNamespace(controls_ready=lambda: True)
    engine.prepared, engine.prepared_level = True, 4
    engine.target_name, engine.target_kind = "orc runner", "NPC"
    engine.handle_job("arm", None)
    assert engine.active and engine.target_ready is None
    assert (engine.target_name, engine.target_kind) == ("orc runner", "NPC")


def test_consider_log_allows_mob_and_blocks_guard(catalog):
    class Tail:
        lines = []

        def poll(self):
            result, self.lines = self.lines, []
            return result

    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.tail = Tail()
    engine.rotation = Rotation(catalog.profile(4), 4)
    engine.active = True
    engine.target_ready = None

    engine.tail.lines = [
        "A bat regards you indifferently -- looks kind of risky, but you might win. (Lvl: 1)"
    ]
    engine.read_log()
    assert engine.target_ready is True
    assert engine.target_name == "A bat"

    engine.tail.lines = [
        "Guard Gabel regards you indifferently -- looks like an even fight. (Lvl: 5)"
    ]
    engine.read_log()
    assert engine.target_ready is False
    assert not engine.attack_started
    assert engine.native_attack_off_pending
    assert "blocked" in engine.status.casefold()


def test_non_npc_target_is_blocked_before_any_attack(catalog):
    class Tail:
        def poll(self):
            return ["Targeted (Merchant): Hanek Ogerbane"]

    engine = Engine(Settings(), lambda *_: None, lambda *_: None)
    engine.tail = Tail()
    engine.rotation = Rotation(catalog.profile(4), 4)
    engine.active = True
    engine.target_ready = True
    engine.attack_started = True

    engine.read_log()

    assert engine.target_ready is False
    assert not engine.attack_started
    assert engine.native_attack_off_pending
    assert "merchant" in engine.status.casefold()
