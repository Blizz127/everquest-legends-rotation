# EQ Legends Solo Assist — Codex handoff

## Low-mana shutdown fix — 2026-10-18

Live follow-up on the pause fix caught an additional concrete shutdown:
13:17:19 trace `stopped`, reason `Low mana. Recover, then press F8 to resume.`,
with target_ready=true and attack_started=true. Insufficient Mana no longer
calls stop_action. Combat and verified melee stay on; mana actions wait five
seconds before retry. Target checks and Lay on Hands remain available during
that wait, while normal emergency priority and guard/player protection remain.
Two tests cover normal HP and critical HP/LoH with invalid mana calibration.
102 tests and compilation pass. Reloaded eql-solo-assist-desktop.service,
PID 1644807 at reload. Press F8 once after this reload. Fresh low-mana live
acceptance remains pending. The three pause/chat/probe fixes below are also
in this build. All current settings and actual prepared gems were retained.

Subsequent trace recorded owner F8, one target probe, then death and zoning
before the low-mana fix could be accepted live. HP read null during that
sequence. The helper is now stopped after death/zone by design; do not claim
the fight was successful or the latest fixes are live-accepted. Owner should
revive/recover and re-arm only when ready. Confirm valid HP sensing in-world
before relying on automatic healing again.

## Combat pause / chat shortcut fix — 2026-10-18

Further live complaints exposed three separate paths after Orc-name approval:
the trace recorded Alt+Enter (Alt key 56 held) stopping combat as if it opened
chat; an InterruptedError before a command's first key queued attack-off even
when an already-approved mob was being fought; and repeated healing/buffs
could delay the initial target probe for many seconds.

Alt+Enter/keypad Enter with Alt now preserves combat while normal Enter,
slash and F9 retain their chat/stop behavior. A transient pause with no partial
draft preserves verified melee and existing target permission; it does not
clear an attack-off already required by target change or protection. A real
partial draft still uses the conservative recovery path. Above 25% HP (or with
no gauge), one pending /con precedes buffs and noncritical heals. At or below
25%, emergency support retains priority. No offense bypasses target approval.

100 tests and Python compilation pass. Reloaded
eql-solo-assist-desktop.service (PID 1623304 at reload), with owner asked to
return to EQ, close chat and press F8 once. The fixes are automated-verified;
fresh owner combat acceptance after this reload remains pending. Do not claim
all input reliability problems resolved: the last pre-fix client log also
contained an invalid command, and real interrupted drafts still require
recovery. Backup: `artifacts/before-combat-pause-fix-20261018/`.

## Hostile Orc taskmaster identity fix — 2026-10-18

The owner reported the level-14 taskmaster still being refused. The trace
showed "Click Orc taskmaster once to confirm it is an NPC"; the game log
showed a hostile /con and repeated Orc taskmaster hits on Legira, but no
Targeted(NPC) line. This was the unknown-name identity gate, not a level cap.
The generic-mob recognizer now also admits hostile `Orc ` names without an
article, including Orc taskmaster/slaver. PC/pet kind, guard/service words,
and friendly faction reactions still take precedence. Other unknown proper
names stay protected. A regression replays the exact hostile level-14 /con
without a target-selection log and checks PC/guard/merchant/friendly refusals.

Prepared-state restoration can also retain the exact older memorized profile
after leveling up in the same EQ process. It reconstructs the marker's original
level and checks exact IDs, never assumes upgraded gems, rejects lower player
levels and different sessions. This avoids requiring F6 just to reload a fix.
Actual read-only restoration passed at level 6 before deployment (Light
Healing, Furor, Ward Undead, Courage, Yaulp). 96 tests and compilation pass.
Reloaded eql-solo-assist-desktop.service, PID 1562690 at reload; owner asked
to press F8 once. Taskmaster approval is test-verified; post-fix live combat
against that exact mob remains unverified. Source backup:
`artifacts/before-orc-identity-20261018/rotation_engine.py.before`.

