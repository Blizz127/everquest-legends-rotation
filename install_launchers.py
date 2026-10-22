"""Install only this helper's desktop launchers and the solo healing setting."""
from pathlib import Path
import datetime
import json
import os
import re
import shutil

from rotation_core import DEFAULT_GAME


def install():
    project = Path(__file__).resolve().parent
    desktop_source = project / "eql-solo-assist.desktop"
    launchers = []
    for directory, name in [(Path.home() / "Desktop", "EQ Legends Solo Assist.desktop"),
                            (Path.home() / ".local/share/applications", "eql-solo-assist.desktop")]:
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / name
        if destination.is_symlink() and destination.resolve() == desktop_source:
            pass
        elif destination.exists() or destination.is_symlink():
            raise RuntimeError(f"An unrelated launcher already exists: {destination}")
        else:
            destination.symlink_to(desktop_source)
        launchers.append(str(destination))
    (project / "launch.sh").chmod(0o755)
    desktop_source.chmod(0o755)
    running = False
    for comm in Path("/proc").glob("[0-9]*/comm"):
        try:
            if comm.read_text().strip().casefold() == "eqgame.exe":
                running = True
                break
        except OSError:
            pass
    changes = []
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not running:
        for ini in DEFAULT_GAME.glob("*_LO*.ini"):
            if ini.name.startswith("UI_"):
                continue
            original = ini.read_bytes()
            updated = re.sub(rb"(?m)^UseImpliedHealing=0(?=\r?$)", b"UseImpliedHealing=1", original)
            if updated != original:
                backup = project / "artifacts" / (ini.name + ".before-implied-healing-" + stamp)
                backup.parent.mkdir(exist_ok=True)
                shutil.copy2(ini, backup)
                backup.chmod(0o600)
                ini.write_bytes(updated)
                changes.append({"file": str(ini), "backup": str(backup),
                                "setting": "UseImpliedHealing", "before": 0, "after": 1})
    report = {"timestamp": stamp, "launchers": launchers,
              "game_running_at_install": running, "character_setting_changes": changes,
              "live_combat_verified": False,
              "first_use": "Choose your current character/level, enter your character, then F6 to prepare and F8 to assist."}
    (project / "artifacts").mkdir(exist_ok=True)
    (project / "artifacts/install.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    install()
