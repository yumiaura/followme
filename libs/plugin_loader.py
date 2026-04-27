#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load and execute followme plugins."""

from __future__ import annotations

import importlib.util
import logging
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any


PluginCallback = Callable[[dict[str, Any]], None]
PluginOnLoad = Callable[[dict[str, Any]], None]

logger = logging.getLogger(__name__)


def load_module_from_path(plugin_path: Path) -> Any | None:
    """Load Python module from plugin path."""
    module_name = f"followme_plugin_{plugin_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_path)
    if spec is None or spec.loader is None:
        logger.warning(f"Cannot load plugin spec: {plugin_path}")
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.warning(
            f"Plugin import failed {plugin_path}: {type(exc).__name__}: {str(exc)}\n"
            f"{traceback.format_exc()}"
        )
        return None
    return module


def load_plugin_callbacks(plugins_dir: Path, runtime: dict[str, Any] | None = None) -> list[PluginCallback]:
    """Load callbacks from plugins directory."""
    callbacks: list[PluginCallback] = []
    if not plugins_dir.is_dir():
        logger.info(f"Plugin directory not found: {plugins_dir}")
        return callbacks
    for plugin_path in sorted(plugins_dir.glob("*.py")):
        if plugin_path.name == "__init__.py":
            continue
        module = load_module_from_path(plugin_path)
        if module is None:
            continue
        callback = getattr(module, "callback", None)
        if not callable(callback):
            logger.info(f"Plugin has no callback: {plugin_path.name}")
            continue
        callbacks.append(callback)
        logger.info(f"Loaded plugin callback: {plugin_path.name}")
        on_load: PluginOnLoad | None = getattr(module, "on_load", None)
        if callable(on_load):
            try:
                on_load(runtime or {})
            except Exception as exc:
                logger.warning(
                    f"Plugin on_load failed {plugin_path.name}: {type(exc).__name__}: {str(exc)}\n"
                    f"{traceback.format_exc()}"
                )
    return callbacks


def run_plugin_callbacks(
    callbacks: list[PluginCallback],
    payload: dict[str, Any],
) -> None:
    """Run all plugin callbacks for analysis result."""
    for callback in callbacks:
        try:
            callback(payload)
        except Exception as exc:
            logger.warning(
                f"Plugin callback failed: {type(exc).__name__}: {str(exc)}\n"
                f"{traceback.format_exc()}"
            )


def main() -> None:
    """Module entrypoint placeholder."""
    pass


if __name__ == "__main__":
    main()
