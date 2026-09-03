# Powerwall Energy Add-on Repo

This repository now contains a proper Home Assistant add-on repository for combining both local Powerwall 3 systems with an optional Shelly 3-phase grid meter.

The add-on itself is in `powerwall_combined_bridge/`.

It also now contains an initial Home Assistant custom integration in `custom_components/powerwall_combined_bridge/` that can create native sensor entities from the bridge output without YAML REST or template configuration.

## Custom Integration

The custom integration polls the bridge endpoint and creates native Home Assistant entities for:

- combined solar, home, battery, grid, site-sum, and balance power
- per-site battery level, solar, load, battery, site power, and grid status
- optional Shelly phase A/B/C power

Current implementation path:

1. Run the `Powerwall Combined Bridge` add-on so the JSON endpoint is available.
2. Copy `custom_components/powerwall_combined_bridge/` into your Home Assistant config directory under `custom_components/`.
3. Restart Home Assistant.
4. In Home Assistant, go to Devices & Services and add `Powerwall Combined Bridge`.
5. Enter the bridge URL, for example `http://homeassistant.local:8676/status` or your HA host IP on port `8676`.

This is the first pass of the native integration. The add-on remains the data collection layer; the custom integration consumes that local JSON and turns it into real entities.

## Recommended Path

If you want to do this properly with Home Assistant OS, the clean path is:

1. Put this repository in its own GitHub repository.
2. Update `repository.yaml` and `powerwall_combined_bridge/config.yaml` to use your real GitHub repo URL.
3. In Home Assistant, open the App Store.
4. Open the repositories dialog from the top-right menu.
5. Add your GitHub repository URL.
6. Install `Powerwall Combined Bridge` from that repository.

This avoids needing to manually find and manage the local `/addons` filesystem on HAOS.

## HAOS Setup

`/config` is the path inside the add-on container. You normally do not access that path directly from the Home Assistant UI.

The add-on maps its Home Assistant add-on config folder into the container as `/config`.

If you want to provide the RSA key as a file, place the verified private key in the add-on config folder on Home Assistant OS.

For GitHub-installed add-ons, that host-side folder will look like:

```text
/addon_configs/<repository_id>_powerwall_combined_bridge/
```

For local add-ons, it is:

```text
/addon_configs/local_powerwall_combined_bridge/tedapi_rsa_private.pem
```

Inside the add-on container this is available as:

```text
/config/tedapi_rsa_private.pem
```

That already matches the add-on default option `rsa_key_path`.

If you do not want to place a file on the host, the add-on also supports an option named `rsa_private_key_base64`. Paste the base64-encoded PEM there and the add-on will decode it into its persistent `/data` volume automatically.

## Add-on Defaults

The add-on is preconfigured for:

- House A: `192.168.1.68` / `1707000-30-K--TG124347001PEX`
- House B: `192.168.1.59` / `1707000-30-K--TG1243480014GF`
- Shelly grid meter: `http://192.168.1.177`

You can change any of those in the add-on options UI.

## Repo Notes

- `.gitignore` excludes the private RSA key, auth cache, and probe output.
- Do not commit `.pypowerwall-auth/` or `tedapi_rsa_private.pem`.

## Development Notes

This workspace contains a safe, read-only-first probe for characterizing what a Tesla Powerwall 3 exposes on a local IP.

## What it does

- Tests transport on the target IP over HTTP and HTTPS.
- Tries likely SNI and Host values used by Tesla gateways.
- Sweeps a discovery set and an extended set of likely local API endpoints.
- Classifies each result as open, unauthorized, redirect, missing, binary/protobuf, server error, or transport failure.
- Writes both JSON and Markdown reports with an availability matrix.
- Can optionally perform one tightly controlled login probe if you explicitly enable it.

## Safe defaults

- Uses `GET` and `HEAD` only unless you add `--allow-auth-probe`.
- Runs single-threaded.
- Defaults to a 1 second delay between endpoint requests.
- Never attempts configuration writes.

## Quick start

Run a read-only full sweep against the home-LAN IP:

```bash
python3 powerwall_probe.py --target-ip 192.168.1.68 --insecure
```

Run only transport checks:

```bash
python3 powerwall_probe.py --target-ip 192.168.1.68 --mode transport --insecure
```

Run discovery-only checks:

```bash
python3 powerwall_probe.py --target-ip 192.168.1.68 --mode discovery --insecure
```

Try one controlled auth probe using the serial's last 5 characters:

```bash
python3 powerwall_probe.py \
  --target-ip 192.168.1.68 \
  --serial TG124347001PEX \
  --allow-auth-probe \
  --insecure
```

