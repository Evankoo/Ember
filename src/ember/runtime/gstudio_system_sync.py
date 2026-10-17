"""Compatibility name for an optional, privately deployed integration."""
from ..integrations import load_runtime_extension

_module = load_runtime_extension('gstudio_system_sync')
if __name__ == "__main__":
    raise SystemExit(_module.main())
