"""Sphinx configuration for the CP2K-FORGE documentation."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

project = "CP2K-FORGE"
author = "Dhruv Sharma"
copyright = "2026, Dhruv Sharma"
release = "0.1.0"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
]

source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

myst_enable_extensions = ["colon_fence", "deflist", "fieldlist", "html_image"]
myst_heading_anchors = 4

autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "show-inheritance": True,
}
autodoc_typehints = "description"
autodoc_preserve_defaults = True

html_theme = "furo"
html_title = "CP2K-FORGE"
html_baseurl = "https://www.dhruvs.com/cp2k-forge/"
html_static_path = ["_static"]
html_css_files = ["academic.css"]
html_favicon = "_static/favicon.svg"
html_theme_options = {
    "light_logo": "forge-mark-light.svg",
    "dark_logo": "forge-mark-dark.svg",
    "sidebar_hide_name": False,
    "source_repository": "https://github.com/DhruvSkyy/cp2k-forge/",
    "source_branch": "main",
    "source_directory": "docs/",
}

html_show_sphinx = False
html_show_sourcelink = False

copybutton_prompt_text = r">>> |\.\.\. |\$ "
copybutton_prompt_is_regexp = True
