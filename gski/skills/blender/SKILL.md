---
name: blender
description: Blender scenes, camera animation and clay-motion previs; control the user's open Blender session, capture review frames and iteratively fix scenes with them.
---

# Blender

Use `bpy` for geometry, collections, keyframes and camera rigs. 

## Live connection

- `gski blender info` prints the file (relative to the current folder), unsaved flag, frame, range, active camera and selection.
- `gski blender exec -c 'import bpy; print(bpy.context.scene.name)'` runs Python inside Blender; stdout comes back. Default for short patches and queries. For longer ones, `gski blender exec patch.py`.
- `gski blender capture renders/cam.png --frame 1 60 121` renders review frames. Paths resolve from the current folder; keep patches and renders in the project folder.
- The client finds the live session and drops stale sockets. Pass `--pid PID` only when it reports several sessions.
- Patches run in the UI's main thread with a fresh namespace; scene changes persist. Use the data API rather than context-dependent operators.
- No automatic saving or rollback. Exceptions can leave partial changes. A timeout does not cancel execution; check state before retrying. Loading files or resetting Blender is a separate explicit step.
- This executes arbitrary Python as the user: never expose the socket to the network or run untrusted code.

## Examples

```
gski blender info
gski blender exec -c 'import bpy; o = bpy.data.objects["Cam"]; o.location.x = 2; o.keyframe_insert("location", frame=60); print("Cam location.x 2 @60")'
gski blender exec patch.py
gski blender --timeout 60 capture renders/cam.png --frame 1 60 121
```

`--timeout` goes before the subcommand.

## Flow

1. Run `info` once at the start of the task and reuse it. Run it again only when the user says they changed something in the UI, or after a failed or timed-out command.
2. Before editing, the patch prints only the current values it will change. No scene dumps.
3. Patch only the requested objects and frames. Preserve manual edits; never rebuild the scene for a local change. Save a checkpoint before destructive changes, with the user's agreement. Use meaningful names and collections, and deterministic keyframes, not simulation.
4. Patches print a one-line confirmation per change: object, property, frame if keyed, new value. Nothing else.
5. Capture all needed frames in one call (max 12). Several frames write `cam_0001.png`, `cam_0060.png`, ... plus `cam_grid.png`, a labelled contact sheet within 1600px; a single frame writes just `cam.png`. Renders the active camera with Workbench at 960px, restores settings, silent on success, blocks the UI briefly; add `--timeout 60` for many frames. Review by opening only the grid; open an individual frame only when a tile is too small to judge. Check framing, occlusion, continuity. Stills cannot verify timing.
6. Report what changed and which frame/object to review. Help the user correct it in Blender. If they ask only for explanation, do not edit or capture.

## Blender essentials

- A typical camera rig is a camera plus a target Empty with a `Track To` constraint (camera local `-Z`, up `Y`). Move the camera for viewpoint, the target for aim. Manual camera rotation or walk navigation conflicts with an active tracking constraint.
- At the desired frame, edit Location and insert its keyframe (hover over Location and press `I`). Without a new key, scrubbing restores the animation. Graph Editor exposes X/Y/Z curves and easing; Dope Sheet edits timing. Motion Paths visualize travel in 3D.
- Without a numpad: `View → Viewpoint → Camera`. Shortcuts act on the editor under the pointer.
- Solid viewport shading (`space.shading`) and Workbench render shading (`scene.display.shading`) are separate; configure both. For readable clay references use material diffuse colors with `color_type='MATERIAL'`, studio light, cavity and shadows. Wire display and alpha do not guarantee transparent renders.
- Blender is Z-up. Choose scene scale and coordinate conversions explicitly. Do not promise render speed. Benchmark before long exports and run them as a separate low-priority background process, never as a long live-UI command.
- Save with `Ctrl+S` when agreed. The open scene is the source of truth during review; live patches never need `F3 → Revert`.
- UI shortcuts: `~` view pie, `Space` play/pause, `N` sidebar/transforms, `G` move (`G,Z,Z` dolly), `I` keyframe, `Alt+I`/`X` delete key, `Shift+S` snap, `Shift+Tab` magnet, `F3` operator search.

## Setup

- Source: `~/Documents/gski/gski/blender/`. `startup.py` runs inside Blender as the bridge; `__init__.py` is the `gski blender` client.
- `~/Documents/dotfiles/.local/link-cfgs` links `startup.py` into each Blender version's `scripts/startup/gski_bridge.py`. Background Blender starts no bridge.
