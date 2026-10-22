"""Client-data-driven Paladin/Cleric profiles; independent of Linux input and Qt."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import re
import time


DEFAULT_GAME = Path.home() / "Games/everquest-legends/drive_c/users/Public/Daybreak Game Company/Installed Games/EverQuest Legends"
FAMILIES = {
    "quick_heal": ("Echo of Health", "Echoing Light", "Renewing Echo", "Celestial Echo", "Sacred Echo"),
    "heal": ("Minor Healing", "Light Healing", "Healing", "Greater Healing", "Superior Healing"),
    "nuke": ("Strike", "Furor", "Smite", "Wrath", "Retribution"),
    "undead": ("Ward Undead", "Expulse Undead", "Dismiss Undead", "Expel Undead", "Banish Undead"),
    "stun": ("Cease", "Desist", "Stun", "Holy Might", "Force"),
    "hot": ("Celestial Remedy", "Celestial Health", "Celestial Healing"),
    "yaulp": ("Yaulp", "Yaulp II", "Yaulp III"),
    "proc": ("Instrument of Nife", "Divine Might"),
    "armor": ("Courage", "Center", "Daring", "Bravery", "Valor", "Resolution"),
}
SLOTS = {"quick_heal": 1, "heal": 2, "nuke": 3, "undead": 4,
         "stun": 5, "hot": 6, "yaulp": 7, "proc": 8, "armor": 2}
LABELS = {"quick_heal": "Fast / Echo heal", "heal": "Large direct heal", "nuke": "General damage",
          "undead": "Undead damage", "stun": "Stun", "hot": "Heal over time",
          "yaulp": "Yaulp buff", "proc": "Weapon proc buff", "armor": "HP / AC buff"}
CONFIG_DIR = Path.home() / ".config/eql-rotation"
STATE_FILE = CONFIG_DIR / "settings.json"


@dataclass(frozen=True)
class Spell:
    id: int
    name: str
    cleric_level: int
    paladin_level: int
    cast_ms: int
    recovery_ms: int
    recast_ms: int
    mana: int
    duration_ticks: int
    target_type: int

    @property
    def level(self) -> int:
        return min(self.cleric_level, self.paladin_level)

    @property
    def busy_seconds(self) -> float:
        # Base client timings are conservative when motes shorten your spells.
        return (self.cast_ms + self.recovery_ms) / 1000 + 0.35


class Catalog:
    def __init__(self, spells: list[Spell]):
        self.spells = {s.id: s for s in spells}
        self.by_name = {s.name.casefold(): s for s in spells}

    @classmethod
    def load(cls, game_dir: Path) -> "Catalog":
        spells = []
        with (game_dir / "spells_us.txt").open(encoding="latin-1") as source:
            for line in source:
                f = line.rstrip("\r\n").split("^")
                if len(f) < 52 or not f[0].isdigit():
                    continue
                try:
                    clr, pal = int(f[37]), int(f[38])
                    if not any(1 <= level <= 50 for level in (clr, pal)):
                        continue  # 254/255 entries include NPC and unusable duplicate spells.
                    spells.append(Spell(int(f[0]), f[1], clr, pal, int(f[8]), int(f[9]),
                                        int(f[10]), int(f[14]), int(f[12]), int(f[30])))
                except (ValueError, IndexError):
                    continue
        result = cls(spells)
        minor = result.spells.get(200)
        if not minor or minor.name != "Minor Healing" or minor.level != 1 or minor.cast_ms != 1500:
            raise ValueError("Client spell layout did not pass the Minor Healing sanity check; no keys will be sent.")
        strike = result.spells.get(14)
        if not strike or strike.name != "Strike" or strike.level != 1:
            raise ValueError("Client spell layout did not pass the Strike sanity check.")
        return result

    def resolve_name(self, text: str) -> Spell | None:
        text = text.strip().strip('"')
        exact = self.by_name.get(text.casefold())
        if exact:
            return exact
        # Mote tiers can be exported as suffixes; real names such as Yaulp II
        # were checked first, so they retain their own spell ID and level.
        for pattern in (r"\s+(?:Rk\.\s*)?[IVX]+$", r"\s*\((?:rank|tier)\s+\d+\)$"):
            stripped = re.sub(pattern, "", text, flags=re.I)
            if stripped != text:
                found = self.by_name.get(stripped.casefold())
                if found:
                    return found
        return None

    def parse_book(self, text: str) -> set[int]:
        known = set()
        for line in text.splitlines():
            # Match names, never arbitrary numeric columns (which may be page
            # numbers or levels rather than spell IDs).
            tokens = re.split(r"\t|\^|\|", line)
            for token in tokens:
                spell = self.resolve_name(token)
                if spell:
                    known.add(spell.id)
            if not any(self.resolve_name(token) for token in tokens):
                match = re.match(r"^\s*\d+\s+(.+?)\s*$", line)
                spell = self.resolve_name(match.group(1)) if match else None
                if spell:
                    known.add(spell.id)
        return known

    def profile(self, level: int, known: set[int] | None = None) -> dict[str, Spell]:
        if not 1 <= level <= 50:
            raise ValueError("Level must be between 1 and 50")
        result = {}
        for role, names in FAMILIES.items():
            candidates = [self.by_name[name.casefold()] for name in names if name.casefold() in self.by_name]
            candidates = [s for s in candidates if s.level <= level and (known is None or s.id in known)]
            if candidates:
                if role == "stun":
                    # Cleric Stun (L2, 4 seconds) is stronger control than the
                    # later Paladin Cease/Desist; do not downgrade by level.
                    result[role] = max(candidates, key=lambda s: names.index(s.name))
                else:
                    result[role] = max(candidates, key=lambda s: (s.level, names.index(s.name)))
        # Before the Echo line, the fast heal uses the same heal as the large
        # heal. EQ cannot memorize a spell twice; leave gem 2 unused then.
        if "quick_heal" not in result and "heal" in result:
            result["quick_heal"] = result.pop("heal")
        # Until two different heals are learned, use the vacant second gem
        # for the HP/AC line. Never displace an existing prepared heal.
        if "heal" in result:
            result.pop("armor", None)
        return result


def message_body(line: str) -> str:
    return re.sub(r"^\[[^\]]+\]\s*", "", line.strip(), count=1)


def level_from_message(line: str) -> int | None:
    match = re.fullmatch(r"You have gained (?:a level|\d+ levels)! Welcome to level (\d+)!", message_body(line))
    level = int(match.group(1)) if match else None
    return level if level is not None and 1 <= level <= 50 else None


class LogTail:
    """Tail only new messages; tolerate truncation, replacement and missing files."""
    def __init__(self, path: Path):
        self.path = path
        self.position = 0
        self.identity = None
        self.partial = b""
        self.initialized = False

    def poll(self) -> list[str]:
        try:
            stat = self.path.stat()
        except OSError:
            return []
        identity = (stat.st_dev, stat.st_ino)
        if not self.initialized:
            self.initialized = True
            self.position = stat.st_size
            self.identity = identity
            return []
        if identity != self.identity or stat.st_size < self.position:
            self.position, self.partial = 0, b""
        self.identity = identity
        with self.path.open("rb") as source:
            source.seek(self.position)
            data = source.read(512 * 1024)
            self.position = source.tell()
        lines = (self.partial + data).split(b"\n")
        self.partial = lines.pop()
        return [line.decode("utf-8", errors="replace") for line in lines]


@dataclass
class Settings:
    game_dir: str = str(DEFAULT_GAME)
    character: str = "Legira"
    server: str = "freeport"
    level: int = 1
    mode: str = "balanced"
    smart_heal: bool = True
    use_stuns: bool = False
    use_bash: bool = False
    damage_interval: float = 10.0
    hp_region: dict | None = None
    mana_region: dict | None = None
    auto_stance: bool = True
    stance_keys_verified: bool = False

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> "Settings":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        data = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        settings = cls(**data)
        settings.level = max(1, min(50, int(settings.level)))
        settings.damage_interval = max(4.0, min(30.0, float(settings.damage_interval)))
        if settings.mode not in ("balanced", "undead"):
            settings.mode = "balanced"
        return settings

    def save(self, path: Path = STATE_FILE) -> None:
        from dataclasses import asdict
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2))
        temporary.chmod(0o600)
        temporary.replace(path)


@dataclass(frozen=True)
class Action:
    role: str
    command: str
    busy_seconds: float
    cooldown: float


@dataclass
class StancePlan:
    """Conservative solo PAL/CLR policy with a gap between enter/exit HP."""
    stance: str | None = None
    invocation: str | None = None
    stance_ready_at: float = 0.0
    invocation_ready_at: float = 0.0

    def choose(self, now, hp):
        desired = self.stance or "balanced"
        if hp is not None and 0 < hp <= .65:
            desired = "defensive"
        elif hp is None or hp >= .85:
            desired = "balanced"
        if desired != self.stance and now >= self.stance_ready_at:
            return desired
        if self.invocation != "divine" and now >= self.invocation_ready_at:
            return "divine"
        return None

    def requested(self, role, now):
        if role == "divine":
            self.invocation = role
            self.invocation_ready_at = now + 6
        else:
            self.stance = role
            self.stance_ready_at = now + 6


def stance_bindings_match(game_dir: Path) -> bool:
    """Read the client's saved bindings; never send an unassigned stance key."""
    import configparser
    expected = {"keymapping_cmd_balanced_stance_1": 0x60000002,
                "keymapping_cmd_defensive_stance_1": 0x60000003,
                "keymapping_cmd_divine_invocation_1": 0x60000004}
    try:
        ini = configparser.ConfigParser(interpolation=None, strict=False)
        ini.read_string((Path(game_dir) / "eqclient.ini").read_text(errors="replace"))
        values = {key: int(value) for key, value in ini["KeyMaps"].items()}
        if any(values.get(key) != value for key, value in expected.items()):
            return False
        return not any(value in expected.values() and key not in expected
                       for key, value in values.items())
    except (OSError, ValueError, KeyError, configparser.Error):
        return False


