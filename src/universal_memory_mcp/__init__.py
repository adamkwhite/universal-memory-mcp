"""Universal Memory MCP — searchable local storage for AI conversation history.

Everything lives under this single package so the built wheel installs exactly
one top-level name. Before #225 the modules sat loose in ``src/``, which meant
``setuptools.packages.find`` skipped them entirely (it collects directories with
``__init__.py``, not stray files) — the wheel shipped without the application,
while claiming ``importers``/``exporters``/``schemas`` as top-level names.
"""

__version__ = "0.1.2"
