"""Load the ``pixelhq`` directory once per process as the package ``pixelhq_plugin``.

Hermes imports the plugin entry points (``__init__.py``, ``dashboard/plugin_api.py``) by file path, so
sibling modules cannot be imported by name without touching ``sys.path`` — and generic names such as
``config`` or ``common`` would collide with other plugins in the same process. This helper gives every
module of the plugin one private, unique namespace instead and imports all of them eagerly, so a running
process never mixes modules from two different versions of the files on disk. Files updated afterwards
take effect only after the process restarts.

Entry points load this file by path (see their ``_loader()``): each builds the module completely and
publishes it with ``sys.modules.setdefault("pixelhq_plugin_loader", candidate)``, so concurrent first imports
end up with one instance and therefore one ``_LOCK``. ``load()`` holds that lock for the whole load and marks
the package as ready only after every module is imported.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
from pathlib import Path

PACKAGE = "pixelhq_plugin"
READY = "_pixelhq_ready"  # set on the package only after every module has been imported
_LOCK = threading.Lock()


def _discard() -> None:
    for name in [n for n in sys.modules if n == PACKAGE or n.startswith(PACKAGE + ".")]:
        del sys.modules[name]


def load():
    """Return the package ``pixelhq_plugin``; the first call executes every module, later calls reuse it.

    The lock is held for the whole load and a package is never returned without its ready marker: a leftover
    without the marker (an interrupted load) is discarded and loaded again.
    """
    with _LOCK:
        package = sys.modules.get(PACKAGE)
        if package is not None and getattr(package, READY, False):
            return package
        _discard()
        directory = Path(__file__).resolve().parent / "pixelhq"
        spec = importlib.util.spec_from_file_location(
            PACKAGE, directory / "__init__.py", submodule_search_locations=[str(directory)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = package
        try:
            spec.loader.exec_module(package)
            for path in sorted(directory.glob("*.py")):
                if not path.stem.startswith("_"):
                    importlib.import_module(f"{PACKAGE}.{path.stem}")
            setattr(package, READY, True)
        except BaseException:
            _discard()
            raise
        return package


def module(name: str):
    """One module of the loaded package, e.g. ``module("collect")``."""
    return importlib.import_module(f"{load().__name__}.{name}")
