# EQ Legends Solo Assist — Paladin / Cleric, levels 1–50

F8 combat on, F9 off, F10 heal, F6 refresh spells. F7 toggles combat on/off
(the Legion Go 2 Y1 wrapper presents Y1 as F7).

Installed for the Alienware Bazzite desktop and the existing Lutris prefix.

Live validation on 2026-10-17 now includes `Legira [4 PAL/CLR]` in
Butcherblock, real spell preparation, calibrated HP/mana readings, guarded
hotkeys, and controlled combat. The prepared bar contains learned spells only:
Light Healing, Strike, Ward Undead, and Yaulp. A controlled fight logged two
separate Strike casts before the same kill. F8 has also been verified live as
persistent ON: it waits with no target, refuses an amiable guard, and resumes
combat only after `/consider` identifies a safe leveling mob selected by the
player. Mob level does not limit attacks; you choose the fight difficulty.
Guards, friendly/service NPCs, and players remain protected. See
`artifacts/live-validation-2026-10-17.md` for exact evidence and remaining
checks.

Open **EQ Legends Solo Assist** from the desktop or application menu. Select
your character and starting level, log into that character with Paladin and
Cleric active, stand safely out of combat, and press **F6** in the game.
The assistant exports your spellbook and loads the best spells you actually
own. Preparation may take roughly a minute; the status shows each gem.

Press **F8** once to arm the combat assist. It waits safely when no target is
selected, fights the enemy you select, and returns to waiting after each kill.
Healing and self buffs run while waiting, including when an enemy is refused
by the attack safety check. Below 65% calibrated HP, healing takes priority
over buffs and damage. Failed casts retry; timed buffs refresh after expiry.
At early levels, preparation adds the learned Courage line to vacant gem 2;
an existing two-heal loadout keeps both heals instead.
You do not need to press F8 for every enemy. Repeated F8 presses keep combat
on; **F9** turns it off. **F10** requests the quick heal. F8 never prepares
spells or selects a target, and the helper consumes it so EQ's default F8
action does not also fire.

`/consider` runs once when combat is armed and once for each newly selected
NPC. If no target exists, the helper then waits silently until EQ reports a new
selection; it does not poll `/consider` continuously. Incoming hits/misses from a new attacker
also wake one safety check, covering EQ target changes that have no selection
log message. F8 while waiting explicitly requests another check.

Before the first attack on each selection, the helper turns melee off and runs
`/consider`. It allows clear leveling mobs, but refuses guards, merchants,
bankers, trainers, players, friendly faction reactions, and unknown proper-name
NPCs. A refusal leaves combat armed so you can select a different mob.
Hostile names such as `Orc taskmaster` and `Orc slaver` count as mobs even
when the game omits an article and no new target-selection log is available.
The check is conservative about NPC identity, but has no level cap. A named
dubious NPC can also be approved from an exact-name incoming attack within
the last 12 seconds. Once approved, that target's permission does not expire
just because no new hit arrives. Players, guards, service NPCs and friendly
reactions are still blocked. Melee stays on between heals for all approved
mobs, so healing does not leave you unable to hit back. If the
helper needs NPC confirmation after a restart, click the attacker once.

For automatic healing, use **Calibrate HP** while at full HP and select the
inner red gauge. Optional blue mana calibration enables a 25% casting reserve.
Automatic healing depends on a valid health reading. With no calibrated or
valid reading, the assistant leaves reactive healing to F10 / your manual gems.
Only the game's own XWayland window is captured; images are not saved or uploaded.
Recalibrate after changing resolution, UI skin, or gauge placement.

The initial level is set manually because the old logs on this install do not
contain a reliable current-level record. New level-up messages update it while
the helper runs. After a level-up, stop between fights and press **F6** to
refresh your learned spellbook and load any newly usable upgrades. You still
acquire and scribe spells normally.

## Solo behavior

- Auto-attack for melee; optional Bash when a shield is equipped, and the
  Paladin **Smite ability** from level 9. Bash is off by default.
- Cleric damage spells every 10 seconds by default; optional 4-second cadence.
- Undead mode chooses the stronger appropriate undead nuke.
- Yaulp and the Paladin proc buff once after preparation or a logged death.
- With calibrated HP: Lay on Hands at 25%, quick/Echo heals at 65%, and a
  Celestial heal over time at 82% when available.
