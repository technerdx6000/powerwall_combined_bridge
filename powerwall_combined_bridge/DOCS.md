# Powerwall Combined Bridge

This add-on exposes a single JSON endpoint that combines:

- House A Tesla Powerwall data via direct signed `v1r`
- House B Tesla Powerwall data via direct signed `v1r`
- An optional Shelly Gen2/Gen3 Energy Meter on the grid side

The endpoint is served on:

- `http://homeassistant.local:8676/status`

## What you need

1. A verified RSA private key for direct Powerwall `v1r` access.
2. The correct host and DIN mapping for each Powerwall.
3. Optionally, the Shelly meter base URL and credentials.

## RSA key placement

`/config` is an internal container path, not something you browse directly in the Home Assistant UI.

This add-on maps the Home Assistant add-on config folder into the container as `/config`.

If you want to provide the key as a file, place your verified private key in the add-on config folder on the Home Assistant host and keep the default option `rsa_key_path: /config/tedapi_rsa_private.pem`.

For GitHub-installed add-ons, the host-side folder is:

- `/addon_configs/<repository_id>_powerwall_combined_bridge/`

For local add-ons, the host-side folder is:

- `/addon_configs/local_powerwall_combined_bridge/tedapi_rsa_private.pem`

Inside the add-on container, this is available at:

- `/config/tedapi_rsa_private.pem`

The default option `rsa_key_path` already points there.

If you do not want to manage a host-side file, you can instead paste the base64-encoded private key into the add-on option `rsa_private_key_base64`. The add-on will decode it into its persistent `/data` volume automatically at startup and use that copy instead.

## Default Powerwall mapping

- House A: `192.168.1.68` with DIN `1707000-30-K--TG124347001PEX`
- House B: `192.168.1.59` with DIN `1707000-30-K--TG1243480014GF`

## Shelly meter

If you enable the Shelly section, the add-on will call:

- `Shelly.GetDeviceInfo`
- `EM.GetStatus?id=0`

The combined `totals.grid_w` value will then come from the Shelly `total_act_power` field instead of the Powerwall site sum.

## Home Assistant integration

This add-on now ships with a native Home Assistant custom integration payload and installs it into Home Assistant's `custom_components` directory automatically on add-on startup.

That means you do not need to manually copy integration files into HAOS.

After first install, or after an add-on update that changes the integration files, restart Home Assistant Core once so it loads the updated custom component.

Then in Home Assistant:

1. Open Devices & Services.
2. Add `Powerwall Combined Bridge`.
3. Enter the bridge URL, usually `http://homeassistant.local:8676/status` or your HA host IP on port `8676`.

The older YAML path is still available if you want it. The example package remains in:

- `home_assistant_rest_package.yaml`

Point `resource:` to your HA host IP or `homeassistant.local` on port `8676`.