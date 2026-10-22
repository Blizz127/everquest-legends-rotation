# Solo leveling map set

The installed **Solo_Leveling** map set adds 37 bright lime camp labels to 14
zone overlays. It is separate from the stock map set, so the original game maps
remain unchanged.

Open the in-game Map window and choose **Solo_Leveling** from the map-set
dropdown. Labels use the form `L04-10_Camp_Name`. `ALT` marks an alternate
route; `HARD` and `HIGH_RISK` call out camps that need better gear or careful
pulls. The helper does not move, target, or pull for you.

At level 4 on D3 in Butcherblock, stay by the lime
`L01-04_Newbie_Hills_L4_Krag_Aviak` marker and select level-4 Krag chicks or
aviak chicks; level 3–5 large snakes are also appropriate. The dwarf skeletons
are level 5–7, so their marker now begins at level 5. For the dungeon route,
follow `L04-10_GO_TO_GFAY_THEN_CRUSHBONE`, then
`L04-10_GO_TO_CRUSHBONE` in Greater Faydark. Inside Crushbone, start at
`L04-07_START_HERE_ENTRANCE`.

## Recommended PAL/CLR route

| Level | Zone and camp |
|---|---|
| 1–4 | Butcherblock — Kaladim newbie hills |
| 4–7 | Crushbone — entrance |
| 7–10 | Crushbone — slave mines |
| 10–16 | Unrest — courtyard |
| 16–22 | Unrest — first floor |
| 22–25 | Unrest — basement and back rooms |
| 25–32 | Lower Guk — bedroom and spider room |
| 32–40 | Lower Guk — undead camps near reanimated hand |
| 38–42 | Lower Guk — assassin and supplier area |
| 40–44 | The Hole — entrance and castle |
| 42–46 | The Hole — sword, slab, and docks |
| 45–50 | The Hole — undead tower; hard, but well suited to PAL/CLR |

The map also marks alternatives in Greater Faydark, Mistmoore, Upper Guk,
Solusek's Eye, Nagafen's Lair, Ocean of Tears, Plane of Hate, and Plane of Fear.
The overlapping ranges are intentional so you can move when a camp is busy or
too difficult.

## Installation record

- Folder: `<EverQuest Legends>/maps/Solo_Leveling`
- Base map files copied: current installed client maps
- Overlay files: 14 `*_3.txt` files
- Markers: 37
- Installed tree SHA-256:
  `1f6e30dcc2ac9ee6be87a88dd8753d92874874603a5f4cc7ca4a2a02bd0aca81`
- Machine-readable record: `artifacts/leveling-maps-install.json`

Re-run `python3 install_leveling_maps.py` after replacing or updating the base
maps. The installer builds the replacement map set in a temporary directory and
backs up an existing `Solo_Leveling` folder before swapping it in.

Route references:

- https://eqlbuildforge.com/leveling/
- https://www.everquestguides.com/everquest-leveling/everquest-legends-leveling-guide-1-50-and-strategy/
- https://eqlsource.com/dungeons/thehole
- https://wiki.project1999.com/Hole
- https://norrathcartographers.com/help.html
