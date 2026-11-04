# Changelog

## 1.0.0

- **Updates from GitHub**: only changed files are downloaded and removed files are deleted. Library and ffmpeg are kept
  - In Nuke: **DMB Tools → Asset Manager Updates...**
  - The Asset Manager window shows an **Update** button when a newer version is available. It checks at most every 6 hours
  - Installer: **Update from GitHub** button, which also works as a fresh install without the ZIP
- Menu moved to **DMB Tools** in the top menu bar
- The installer replaces older Asset Manager blocks in `menu.py`, with a backup first
- The installer shows the version on GitHub next to the installed one
- Nodes are created through TCL, so the plugin works on Nuke Indie without hitting the Python node limit
- The plugin loads only when its menu item is clicked, so Nuke starts with no extra cost
- New interface: sidebar with a folder tree, card grid, list view, one-line info bar
- Thumbnails are generated in parallel in the background, with a progress bar
- Hover scrub builds all preview frames with one ffmpeg run per clip, on its own queue
- Image sequences keep their real separator (`name_0001.png` → `name_%04d.png`). A single numbered image is no longer treated as a sequence
- New "Images" category for PNG and JPG
- Missing files are marked and can be removed from the library
- Window, layout, view mode and thumbnail size are remembered
- No longer depends on Pillow; only Qt and ffmpeg are used
- Colorspace and premultiplied are left to Nuke's own rules
- Fixed: rescanning a folder failed silently and could wipe notes and tags
- Fixed: drag and drop no longer captures every file dropped into Nuke
- Quiet log: set `ASSET_MANAGER_DEBUG=1` for details
- `install.pyw` checks the machine, installs or updates, downloads ffmpeg and adds the menu entry once
