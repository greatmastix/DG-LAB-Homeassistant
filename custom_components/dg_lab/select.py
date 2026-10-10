"""Select platform for DG-LAB pulse presets."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.restore_state import RestoreEntity

from .api import DGLabChannelSettings, DGLabClient, channel_name
from .const import DOMAIN, PRESET_CUSTOM
from .entity import (
    DGLabChannelEntity,
    iter_connected_devices,
    iter_device_channels,
    remove_stale_entities,
)
from .presets import DGLabPulsePresets, pulse_presets


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[list[SelectEntity]], None],
) -> None:
    """Set up DG-LAB select entities."""
    client: DGLabClient = hass.data[DOMAIN][entry.entry_id]
    presets = pulse_presets(hass)
    seen: dict[tuple[Any, ...], str] = {}

    @callback
    def discover_entities() -> None:
        entities: list[SelectEntity] = []
        current: set[tuple[Any, ...]] = set()
        for device in iter_connected_devices(client):
            for channel in iter_device_channels(device):
                key = (device.client_id, device.slot_id, channel, "pulse_preset")
                current.add(key)
                if key in seen:
                    continue
                entity = DGLabPulsePresetSelect(
                    client, presets, device.client_id, device.slot_id, channel
                )
                assert entity.unique_id is not None
                seen[key] = entity.unique_id
                entities.append(entity)
        remove_stale_entities(hass, Platform.SELECT, seen, current)
        if entities:
            async_add_entities(entities)

    discover_entities()
    entry.async_on_unload(client.async_add_listener(discover_entities))


class DGLabPulsePresetSelect(DGLabChannelEntity, SelectEntity, RestoreEntity):
    """Choose the frames the channel send-pulse button uses."""

    _attr_icon = "mdi:waveform"

    def __init__(
        self,
        client: DGLabClient,
        presets: DGLabPulsePresets,
        client_id: str,
        slot_id: str,
        channel: int,
    ) -> None:
        """Initialize the select."""
        super().__init__(client, client_id, slot_id, channel, "pulse_preset")
        self.presets = presets
        self._attr_name = f"{channel_name(channel)} pulse preset"

    async def async_added_to_hass(self) -> None:
        """Restore the selected preset and follow preset changes."""
        await super().async_added_to_hass()
        self.async_on_remove(self.presets.async_add_listener(self._handle_update))
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self.presets.names:
            self._setting.pulse_preset = last_state.state

    @property
    def _setting(self) -> DGLabChannelSettings:
        """Return the channel helper settings."""
        return self.client.channel_setting(self.client_id, self.slot_id, self.channel)

    @property
    def options(self) -> list[str]:
        """Return the custom-frames option followed by stored presets."""
        return [PRESET_CUSTOM, *self.presets.names]

    @property
    def current_option(self) -> str:
        """Return the active preset, falling back when it was deleted."""
        preset = self._setting.pulse_preset
        if preset is None or preset not in self.presets.names:
            return PRESET_CUSTOM
        return preset

    async def async_select_option(self, option: str) -> None:
        """Select a preset or the channel's custom frames."""
        self._setting.pulse_preset = None if option == PRESET_CUSTOM else option
        self.async_write_ha_state()