@dataclass
class Rotation:
    profile: dict[str, Spell]
    level: int
    mode: str = "balanced"
    damage_interval: float = 10.0
    smart_heal: bool = True
    use_stuns: bool = False
    use_bash: bool = False
    last: dict[str, float] = field(default_factory=dict)
    busy_until: float = 0.0
    loh_ready_at: float = 0.0

    def spell_action(self, role: str, cooldown: float = 0) -> Action | None:
        spell = self.profile.get(role)
        if not spell:
            return None
        return Action(role, f"/cast {SLOTS[role]}", spell.busy_seconds,
                      max(cooldown, spell.recast_ms / 1000, spell.busy_seconds))

    def choose(self, now: float, hp: float | None, mana: float | None,
               *, allow_offense: bool = True) -> Action | None:
        if now < self.busy_until:
            return None
        if self.smart_heal and hp is not None and 0 < hp <= 0.25 and now >= self.loh_ready_at:
            return Action("lay_hands", "/alt activate 6001", 0.2, 900)
        if self.smart_heal and hp is not None and 0 < hp <= 0.65:
            heal = self.spell_action("quick_heal") or self.spell_action("heal")
            if heal:
                # Do not fill a short heal cooldown with a damage/buff cast
                # while the player still needs that heal.
                return heal if self.ready(heal, now) else None
        if self.smart_heal and hp is not None and 0 < hp <= 0.82:
            hot = self.profile.get("hot")
            heal = self.spell_action("hot", max(24, (hot.duration_ticks * 6) if hot else 24))
            if heal and self.ready(heal, now) and (mana is None or mana > 0.15):
                return heal
        for role in ("armor", "yaulp", "proc"):
            spell = self.profile.get(role)
            if not spell:
                continue
            duration = spell.duration_ticks * 6
            if role not in self.last or (duration > 0 and now >= self.last[role] + duration):
                buff = self.spell_action(role)
                if buff and self.ready(buff, now) and (mana is None or mana > 0.35):
                    return buff
        if not allow_offense:
            return None
        if self.level >= 9 and (mana is None or mana > 0.35):
            smite = Action("smite_ability", "/doability Smite", 0.2, 15)
            if self.ready(smite, now):
                return smite
        if self.use_bash:
            bash = Action("bash", "/doability Bash", 0.2, 8)
            if self.ready(bash, now):
                return bash
        if self.use_stuns and (mana is None or mana > 0.35):
            stun = self.spell_action("stun", 20)
            if stun and self.ready(stun, now):
                return stun
        if mana is not None and mana <= 0.25:
            return None  # Keep a reserve for healing.
        role = "undead" if self.mode == "undead" and "undead" in self.profile else "nuke"
        damage = self.spell_action(role, self.damage_interval)
        return damage if damage and self.ready(damage, now) else None

    def ready(self, action: Action, now: float) -> bool:
        return now - self.last.get(action.role, float("-inf")) >= action.cooldown

    def committed(self, action: Action, now: float) -> None:
        self.last[action.role] = now
        self.busy_until = now + action.busy_seconds
        if action.role == "lay_hands":
            self.loh_ready_at = now + 900

    def landed_smite(self) -> None:
        self.loh_ready_at = max(0.0, self.loh_ready_at - 60)


