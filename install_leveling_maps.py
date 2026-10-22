#!/usr/bin/env python3
"""Build a separate EQ map set with visible 1-50 leveling markers."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


PACK_NAME = "Solo_Leveling"
DEFAULT_MAPS = (Path.home() / "Games/everquest-legends/drive_c/users/Public/"
                "Daybreak Game Company/Installed Games/EverQuest Legends/maps")
MARKER_RGB = (0, 255, 127)
MARKER_SIZE = 3


@dataclass(frozen=True)
class LevelingSpot:
    zone: str
    minimum: int
    maximum: int
    x: float
    y: float
    z: float
    name: str
    primary: bool = False

    @property
    def label(self) -> str:
        return f"L{self.minimum:02d}-{self.maximum:02d}_{self.name}"


# Coordinates are EQ map coordinates, not /loc order. Lime size-3 labels keep
# the route distinct from the stock geometry copied into the custom map set.
LEVELING_SPOTS = (
    LevelingSpot("butcher", 1, 4, 650, -2700, 0,
                 "Newbie_Hills_L4_Krag_Aviak", True),
    LevelingSpot("butcher", 5, 8, -884, 1540, 0,
                 "Dwarf_Skeletons_CLR_PAL_Bonus"),
    LevelingSpot("butcher", 5, 8, 2069, 298, 0, "Goblin_Camp_ALT"),
    LevelingSpot("butcher", 4, 10, 3061, 1316, 0, "GO_TO_GFAY_THEN_CRUSHBONE"),
    LevelingSpot("gfaydark", 4, 7, -48, -1849, 18, "Orc_Camps"),
    LevelingSpot("gfaydark", 4, 10, 52, -2597, 16, "GO_TO_CRUSHBONE"),
    LevelingSpot("crushbone", 4, 7, -150, 520, 0, "START_HERE_ENTRANCE", True),
    LevelingSpot("crushbone", 7, 10, -426, -74, -17, "Slave_Mines", True),
    LevelingSpot("crushbone", 10, 13, -119, 212, 80, "Trainer_Hill"),
    LevelingSpot("crushbone", 13, 17, 95, 78, 0, "North_Wall_and_Castle"),
    LevelingSpot("crushbone", 17, 22, -106, -154, 16, "Throne_Room"),
    LevelingSpot("cauldron", 10, 25, 625, 2031, 91, "Zone_to_Unrest"),
    LevelingSpot("unrest", 10, 17, -100, -300, 0, "Courtyard", True),
    LevelingSpot("unrest", 16, 22, -35, -524, 16, "First_Floor", True),
    LevelingSpot("unrest", 22, 25, -55, -674, -22, "Basement_and_Back_Rooms", True),
    LevelingSpot("mistmoore", 19, 23, -126, 300, -182, "Entrance_and_Tunnels_ALT"),
    LevelingSpot("mistmoore", 23, 30, -392, -89, -200, "Graveyard_and_Courtyard_ALT"),
    LevelingSpot("guktop", 19, 25, -159, -170, 0, "Necromancer_Area_ALT"),
    LevelingSpot("guktop", 25, 30, -260, 17, -98, "Shin_Lord_ALT"),
    LevelingSpot("gukbottom", 25, 32, 414, -927, -141, "Bedroom_and_Spiders", True),
    LevelingSpot("gukbottom", 32, 40, 651, -1140, -195, "Reanimated_Hand_Undead", True),
    LevelingSpot("gukbottom", 38, 45, 775, -638, -112, "Assassin_and_Supplier", True),
    LevelingSpot("gukbottom", 42, 50, 832, -1171, -194, "Arch_Magus_and_Ghoul_Lord_ALT"),
    LevelingSpot("soldunga", 20, 25, 551, 650, 40, "Goblin_Castle_ALT"),
    LevelingSpot("soldunga", 24, 30, 583, 356, 35, "Foreman_and_Predator_ALT"),
    LevelingSpot("soldungb", 32, 38, 311, 968, -85, "Stone_Spiders_ALT"),
    LevelingSpot("soldungb", 35, 42, 333, 648, -70, "Kobolds_and_Beetles_ALT"),
    LevelingSpot("soldungb", 40, 46, -334, 481, -84, "Efreeti_ALT"),
    LevelingSpot("oot", 14, 18, -3979, -1539, -77, "Aviak_Island_ALT"),
    LevelingSpot("oot", 18, 22, 4887, 88, -105, "Island_of_the_Dead_CLR_PAL"),
    LevelingSpot("oot", 30, 40, 2800, -1704, -283, "Seafury_Island_ALT"),
    LevelingSpot("oot", 40, 50, 5639, -2264, -174, "Elite_Goblin_Island_ALT"),
    LevelingSpot("hole", 40, 44, 940, -611, -95, "Entrance_and_Castle", True),
    LevelingSpot("hole", 42, 46, -80, -400, -350, "Sword_Slab_and_Docks", True),
    LevelingSpot("hole", 45, 50, -460, -680, -658, "Undead_Tower_HARD_CLR_PAL", True),
    LevelingSpot("hateplane", 46, 50, 362, 420, 2, "Plane_of_Hate_ALT_HIGH_RISK"),
    LevelingSpot("fearplane", 46, 50, -1030, 784, 0, "Plane_of_Fear_ALT_HIGH_RISK"),
)


def _point_line(spot: LevelingSpot) -> str:
    red, green, blue = MARKER_RGB
    return (f"P {spot.x:.4f}, {spot.y:.4f}, {spot.z:.4f}, "
            f"{red}, {green}, {blue}, {MARKER_SIZE}, {spot.label}\n")


def render_overlays(output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for zone in sorted({spot.zone for spot in LEVELING_SPOTS}):
        path = output / f"{zone}_3.txt"
        spots = sorted((spot for spot in LEVELING_SPOTS if spot.zone == zone),
                       key=lambda spot: (spot.minimum, spot.maximum, spot.name))
        path.write_text("".join(_point_line(spot) for spot in spots), encoding="utf-8")
        paths.append(path)
    return paths


def route_text() -> str:
    return """EQ Legends Solo Leveling map set

