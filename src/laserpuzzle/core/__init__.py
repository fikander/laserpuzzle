"""Shared building blocks used by every generator.

- params:   typed parameter declarations (drive both CLI and UI forms)
- design:   Part / Hardware / Design data model (2D outline + 3D placement)
- geometry: shapely helpers (sections, cleanup, kerf)
- mesh:     loading + normalising 3D models
- font:     single-stroke vector font for engraved labels
- layout:   nesting parts onto sheets
- export:   SVG / DXF writers
- validate: 3D collision check between parts
"""