Try one controlled auth probe using the full gateway password from the QR label without putting it on the command line:

```bash
export PW_GATEWAY_PASSWORD='your-full-gateway-password'
python3 powerwall_probe.py \
  --target-ip 192.168.1.68 \
  --allow-auth-probe \
  --insecure
```

Use an existing bearer token or cookie for an authenticated read-only sweep:

```bash
export PW_BEARER_TOKEN='your-token'
python3 powerwall_probe.py \
  --target-ip 192.168.1.68 \
  --mode full \
  --methods GET \
  --insecure
```

Fetch config directly over signed v1r without relying on `/api/login/Basic` first:

```bash
python3 powerwall_v1r_direct.py \
  --host 192.168.1.68 \
  --din '1707000-30-K--TG124347001PEX' \
  --output probe-output/house_a_v1r_config_direct.json
```

Fetch a concise direct v1r summary for a known DIN:

```bash
python3 powerwall_v1r_direct.py \
  --host 192.168.1.68 \
  --din '1707000-30-K--TG124347001PEX' \
  --artifact summary \
  --output probe-output/house_a_v1r_summary.json
```

Fetch the full bundle of direct read-only artifacts:

```bash
python3 powerwall_v1r_direct.py \
  --host 192.168.1.68 \
  --din '1707000-30-K--TG124347001PEX' \
  --artifact all \
  --output-dir probe-output/direct-v1r-house-a
```

Expose both Powerwalls plus an optional Shelly 3-phase EM meter as a single local JSON endpoint for Home Assistant REST sensors:

```bash
cp bridge_config.example.json bridge_config.json
python3 combined_energy_bridge.py --config bridge_config.json
```

Test a single combined snapshot from the command line:

```bash
python3 combined_energy_bridge.py --config bridge_config.json --once
```

The Home Assistant example package is in `home_assistant_rest_package.yaml` and expects the bridge at `http://YOUR_BRIDGE_HOST:8676/status`.

Install the proper Home Assistant add-on version on HAOS:

```text
/addons/<your-local-repo>/
  repository.yaml
  powerwall_combined_bridge/
```

The add-on files live in `powerwall_combined_bridge/`.

For HAOS local add-ons, place the verified RSA key here on the Home Assistant host:

```text
/addon_configs/local_powerwall_combined_bridge/tedapi_rsa_private.pem
```

The add-on maps that folder to `/config` inside the container and defaults `rsa_key_path` to `/config/tedapi_rsa_private.pem`.

For GitHub-installed add-ons, the host-side folder name is not `local_*`; Home Assistant uses a repository-specific identifier under `/addon_configs/`. The container path is still `/config/tedapi_rsa_private.pem`.

After copying the repository into HAOS local add-ons:

1. Go to the add-on store.
2. Click `Check for updates`.
3. Open `Powerwall Combined Bridge` under local add-ons.
4. Install it.
5. Review the options for House A, House B, and Shelly.
6. Start it.

The add-on exposes the same JSON endpoint on port `8676`, so Home Assistant can poll:

```text
http://homeassistant.local:8676/status
```

or your HAOS VM IP on port `8676`.

## Output

Reports are written into `probe-output/`:

- `powerwall_probe_<timestamp>.json`
- `powerwall_probe_<timestamp>.md`

The Markdown report is the easiest place to review the endpoint availability matrix and the final branch recommendation.

## Notes

- `--insecure` is useful for first contact because Tesla devices commonly present self-signed certificates.
- Sensitive inputs can be provided through environment variables: `PW_GATEWAY_PASSWORD`, `PW_LOGIN_PASSWORD`, `PW_BEARER_TOKEN`, `PW_COOKIE`, and `PW_EMAIL`.
- `powerwall_v1r_direct.py` is a read-only workaround for hosts where direct signed `/tedapi/v1r` works even though `/api/login/Basic` still returns `401`.
- `powerwall_v1r_direct.py` can fetch `config`, `firmware`, `status`, `components`, `controller`, `pw3_vitals`, `vitals`, `summary`, or `all`.
- `combined_energy_bridge.py` combines House A, House B, and an optional Shelly Gen2/Gen3 EM meter into one local JSON document that Home Assistant can poll over REST.
- `powerwall_combined_bridge/` is a proper Home Assistant add-on scaffold with `config.yaml`, `Dockerfile`, `run.sh`, translations, and vendored bridge scripts.
- If the home-LAN IP is sparse, the next likely branches are Powerwall Wi-Fi TEDAPI at `192.168.91.1` or the Powerwall 3 vendor subnet path.
- The script does not brute force credentials. If you enable auth probing, it will try only one password candidate.
