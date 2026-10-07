---
name: blender
description: Blender scenes, camera animation and clay-motion previs; control the user's open Blender session, capture review frames and iteratively fix scenes with them.
---

# Blender

Use `bpy` for geometry, named collections, keyframes and camera rigs. The user is learning Blender: explain the relevant control briefly, work one requested step at a time, and let them review in the UI. Do not push ahead into a full production or polished render.

## Live connection

- Source: `~/Documents/gski/gski/blender/`. `startup.py` is a standalone Blender startup module; `__init__.py` supplies the `gski blender` client.
- Dotfiles `.local/link-cfgs` links the module into installed Blender versions' `scripts/startup/gski_bridge.py`. Restart Blender once after installation. Background Blender does not start a bridge.
- After a Blender version upgrade, rerun the linker after its version directory exists. To disable autostart, remove that version's `gski_bridge.py` symlink and restart Blender; do not delete the source or user preferences.
- `gski blender sessions` lists socket paths, not confirmed live sessions. `gski blender --pid PID info` checks the scene, file, frame and selection. Always identify the right session before editing; never guess between windows.
- Write a small Python patch in the scene's working folder, then send it with `gski blender --pid PID exec /absolute/path/patch.py`. Code runs in the UI's main thread; use the data API rather than context-dependent operators where possible. Each request has a fresh namespace, but scene changes persist.
- Unix sockets live in `$XDG_RUNTIME_DIR/gski-blender-UID/` (fallback `/tmp`), with owner-only permissions. This executes arbitrary Python as the user, not sandboxed code. Never expose it to the network or execute untrusted downloaded code.
- No automatic saving or rollback. Exceptions can leave partial changes. A timeout does not cancel execution: inspect before retrying. Long commands block the UI. Loading files or resetting Blender should be a separate explicit step.

## Edit → inspect → review

1. Inspect the live scene before changing it. Preserve manual edits; never rebuild or overwrite the scene just to adjust a camera or shading. Save a checkpoint before destructive changes, with the user's agreement.
2. Patch only the requested objects/frames. Keep meaningful names and separate environment, action and camera collections. Use deterministic keyframes, not real-time simulation.
3. Capture with `gski blender --pid PID --timeout 60 capture /absolute/path/frame.png --frame 60`. The output directory must exist. This renders the active camera with Workbench at 960px width, preserves aspect ratio and restores frame/render settings. It briefly blocks the UI; it is not a UI screenshot. Open the PNG with the image-reading tool and check framing, occlusion and continuity. Review start/middle/end for motion changes; a still cannot verify timing.
4. Report what changed and which frame/object to review. Help the user correct it in Blender; do not merely send a file and ask whether it works. If they ask only for explanation, do not edit anything.

## Blender essentials

- `MainCamera` is the viewpoint; a target Empty is the look-at point. `Track To` uses camera local `-Z`, up `Y`. Move the camera for viewpoint, the target for aim. Manual camera rotation/walk navigation conflicts with an active tracking constraint.
- At the desired frame, edit Location and insert its keyframe (hover over Location and press `I`). Without a new key, scrubbing restores the animation. Graph Editor exposes X/Y/Z curves and easing; Dope Sheet edits timing. Motion Paths visualize travel in 3D.
- Without a numpad: `View → Viewpoint → Camera`. `F3` searches operators. Switch editors using their type selector; shortcuts act on the editor under the pointer.
- Solid viewport shading (`space.shading`) and Workbench render shading (`scene.display.shading`) are separate. Configure both. Use material diffuse colors plus `color_type='MATERIAL'`, studio light, cavity and shadows for readable clay references. Wire display and alpha do not guarantee transparent renders.
- Blender uses Z-up. Explicitly choose scene scale and coordinate conversions. Keep previews lightweight; use 768–960px frames. Do not promise fixed rendering speed. Benchmark before long exports; use a separate background process with inherited two-CPU affinity and low priority, not a long live-UI command.
- Save via `Ctrl+S` when agreed. `F3 → Revert` discards unsaved changes; it is unnecessary for live patches. The open scene is the source of truth during manual review.
- UI shortcuts: `~` camera/pie, `Space` play/pause, `N` sidebar/transforms, `G` move (`G,Z,Z` dolly), `I` keyframe, `Alt+I`/`X` delete key, `Shift+S` snap, `Shift+Tab` magnet, `F3` search. Detailed notes: `docs/blender-hints.md`.

