# Changelog

## 0.8.0

### New
- **Stop all output**: a hub button and `dg_lab.stop_all` action that clear operations and set intensity to 0 on every channel of every connected app. Every target is attempted even if one app fails.
- **Pulse presets**: save named waveform frame lists with `dg_lab.save_pulse_preset` and remove them with `dg_lab.delete_pulse_preset`. Each channel has a pulse preset select used by its send pulse button, and `dg_lab.send_pulse` accepts `preset` instead of `frames`. Presets are shared across entries and persist across restarts.

### Changed
- The pulse frames text entity is limited to 255 characters (Home Assistant's state limit). Use a preset for longer frame lists.
- `iot_class` is now `local_push`; `@greatmastix` is listed as code owner.
- Removed the obsolete `domains` key from `hacs.json`; fixed the repository URL in the README.

### Maintenance
- New Validate workflow (hassfest, HACS, tests) and Release workflow.
- Declared `CONFIG_SCHEMA` and fixed a racy websocket test.
