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

Place your verified private key at:

- `/addon_configs/local_powerwall_combined_bridge/tedapi_rsa_private.pem`

Inside the add-on container, this is available at:

- `/config/tedapi_rsa_private.pem`

The default option `rsa_key_path` already points there.

## Default Powerwall mapping

- House A: `192.168.1.68` with DIN `1707000-30-K--TG124347001PEX`
- House B: `192.168.1.59` with DIN `1707000-30-K--TG1243480014GF`

## Shelly meter

If you enable the Shelly section, the add-on will call:

- `Shelly.GetDeviceInfo`
- `EM.GetStatus?id=0`

The combined `totals.grid_w` value will then come from the Shelly `total_act_power` field instead of the Powerwall site sum.

## Home Assistant integration

Use the generated bridge endpoint with the REST and Template configuration in:

- `home_assistant_rest_package.yaml`

Point `resource:` to your HA host IP or `homeassistant.local` on port `8676`.