Post-reload live evidence: trace at 13:14:09 approved `Orc slaver` without
a Targeted(NPC) prerequisite. The client logged Legira slashing orc slaver
at 13:14:11 and 13:14:23 while helper Light Healing continued. That verifies
the same Orc-name classification and melee-with-healing path live. The exact
taskmaster recheck remains pending; do not relabel the slaver as taskmaster.

## Current policy: any-level mobs — 2026-10-18

The owner explicitly removed the mob level limit because external buffs let
them fight higher-level enemies. Mob level is now informational and never
blocks an otherwise approved target. Guards, service NPCs, friendly faction
reactions, players and unknown proper-name targets retain their protections.
Named dubious NPCs can still be admitted from exact-name incoming attack
evidence; once admitted, approval does not expire after 12 seconds. Target
changes and protected-target results still invalidate permission.

All verified mobs now enable melee before support spells so healing/buffs
cannot starve auto-attack. Repeated /consider results on the same approved
target preserve melee state. No auto-targeting or movement was added.
The faster input below is also loaded, using /con and the shorter typing gaps.
The desktop helper was restarted as eql-solo-assist-desktop.service (PID
1503230 at reload). 95 tests and Python compilation pass. The owner reported
"way better now" after reloading and resuming combat. Treat that as owner
acceptance of the improvement, not proof of every remaining feature. The live
trace independently shows automatic Light Healing and Defense after reload;
Legira reached level 6 in the current client log. F6 upgrades the spell bar
between fights. Preserve the current settings. Backup:
`artifacts/before-any-level-mobs-20261018/`.

This section supersedes every older level-cap, retaliation-timeout, and
faster-input pending-reload statement below.

## Faster command input — 2026-10-18

The owner reported slow command entry on each mob. KeySender now types the
client-listed `/con` alias for canonical `/consider` (eqstr_us.txt string 6668).
It retains 20 ms key holds, but waits an additional 20 ms on release only for
adjacent repeated letters and the final Enter. Different letters already leave
the previous key released during the next key's hold. Stance tap timing and
every-key F9/focus checks are preserved. No targeting or safety policy changed.

Virtual-input timing tests reduce the attack-off/consider/attack-on sequence
from 1.32 s to 0.68 s, excluding focus checks, scheduling, game processing and
log delivery. This is planned input time, not a measured live engagement time.
94 tests and Python compilation pass, including interruption/key-release and
repeated-letter checks. Backup: `artifacts/before-faster-command-input-20261018/`.
The existing helper was left running on the prior code while awaiting the
owner's safe/out-of-combat response. Reload and a harmless live `/con` check
remain pending. Do not call the faster input live verified yet.

Updated 2026-10-17. Owner requested a one-button solo Paladin/Cleric rotation assist for EverQuest Legends, levels 1–50, on Alienware Linux using Lutris. Third class is undecided; do not assume one. Continue this implementation rather than replacing it.

## Location and machine

- Source on Alienware: `~/Projects/everquest-legends-rotation` (canonical Bazzite path `/var/home/blizz/Projects/everquest-legends-rotation`). A matching source mirror exists on the devbox at `/home/blizz/Projects/everquest-legends-rotation`.
- From the devbox, connect with `ssh blizz@100.111.220.11`. Tailscale name: `alienware-bazzite.tail646ff8.ts.net`.
- Alienware runs Bazzite, KDE Wayland, and XWayland. Python there has PySide6, evdev, Xlib, Pillow, numpy, and pytest. The user already has access to physical keyboard devices and `/dev/uinput`.
- Game directory: `~/Games/everquest-legends/drive_c/users/Public/Daybreak Game Company/Installed Games/EverQuest Legends`.
- Wine prefix: `~/Games/everquest-legends`; Lutris game ID 29. Lutris config: `~/.local/share/lutris/games/everquest-legends-1782570403.yml`.
- For graphical checks over SSH, obtain the existing desktop environment from `systemctl --user show-environment`, or an existing same-user desktop process. Select only DISPLAY, XAUTHORITY, WAYLAND_DISPLAY, XDG_RUNTIME_DIR, and DBUS_SESSION_BUS_ADDRESS; do not dump environment secrets. XAUTHORITY changes between sessions; do not hardcode a previous path.

