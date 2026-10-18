"""Canonical Ember environment names accept legacy inputs without changing them."""
import os

def env(name, default=None):
    canonical = name.replace("GSTUDIO_", "EMBER_", 1)
    legacy = name.replace("EMBER_", "GSTUDIO_", 1)
    return os.environ.get(canonical, os.environ.get(legacy, default))
