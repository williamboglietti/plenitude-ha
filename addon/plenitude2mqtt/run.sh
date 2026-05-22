#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Plenitude2MQTT…"

# Export options for the Python service
export PLENITUDE_EMAIL="$(bashio::config 'email')"
export PLENITUDE_PASSWORD="$(bashio::config 'password')"
export PLENITUDE_SCAN_INTERVAL_HOURS="$(bashio::config 'scan_interval_hours')"
export PLENITUDE_MQTT_TOPIC_PREFIX="$(bashio::config 'mqtt_topic_prefix')"
export PLENITUDE_MQTT_DISCOVERY_PREFIX="$(bashio::config 'mqtt_discovery_prefix')"
export PLENITUDE_LOG_LEVEL="$(bashio::config 'log_level')"

# Supervisor injects MQTT_* env vars when services: ["mqtt:need"] is declared
bashio::log.info "MQTT broker: ${MQTT_HOST}:${MQTT_PORT}"

cd /opt/plenitude2mqtt
exec python3 -m service.main