## Implemented

- `rotation_core.py`: installed-client spell catalog parsing, learned spellbook filtering, level-specific spell profiles, level-up log tracking, settings, rotation priority, and gauge reading.
- `rotation_engine.py`: game window/focus checks, physical-input monitoring, guarded virtual keyboard input, global helper keys, preparation and combat jobs, cancellation, and log handling.
- `eql_rotation.py`: PySide6 GUI, character/level controls, spell display, gauge calibration, solo guide, and progression tab. Single-instance lock and clean signal shutdown.
- `test_rotation.py`: 89 tests. `install_launchers.py`: desktop/menu launcher installation and backed-up offline implied-healing configuration adjustment. `install_leveling_maps.py`: separate full map set with 1–50 camp overlays. `launch.sh`: entry point.
- Installed launchers: `~/Desktop/EQ Legends Solo Assist.desktop` and `~/.local/share/applications/eql-solo-assist.desktop`.
- Settings: `~/.config/eql-rotation/settings.json`. Preserve existing user configuration.

F6 prepares learned spells out of combat. F8 is ON-only for persistent combat and never begins preparation; F9 is OFF. If the bar is not ready, the UI tells the owner to use F6 or the Prepare button. One F8 press stays armed through no-target periods, kills, Escape, temporary focus loss, movement/modifier pauses, and transient interruption in the middle of a helper command. A partial helper command is cleared after focus returns before the safety check repeats. Before attacking each selected target, the helper sends `/attack off`, uses `/consider` once, and permits only a conservative leveling-mob classification at no more than player level + 1. It then waits silently until EQ logs a new owner-selected NPC instead of polling `/consider` with no target. It blocks guards, service NPCs, players, friendly reactions, unknown proper-name NPCs, and over-level mobs. F10 casts the quick heal manually. Enter, Slash, death, zoning, and F9 disarm assistance. No target selection, movement, pulling, or unattended navigation is implemented.

Preparation exports the native spellbook with `/outputfile spellbook eql-rotation-spellbook.txt`, filters for learned and level-eligible Paladin/Cleric spells, then uses `/memspellslot N ID`. Existing `LF_*` files are loot filters, not spell loadouts; do not overwrite them as spell bars. The installed client's `eqstr_us.txt` confirms `/memspellslot` syntax.

Automated healing requires calibration of the owner's red HP gauge. Mana calibration is optional. Missing/invalid HP readings disable automated healing; manual F10 remains available. Calibration is invalidated if the window dimensions change. Implied healing is intended for solo tanking while targeting an enemy, not party-healer targeting.

Live in-world checks confirmed **Legira [4 PAL/CLR]** in Butcherblock Mountains, and the saved assistant level is 4. Character and level remain owner-selectable. Level-up tracking reads new self-system log messages, ignoring historical log content and other players' chat. Existing character files include Blizz and Legira. Do not infer a later level from the old log.

## Rotation and spell choices

Default damage cadence is 10 seconds, with an optional faster 4-second cadence. Legira is currently saved at 4 seconds with smart healing and stuns on. Priority includes critical Lay on Hands, quick healing, HoT, Yaulp/proc buff, Paladin Smite ability, optional Bash, optional stun, and damage spells. Bash is saved off and is opt-in only for a shield-equipped loadout. Courage-line HP/AC buffs occupy gem 2 when a second heal is not in use. Symbols and other buff families remain manual. Automatic stance selection requires matching saved native bindings; see the current update below. The client `/stance` command changes mercenary stance and must not be used for the player stance.

Gems select learned spells from these families:

