#!/usr/bin/with-contenv bashio

set -euo pipefail

bashio::log.info "Installing Home Assistant custom integration payload"
install_output=$(python3 /opt/powerwall/install_homeassistant_custom_component.py)
bashio::log.info "$install_output"
if [[ "$install_output" == Installed* ]]; then
  bashio::log.warning "Custom integration files changed. Restart Home Assistant Core once to load the updated integration."
fi

bashio::log.info "Rendering Powerwall bridge configuration"
python3 /opt/powerwall/render_addon_config.py \
  --options /data/options.json \
  --output /data/bridge_config.generated.json

bashio::log.info "Starting Powerwall Combined Bridge"
exec python3 /opt/powerwall/combined_energy_bridge.py \
  --config /data/bridge_config.generated.json \
  --host "$(bashio::config 'server_host')" \
  --port "$(bashio::config 'server_port')" \
  --interval "$(bashio::config 'refresh_interval')"