def bar_fraction(image, channel: str) -> float | None:
    """Estimate a calibrated, flat red/blue gauge; reject noisy/non-gauge images.

    No reading is preferable to guessing HP from an unrelated window/skin.
    The calibration UI requires the inner gauge at full health/mana.
    """
    import numpy as np
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    if pixels.shape[1] < 20 or pixels.shape[0] < 2:
        return None
    dominant = pixels[:, :, 0 if channel == "red" else 2]
    other = np.maximum(pixels[:, :, 1], pixels[:, :, 2 if channel == "red" else 0])
    colored = (dominant >= 80) & (dominant > other * 1.35 + 8)
    columns = colored.mean(axis=0) >= 0.20
    hits = np.flatnonzero(columns)
    if len(hits) < 2:
        return None
    width = len(columns)
    # The filled segment must start at the left edge and be mostly contiguous.
    if hits[0] > max(3, width * 0.08):
        return None
    end = int(hits[-1]) + 1
    if columns[:end].mean() < 0.65:
        return None
    return min(1.0, end / width)


def profile_report(catalog: Catalog, level: int, known: set[int] | None = None) -> dict:
    profile = catalog.profile(level, known)
    return {"level": level, "spellbook_confirmed": known is not None,
            "gems": [{"slot": SLOTS[role], "role": role, "name": spell.name,
                      "id": spell.id, "required_level": spell.level, "mana": spell.mana,
                      "cast_ms": spell.cast_ms} for role, spell in profile.items()]}
