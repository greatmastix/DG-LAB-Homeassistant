"""Tests for the emergency stop and saved pulse presets."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.dg_lab.api import (
    DGLabApp,
    DGLabClient,
    DGLabDevice,
    DGLabNotConnectedError,
)
from custom_components.dg_lab.button import DGLabSendPulseButton
from custom_components.dg_lab.const import (
    CONF_MAX_INTENSITY,
    DATA_PULSE_PRESETS,
    DEVICE_TYPE_BMTR,
    DEVICE_TYPE_OVC,
    PRESET_CUSTOM,
)
from custom_components.dg_lab.presets import DGLabPulsePresets
from custom_components.dg_lab.select import DGLabPulsePresetSelect


def make_client() -> DGLabClient:
    """Create a client with the Home Assistant surface these tests need."""
    hass = SimpleNamespace(
        bus=SimpleNamespace(async_fire=lambda *_args, **_kwargs: None)
    )
    entry = SimpleNamespace(
        entry_id="test-entry",
        title="DG-LAB",
        data={},
        options={CONF_MAX_INTENSITY: 100},
    )
    return DGLabClient(hass, entry)


def add_device(
    client: DGLabClient, client_id: str, slot_id: str, device_type: str
) -> None:
    """Attach an app with one connected device."""
    client.apps.setdefault(client_id, DGLabApp(client_id=client_id, connected=True))
    client.devices[(client_id, slot_id)] = DGLabDevice(
        client_id=client_id, slot_id=slot_id, type=device_type
    )


class FakeStore:
    """In-memory replacement for Home Assistant storage."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        """Initialize the store."""
        self.data = data
        self.saved: list[dict[str, Any]] = []

    async def async_load(self) -> dict[str, Any] | None:
        """Return stored data."""
        return self.data

    async def async_save(self, data: dict[str, Any]) -> None:
        """Record saved data."""
        self.saved.append(data)
        self.data = data


def make_presets(data: dict[str, Any] | None = None) -> tuple[DGLabPulsePresets, FakeStore]:
    """Create a preset store backed by memory."""
    store = FakeStore(data)
    with patch("custom_components.dg_lab.presets.Store", return_value=store):
        presets = DGLabPulsePresets(Mock())
    return presets, store


class StopAllTest(unittest.IsolatedAsyncioTestCase):
    """Check the emergency stop reaches every connected channel."""

    async def test_clears_and_zeroes_every_connected_channel(self) -> None:
        """Every app is cleared and every controllable channel is reset."""
        client = make_client()
        add_device(client, "app-1", "slot-a", DEVICE_TYPE_OVC)
        add_device(client, "app-2", "slot-b", DEVICE_TYPE_OVC)
        add_device(client, "app-2", "civet", DEVICE_TYPE_BMTR)
        client.apps["app-3"] = DGLabApp(client_id="app-3", connected=False)
        client.send_rpc = AsyncMock(return_value={})

        await client.stop_all()

        requests = [
            (call.args[0], call.args[1]["m"], call.args[1].get("data"))
            for call in client.send_rpc.await_args_list
        ]
        self.assertIn(("app-1", "device.op.clear", None), requests)
        self.assertIn(("app-2", "device.op.clear", None), requests)
        resets = {
            (client_id, data["s"], data["c"])
            for client_id, method, data in requests
            if method == "device.op"
        }
        self.assertEqual(
            resets,
            {
                ("app-1", "slot-a", 0),
                ("app-1", "slot-a", 1),
                ("app-2", "slot-b", 0),
                ("app-2", "slot-b", 1),
            },
        )
        for client_id, method, data in requests:
            if method == "device.op":
                self.assertEqual(data["v"], 0)
                self.assertTrue(data["im"])
        self.assertNotIn("app-3", {client_id for client_id, _, _ in requests})

    async def test_failure_does_not_stop_remaining_targets(self) -> None:
        """A failing app is reported after every other target was attempted."""
        client = make_client()
        add_device(client, "app-1", "slot-a", DEVICE_TYPE_OVC)
        add_device(client, "app-2", "slot-b", DEVICE_TYPE_OVC)

        async def send_rpc(client_id: str, *_args: Any, **_kwargs: Any) -> Any:
            if client_id == "app-1":
                raise DGLabNotConnectedError("gone")
            return {}

        client.send_rpc = AsyncMock(side_effect=send_rpc)

        with self.assertRaisesRegex(HomeAssistantError, "app-1"):
            await client.stop_all()

        app_2_calls = [
            call for call in client.send_rpc.await_args_list if call.args[0] == "app-2"
        ]
        self.assertEqual(len(app_2_calls), 3)

    async def test_without_connected_apps_is_a_no_op(self) -> None:
        """Nothing is sent when no app is connected."""
        client = make_client()
        client.send_rpc = AsyncMock()

        await client.stop_all()

        client.send_rpc.assert_not_awaited()


class PulsePresetStoreTest(unittest.IsolatedAsyncioTestCase):
    """Check preset persistence and validation."""

    async def test_save_normalizes_frames_and_notifies(self) -> None:
        """Comma-separated frames are stored as a list."""
        presets, store = make_presets()
        listener = Mock()
        presets.async_add_listener(listener)

        await presets.async_save("  Wave  ", "aa, bb\ncc")

        self.assertEqual(presets.names, ["Wave"])
        self.assertEqual(presets.get("Wave"), ["aa", "bb", "cc"])
        self.assertEqual(store.data, {"presets": {"Wave": {"frames": ["aa", "bb", "cc"]}}})
        listener.assert_called_once()

    async def test_invalid_names_are_rejected(self) -> None:
        """Empty, reserved, and over-long names are refused."""
        presets, store = make_presets()
        for name in ("   ", PRESET_CUSTOM, "x" * 65):
            with self.subTest(name=name), self.assertRaises(ServiceValidationError):
                await presets.async_save(name, ["aa"])
        self.assertEqual(store.saved, [])

    async def test_load_skips_malformed_entries(self) -> None:
        """Only presets with a non-empty frame list survive loading."""
        presets, _store = make_presets(
            {
                "presets": {
                    "good": {"frames": ["aa"]},
                    "empty": {"frames": []},
                    "wrong": {"frames": "aa"},
                    "bad": "aa",
                }
            }
        )

        await presets.async_load()

        self.assertEqual(presets.names, ["good"])

    async def test_delete_and_unknown_names(self) -> None:
        """Deleting removes a preset; unknown names raise validation errors."""
        presets, _store = make_presets()
        await presets.async_save("Wave", ["aa"])

        await presets.async_delete("Wave")

        self.assertEqual(presets.names, [])
        with self.assertRaises(ServiceValidationError):
            presets.get("Wave")
        with self.assertRaises(ServiceValidationError):
            await presets.async_delete("Wave")


class PulsePresetEntityTest(unittest.IsolatedAsyncioTestCase):
    """Check the preset select and send-pulse button work together."""

    async def asyncSetUp(self) -> None:
        """Create a client, device, and preset store."""
        self.client = make_client()
        add_device(self.client, "app", "slot", DEVICE_TYPE_OVC)
        self.client.send_rpc = AsyncMock(return_value={})
        self.presets, _store = make_presets()
        await self.presets.async_save("Wave", ["aa", "bb"])
        self.hass = SimpleNamespace(data={DATA_PULSE_PRESETS: self.presets})
        self.select = DGLabPulsePresetSelect(self.client, self.presets, "app", "slot", 0)
        self.select.async_write_ha_state = Mock()
        self.button = DGLabSendPulseButton(self.client, "app", "slot", 0)
        self.button.hass = self.hass
        self.setting = self.client.channel_setting("app", "slot", 0)
        self.setting.pulse_frames = "cc"

    async def test_custom_frames_are_sent_by_default(self) -> None:
        """Without a selected preset the text entity frames are used."""
        self.assertEqual(self.select.options, [PRESET_CUSTOM, "Wave"])
        self.assertEqual(self.select.current_option, PRESET_CUSTOM)

        await self.button.async_press()

        self.assertEqual(self.client.send_rpc.await_args.args[1]["data"]["v"], ["cc"])

    async def test_selected_preset_is_sent(self) -> None:
        """Selecting a preset makes the button send its frames."""
        await self.select.async_select_option("Wave")

        await self.button.async_press()

        self.assertEqual(self.select.current_option, "Wave")
        self.assertEqual(
            self.client.send_rpc.await_args.args[1]["data"]["v"], ["aa", "bb"]
        )

    async def test_deleted_preset_falls_back_to_custom_frames(self) -> None:
        """Removing the selected preset reverts the channel to its own frames."""
        await self.select.async_select_option("Wave")
        await self.presets.async_delete("Wave")

        await self.button.async_press()

        self.assertEqual(self.select.current_option, PRESET_CUSTOM)
        self.assertEqual(self.client.send_rpc.await_args.args[1]["data"]["v"], ["cc"])


if __name__ == "__main__":
    unittest.main()