- Stuns are optional and off by default to conserve mana.
- A kill leaves combat armed and waiting for the next manually selected enemy.
  Escape clears the target and leaves combat armed. F8 is ON-only and F9 is
  OFF. Losing focus or holding movement/modifier keys pauses command injection
  while preserving the armed state. If this interrupts a partly typed helper
  command, returning to EQ clears the draft and repeats the safety check before
  resuming. Chat/slash, zoning, death, or F9 disarms it.
- Alt+Enter window-mode changes preserve the armed state. A pause before any
  command is typed leaves already-verified melee running. A pending target
  safety check runs before buffs/noncritical heals so they cannot delay attack
  approval; emergency healing at 25% HP or below still has priority.
- Running out of mana keeps combat and verified melee on. Mana-consuming
  actions wait five seconds before retrying; Lay on Hands remains available.
- No third-class ability is assumed. Targeting, pulling, movement, additional buff sets, cures, and encounters
  remain player controlled. Stance automation is optional and requires verified bindings.

The client `/stance` command is for mercenaries. Optional automatic player
stances use the game's own verified bindings in Options → Controls →
Stances/Invocations: **Ctrl+Shift+1** Balanced Stance, **Ctrl+Shift+2** Defense
Stance, **Ctrl+Shift+3** Divine. Do not use Ctrl+Shift+F1/F2/F3: KDE uses those
for desktop shortcuts. The helper reads saved bindings and disables stance
input if any chord is missing or assigned to another action. With the automatic
stance option on, it requests Defense at or below 65% HP, returns to Balanced
at 85%, and selects Divine invocation. It respects six-second switch cooldowns
and ongoing spell casts. Turn off the option to choose stances manually.

Solo heals require the game's **Use implied healing** option. The installation
step backs up the existing offline character files before enabling that setting.
The full solo spell progression, buff advice, and controls are in the app.

## Leveling maps

The separate in-game map set **Solo_Leveling** is installed with 37 bright lime
camp markers across 14 zone overlays. Choose `Solo_Leveling` in the Map window's
map-set dropdown. The primary PAL/CLR route is Butcherblock 1–4, Crushbone
4–10, Unrest 10–25, Lower Guk 25–42, and The Hole 40–50. The original map files
were not changed. At level 4 on D3 in Butcherblock, stay at
`L01-04_Newbie_Hills_L4_Krag_Aviak` and choose level-4 Krag or aviak chicks.
The dwarf-skeleton marker begins at level 5. The dungeon route follows
`GO_TO_GFAY_THEN_CRUSHBONE`, then `GO_TO_CRUSHBONE`, and starts at the marked
Crushbone entrance. See `LEVELING_MAPS.md` for the full route and alternatives.

## Local checks

```bash
./launch.sh --dry-run --level 20
./launch.sh --all-levels
python3 -m pytest -q
QT_QPA_PLATFORM=offscreen ./launch.sh --gui-smoke-test /tmp/eql-ui.png
```

Dry runs and GUI smoke tests never start the input engine or create a virtual
keyboard. Runtime dependencies already present on Alienware: Python, PySide6,
python-evdev, python-xlib, Pillow and numpy. No package installation, root
service, startup automation, or Lutris runner change is required.

Settings: `~/.config/eql-rotation/settings.json`. Spellbook export:
`<game>/eql-rotation-spellbook.txt`. Remove the desktop/menu launchers and this
project to uninstall; restore the per-character backups to undo implied healing.

Spell data comes from the installed `spells_us.txt`; canonical spell names,
class-level columns and timings are checked before input is allowed. Unusable
254/255 and NPC duplicate entries are excluded. The native `/memspellslot`
command is present in this client's command and string tables.

References for the mechanics and file formats:

- https://www.everquest.com/update-notes/eq-update-notes-7-20-2022
- https://github.com/ArtSabintsev/everquest-legends-mcp/blob/main/docs/local-client-extraction.md
- https://eqlwiki.com/Paladin
- https://eqlwiki.com/Cleric

Automatic Light Healing completed in live combat on 2026-10-18: the helper
requested gem 1 at about 6% HP, and the game logged 49 HP healed on Legira.
F10 completion and Courage application remain unverified. Incoming-add
wakeup and Escape persistence have automated coverage; a new live multi-mob
sequence is still pending. The helper cannot guarantee survival against
over-level enemies, stuns or repeated failed casts.