1. Echo heal from level 8, otherwise direct heal.
2. Larger direct heal once Echo is available.
3. Strike → Furor → Smite → Wrath → Retribution.
4. Ward Undead → Expulse → Dismiss → Expel → Banish.
5. Stun family; Cleric Stun can be preferred over later Paladin Cease/Desist.
6. Celestial Remedy → Celestial Health → Celestial Healing.
7. Yaulp → Yaulp II → Yaulp III.
8. Instrument of Nife → Divine Might.

Cleric Smite is a spell; Paladin Smite is a separate `/doability Smite` ability. Promised Renewal remains manual. Installed `spells_us.txt` is authoritative for current spell IDs and level requirements. Its class-level fields are 36–51, with Cleric at 37 and Paladin at 38. Values 254/255 are not player unlock levels. Some other field offsets differ from community parsers. Exact learned spell names are matched before considering rank suffixes, so Yaulp II is not mistaken for Yaulp.

## Verification already completed

- On Alienware: `python3 -m pytest -q`: **47 passed**.
- All 50 level profiles validated against the installed spell catalog with no duplicate gem IDs or invalid unlocks.
- GUI rendered and visually inspected with `QT_QPA_PLATFORM=offscreen ./launch.sh --gui-smoke-test artifacts/ui-preview.png`.
- Actual KDE/XWayland window gate initialized. With no game running, attempted command injection was blocked before sending keys; virtual input was closed and no keys remained held.
- Engine initialized on the actual desktop with no game and did not create a virtual keyboard.
- Desktop launcher installed. Do not rely on any historical process ID.
- Evidence on Alienware: `artifacts/live-validation-2026-10-17.md`, `artifacts/live-runtime-check-2026-10-17.json`, `artifacts/verification.json`, `artifacts/runtime-check.json`, `artifacts/install.json`, `artifacts/progression-1-50.json`, `artifacts/ui-preview.png`, and `artifacts/runtime.log`.
- Live in-world preparation exported 12 learned Paladin/Cleric spells and loaded gem 1 Light Healing, gem 3 Strike, gem 4 Ward Undead, and gem 7 Yaulp. The prepared marker is tied to the exact EQ PID/start time so a helper restart can restore only the same live session.
- HP and mana regions were calibrated at 2560x1600. A fresh read while the game was focused returned HP 100% and mana about 99%.
- A controlled Krag chick fight logged Strike at 21:21:49 and again at 21:21:59 before the 21:22:02 kill. Out-of-range encounters also logged repeated retries as enemies approached.
- The earlier Bash spam was reproduced and fixed. Bash is now unchecked in the live GUI, saved false, default false, and chosen only when explicitly enabled.
- F8 was verified as ON-only and can arm while EQ is unfocused. No virtual input device is created until the actual EQ window regains focus. Movement/modifier keys no longer cause F8 to be silently dropped; they pause input until released. F9 remains OFF.
- A live focus interruption during a partly typed slash command reproduced the remaining F8 disarm. The fixed path keeps `active=true`, clears the draft after focus returns, forces native attack off, and requires a fresh target check. The final live helper is loaded with this fix.
- With combat armed, a controlled live negative test selected Guard Dunn. Repeated `/consider` results reported him amiable; the helper sent no attack, spell, or damage action, remained armed, and returned to `Consider whom?` after the target was cleared. The command whitelist permits `/consider` but still rejects `/target`, so the helper cannot choose targets.
- The positive safety-gate path was then verified against owner-selected ordinary mobs without another F8 press. `/consider` admitted a decaying dwarf skeleton, goblin whelp, worker scarab, and bat; Strike fired repeatedly and combat returned to waiting after kills. The worker scarab awarded 0.727% experience, while level-1 mobs awarded 0.173%.
- The final no-target run produced exactly one `Consider whom?` over 11 seconds, confirming that `/consider` no longer repeats while waiting. EQ's `Targeted (NPC)` message now arms one fresh probe for each owner selection.
- A level-8 giant scarab was too dangerous for level-4 D3. The gate now parses the target level and blocks anything above player level + 1. This is automated-test verified and loaded live; a natural live over-level refusal after the fix is still unverified.
- Automatic low-HP logic selected Light Healing during live combat, but the cast was interrupted. F10 reached Light Healing in a later check and fizzled. Target probing is now suspended for each spell's full cast window. A completed heal through implied targeting is still unverified.
- A live UI check exposed a stale level-1 spell preview after the saved level changed to 4. The engine now invalidates preparation and recomputes the profile when the level, character, or server changes. After restarting the installed assistant, its live Combat table showed level-4 `Light Healing` in gem 1 instead of `Minor Healing`; the new regression test passes.
- A clean normal Lutris restart now reaches `CefInitialized`, loads the local loading view, and reaches `DisplayingMainScreen` / `Main screen loaded`. The final desktop was locked, so the loaded window was left running behind the lock screen.
- The separate `maps/Solo_Leveling` map set contains 233 files, 14 overlays, and 37 markers. For level 4 on D3, `Newbie_Hills_L4_Krag_Aviak` identifies same-level targets; the dwarf-skeleton marker begins at level 5 because current EQL data puts them at levels 5–7. The route also marks `GO_TO_GFAY_THEN_CRUSHBONE`, `GO_TO_CRUSHBONE`, and `START_HERE_ENTRANCE`. Stock maps were untouched. The live Map window still had `default` selected; synthetic mouse motion was stopped because the 3D view captures it. See `LEVELING_MAPS.md` and `artifacts/leveling-maps-install.json`.
- Installed client strings establish that `/stance` is the mercenary stance command. It was removed from the helper. Player stance/invocation remains a deliberate palette choice until a safe control is verified.

