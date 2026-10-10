"""Shared pulse preset storage for the DG-LAB integration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.storage import Store

from .api import normalize_frames
from .const import DATA_PULSE_PRESETS, DOMAIN, PRESET_CUSTOM, PRESET_NAME_MAX_LENGTH

STORAGE_KEY = f"{DOMAIN}.pulse_presets"
STORAGE_VERSION = 1


class DGLabPulsePresets:
    """Named pulse frame lists shared by every DG-LAB config entry."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the preset store."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._presets: dict[str, list[Any]] = {}
        self._listeners: set[Callable[[], None]] = set()

    async def async_load(self) -> None:
        """Load stored presets, ignoring malformed entries."""
        data = await self._store.async_load() or {}
        presets = data.get("presets", {})
        if not isinstance(presets, dict):
            return
        self._presets = {
            name: preset["frames"]
            for name, preset in presets.items()
            if isinstance(name, str)
            and isinstance(preset, dict)
            and isinstance(preset.get("frames"), list)
            and preset["frames"]
        }

    @property
    def names(self) -> list[str]:
        """Return preset names in display order."""
        return sorted(self._presets, key=str.casefold)

    def get(self, name: str) -> list[Any]:
        """Return the frames for a preset or raise a validation error."""
        frames = self._presets.get(name)
        if frames is None:
            raise ServiceValidationError(f"Unknown DG-LAB pulse preset: {name}")
        return list(frames)

    async def async_save(self, name: str, frames: Any) -> None:
        """Create or replace a preset."""
        name = _validate_name(name)
        self._presets[name] = normalize_frames(frames)
        await self._async_write()

    async def async_delete(self, name: str) -> None:
        """Delete a preset."""
        if name not in self._presets:
            raise ServiceValidationError(f"Unknown DG-LAB pulse preset: {name}")
        del self._presets[name]
        await self._async_write()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Listen for preset changes."""
        self._listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    async def _async_write(self) -> None:
        """Persist presets and notify listeners."""
        await self._store.async_save(
            {"presets": {name: {"frames": frames} for name, frames in self._presets.items()}}
        )
        for listener in list(self._listeners):
            listener()


def _validate_name(name: str) -> str:
    """Return a normalized preset name."""
    name = name.strip()
    if not name:
        raise ServiceValidationError("Pulse preset name cannot be empty")
    if name == PRESET_CUSTOM:
        raise ServiceValidationError(f"{PRESET_CUSTOM!r} is a reserved preset name")
    if len(name) > PRESET_NAME_MAX_LENGTH:
        raise ServiceValidationError(
            f"Pulse preset name cannot exceed {PRESET_NAME_MAX_LENGTH} characters"
        )
    return name


def pulse_presets(hass: HomeAssistant) -> DGLabPulsePresets:
    """Return the loaded preset store."""
    return hass.data[DATA_PULSE_PRESETS]