Select Solo_Leveling in the in-game Map window's map-set dropdown.
Bright lime labels show level ranges and camps. ALT means an optional route;
HARD/HIGH_RISK means gear and careful pulls matter. The helper never moves,
targets, or pulls for you.

Recommended PAL/CLR path:
  1-4   Butcherblock: Kaladim newbie hills
  4-10  Crushbone: entrance, then slave mines
 10-25  Unrest: courtyard, first floor, then basement/back rooms
 25-32  Lower Guk: bedroom and spider room
 32-42  Lower Guk: undead camps around reanimated hand
 40-46  The Hole: entrance/castle, then sword/slab/docks
 45-50  The Hole: undead tower (hard; excellent PAL/CLR target type)

At level 4, stay at L01-04_Newbie_Hills_L4_Krag_Aviak for level-4 Krag
and aviak chicks. On D3, do not move to the level 5-7 dwarf skeletons early.
For the dungeon route, follow L04-10_GO_TO_GFAY_THEN_CRUSHBONE, then
L04-10_GO_TO_CRUSHBONE in Greater Faydark, and begin at
L04-07_START_HERE_ENTRANCE inside Crushbone.

The installer copied the current client maps into this separate folder and
added only *_3.txt overlays. Re-run install_leveling_maps.py after a client map
update to refresh the copied base maps. Camp coordinates were cross-checked
against Brewall 2024-01-09 map labels and current Legends leveling sources.
"""


def _tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.txt")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def install_pack(stock_maps: Path = DEFAULT_MAPS) -> Path:
    stock_maps = Path(stock_maps).expanduser().resolve()
    if not stock_maps.is_dir() or not (stock_maps / "butcher.txt").is_file():
        raise FileNotFoundError(f"EverQuest maps folder is not valid: {stock_maps}")

    target = stock_maps / PACK_NAME
    temporary = Path(tempfile.mkdtemp(prefix=f".{PACK_NAME}.build-", dir=stock_maps))
    backup = None
    try:
        source_files = sorted(path for path in stock_maps.glob("*.txt") if path.is_file())
        if not source_files:
            raise RuntimeError("No stock map files were found; nothing was installed.")
        for source in source_files:
            shutil.copy2(source, temporary / source.name)
        render_overlays(temporary)
        (temporary / "README.txt").write_text(route_text(), encoding="utf-8")

        if target.exists():
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = stock_maps / f"{PACK_NAME}.before-{timestamp}"
            target.rename(backup)
        temporary.rename(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        if backup is not None and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps-dir", type=Path, default=DEFAULT_MAPS)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    target = install_pack(args.maps_dir)
    report = {
        "installed": str(target),
        "map_files": len(list(target.glob("*.txt"))),
        "overlays": len(list(target.glob("*_3.txt"))),
        "markers": len(LEVELING_SPOTS),
        "sha256": _tree_hash(target),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