Do not claim a completed low-HP automatic heal or completed F10 heal is live-verified yet. Gauge input, the automatic Light Healing decision, and an F10 Light Healing attempt are verified; the observed attempts were interrupted or fizzled.

## Remaining work

1. During a safe naturally damaged fight, verify a completed automatic Light Healing through implied targeting; separately verify one completed F10 heal.
2. Verify a real level-up refresh when Legira dings and F6 reloads any newly learned upgrade.
3. Choose `Solo_Leveling` from the in-game Map window and visually confirm the marker overlay. Do not drive the game mouse automatically; prior pointer tests changed the camera.
4. Select an over-level NPC without engaging it and verify the final live helper refuses it through the player-level + 1 gate.

Avoid changing third-class assumptions, rewriting the app, or adding unattended targeting without a new owner request. Never overwrite live game INIs while the client runs.

## Existing modifications and backup

The installer changed only `UseImpliedHealing=0` to `1` in Blizz's character INI while the game was closed; Legira already had it enabled. Backup: `artifacts/Blizz_freeport_LO1.ini.before-implied-healing-20261017T203302Z`. See `artifacts/install.json`. No Wine runner, Lutris prefix, account credentials, or other game settings were changed. No autostart was installed.

The prior music helper modified `eqgame.exe`; that binary authenticated but disconnected from the world after 10–13 seconds. LaunchPad repaired the official executable, SHA-256 `de817e40ceb873651b0f17b5fdc0eb34db0190347da2f59e4d3edd0448d155ea`, which stayed connected at character select. `~/Games/everquest-legends/fix-eq-music.py` no longer rewrites the executable, and its Lutris pre-launch shell hook is now a no-op. The exact modified executable is retained only as `artifacts/eqgame.exe.before-stock-connectivity-20261017T2133Z`.

