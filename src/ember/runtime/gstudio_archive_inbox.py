"""Legacy import alias; implementation lives under the Ember name."""
import importlib as _importlib
import sys as _sys
_module = _importlib.import_module("." + 'ember_archive_inbox', __package__)
if __name__ == "__main__":
    raise SystemExit(_module.main())
_sys.modules[__name__] = _module
