#!/usr/bin/with-contenv bashio

set -euo pipefail

bashio::log.info "Installing Home Assistant custom integration payload"
install_output=$(python3 /opt/powerwall/install_homeassistant_custom_component.py)
bashio::log.info "$install_output"
integration_changed=false
if [[ "$install_output" == Installed* ]]; then
  integration_changed=true
  bashio::log.warning "Custom integration files changed. Home Assistant Core will be restarted so the updated integration can load."
fi

bashio::log.info "Rendering Powerwall bridge configuration"
python3 /opt/powerwall/render_addon_config.py \
  --options /data/options.json \
  --output /data/bridge_config.generated.json

bashio::log.info "Starting Powerwall Combined Bridge"
python3 /opt/powerwall/combined_energy_bridge.py \
  --config /data/bridge_config.generated.json \
  --host "$(bashio::config 'server_host')" \
  --port "$(bashio::config 'server_port')" \
  --interval "$(bashio::config 'refresh_interval')" &
bridge_pid=$!

cleanup() {
  if kill -0 "$bridge_pid" 2>/dev/null; then
    kill "$bridge_pid" 2>/dev/null || true
    wait "$bridge_pid" 2>/dev/null || true
  fi
}

trap cleanup INT TERM EXIT

bashio::log.info "Ensuring Home Assistant integration entry exists"
integration_args=(
  --port "$(bashio::config 'server_port')"
  --scan-interval "$(bashio::config 'refresh_interval')"
  --local-bridge-url "http://127.0.0.1:$(bashio::config 'server_port')/health"
)
if [[ "$integration_changed" == true ]]; then
  integration_args+=(--restart-core)
fi

if ! python3 /opt/powerwall/ensure_homeassistant_integration.py "${integration_args[@]}"; then
  bashio::log.warning "Automatic Home Assistant integration setup did not complete. The bridge will continue running, but you may need to add the integration manually."
fi

wait "$bridge_pid"