Wine-specific LaunchPad recovery is stored in `LaunchPad-user.ini`: an empty `Display/SplashScreenImageFilepath` bypasses the frozen basic splash, and `Updates/PatchSelf=false` bypasses the hanging in-process self-patch path. LaunchPad still checked its version and reported the installed official build current. A fresh CEF cache fixed the subsequent loading stall; the prior cache is preserved beside it as `LaunchPad.Cache.before-fresh-cef-test-20261017T1747`. The pre-change INI is `LaunchPad-user.ini.before-no-splash-test-20261017T1745`. The official application-updater package was restored from Daybreak's manifest. The original `ApplicationRegistry.xml` and Lutris YAML were restored after negative tests.

## References

- Installed client `spells_us.txt` and `eqstr_us.txt`.
- https://www.everquest.com/update-notes/eq-update-notes-7-20-2022
- https://github.com/ArtSabintsev/everquest-legends-mcp/blob/main/docs/local-client-extraction.md
- https://eqlwiki.com/Paladin
- https://eqlwiki.com/Cleric
- https://eqlwiki.com/Skill_Smite

## Self support fix — 2026-10-18

The owner reported low HP with F8 armed and no healing. Root cause: the entire
rotation, including beneficial spells, was gated on `target_ready is True`.
An observed level-7 orc runner was refused for level-4 Legira, which also
prevented healing. `combat_tick` now runs beneficial spells before target
probing or melee; only offensive actions require target approval. Healing
cooldowns no longer get filled with damage or buff casts. Fizzles/interruption
reset the failed action for retry. Timed buffs refresh and named buff fade
messages invalidate their once-cast marker. HP calibration was read at 57%
and matched the visible gauge; that was not a calibration failure.

New optional Courage-line buff uses vacant gem 2 until two distinct heals
need gems 1/2. Existing session-bound prepared markers restore without that
new buff, so F8 healing works immediately; F6 adds Courage. Do not fabricate
a marker for an unprepared gem. A one-second virtual-keyboard initialization
delay fixes the observed loss of first-command input before udev registration.

Stance policy: Defense at <=65% HP, Balanced again at >=85%, Divine invocation.
Uses native chords only: Ctrl+Shift+1/2/3 for Balanced/Defense/Divine. The
engine reads `eqclient.ini` KeyMaps every five seconds and enables input only
when all three saved bindings match and are not assigned to another action.
Never write the live game INI. The earlier Ctrl+Shift+F1/F2/F3 proposal hit KDE
desktop shortcuts; Defense was logged successfully but focus was lost. Those
function-key bindings must not be used by the helper. The owner replaced them with number-key chords. Saved native KeyMaps now pass
verification. A live trace confirmed Balanced and Divine; automatic low-HP
switching and the new no-target heal/buff path remain unverified.

Automated checks: 89 tests passed; Python compilation passed. Backups are in
`artifacts/before-self-support-20261017/`. Current helper unit is
`eql-solo-assist-current.service`, trace `/tmp/eql-support-runtime.jsonl`.
Earlier live log at 23:42:17 contains a completed 49 HP Light Healing, but its
source cannot be attributed to the helper, so it is not automatic-heal proof.

A further regression fix restricts Escape/Enter/slash target/chat handling to actual EQ focus. Typing replies in Codex preserves the armed state; F9 remains global. The saved number-row native bindings now match: Balanced 1610612738, Defense 1610612739, Divine 1610612740. Automatic stance input enables when the normal engine reads those settings.

Live follow-up: `/tmp/eql-live-support-validation.jsonl` records Balanced and Divine confirmation. The first validation harness incorrectly armed a restored bar after preparation failed, retaining the owner-selected goblin; out-of-range offensive attempts followed. That harness was stopped, native attack was turned off, and the target cleared. The corrected support-only harness blocks offensive commands, but aborted on focus loss before preparation; no heal/buff completion is claimed. Restore the normal GUI helper unarmed and use owner-driven F6/F8 for further live checks. Do not rerun the first harness.

## Incoming attacker / Escape fix — 2026-10-18

The owner reported two kills followed by standing idle while an add hit them.
The trace stayed `active=true`, `target_ready=false`: EQ had switched targets
without another `Targeted (NPC)` line. Incoming self-hit/miss messages now
wake one fresh `/consider` for the current target after a kill/new attacker.
They never select a target or grant permission to attack. Repeated hits from
the same attacker do not spam probes. Guards, players, and over-level targets
still require/refuse the same safety checks. Repeated F8 while waiting also
requests a fresh safety check instead of reporting ON without doing anything.
Escape during a partially typed helper command now clears it while preserving
armed combat; F9/chat/death/zoning still stop. A settings trace serialization
crash was reproduced and fixed; tracing dataclass Settings no longer kills
the engine. Damage commands recheck target permission after pumping the log
to prevent a queued attack/nuke crossing a kill/target change. Named failure
messages such as `Your Light Healing spell fizzles!` and `Your Light Healing
spell is interrupted.` now reset the failed action for retry.

Actual automatic Light Healing is now live verified: trace at 00:17:31.072
selected `/cast 1` at HP 0.0619 while `target_ready=false`; the game began
Light Healing at 00:17:31 and logged 49 HP healed on Legira at 00:17:33.
The next gauge rose to 0.2932. The level-8 orc runner later killed Legira
through multiple fizzles, stuns, and interrupted heals; do not claim the helper
can sustain that fight. New add-wakeup and Escape persistence are automated
verified and loaded, but a new natural multi-mob sequence is still pending.

Key input now allows 20 ms down plus 20 ms up instead of 8 ms down/no gap,
because live logs contained truncated/invalid helper commands. This input
timing change is loaded but its reliability improvement still needs live
observation. 89 tests and compilation pass. Current unit remains
`eql-solo-assist-current.service`. Re-arm with F8 once after reviving; no F6
is required just for this patch. Courage is still not loaded in the old bar.

Additional stance evidence: 00:15:53.690 requested Defense at HP 0.6091, confirmed at 00:15:55; 00:16:01.965 requested Balanced at HP 0.9283, confirmed at 00:16:03. Automatic HP-based stance switching is therefore live verified, separately from the new add-wakeup patch.

## Current retaliation exception — 2026-10-18

The owner explicitly asked to fight back when an orc runner attacks. This
supersedes the earlier unconditional player-level + 1 refusal for self defense.
The live trace repeatedly refused the level-7 orc runner despite incoming hits.
`safe_leveling_target(..., retaliating=True)` now permits an otherwise eligible
NPC above the level cap only when the exact considered name matches a self
hit/miss in the last 12 seconds. Known NPC identity is required for named
non-generic targets; PC/pet kinds, guard/service names, friendly reactions,
and missing target levels remain blocked. The proactive level limit remains.
Evidence expires and is cleared on stop/death/zoning or the matching kill; it
never selects a target or moves the character. Retaliatory melee starts even
when HP is low and healing remains the top spell priority, preventing continuous
healing from starving auto-attack. Spell/guard checks still apply.

F8 now retains an NPC/PC identity observed before arming but always rechecks
with /consider. If a named attacker was already selected before the helper
restarted, its NPC kind is unknown: the UI asks the owner to click it once.
Do not infer NPC kind from an unknown named player solely because it attacked.
A separate recovery fix marks a command unfinished only after a key was
successfully sent; movement that blocks the initial slash no longer triggers
an unnecessary Escape that would clear the current target.

89 tests and Python compilation passed. The final patch is loaded in the
normal `eql-solo-assist-current.service`, initially unarmed. No F6 is needed
for this patch; click the attacker once then F8 after reload/zone change.
Successful live retaliation is still UNVERIFIED. The orc encounter after the
first patch remained blocked because NPC identity was unknown; do not call
that a successful defense. A new owner-selected NPC encounter is required.
Live 00:48:43 Lay on Hands I healed Legira for 213 HP, confirming the existing
6001 activation works with the slower input. Automated healing, named fizzle
retry and HP-based stance changes have live evidence; Courage is still not
prepared on the owner's restored old bar.
