#!/usr/bin/env bash
# Per-instance names for running more than one factory on one machine (WO-1108).
# Source this file. With FACTORY_INSTANCE unset every value is the one the engine
# has always used, so an existing install is unchanged.
#
#   FACTORY_INSTANCE=aegisflux  ->  keychain service dentroio-factory-aegisflux,
#                                   prefs ~/.config/factory-agent-aegisflux/prefs,
#                                   logs ~/Library/Logs/factory-agent-aegisflux
#   FACTORY_PORT_OFFSET=100     ->  every published port moves up by 100
#
# FACTORY_KEYCHAIN_SERVICE and FACTORY_PREFS still override the derived values.

FACTORY_INSTANCE="${FACTORY_INSTANCE:-}"
_fi_sfx=""
[ -n "$FACTORY_INSTANCE" ] && _fi_sfx="-${FACTORY_INSTANCE}"

FACTORY_KEYCHAIN_SERVICE="${FACTORY_KEYCHAIN_SERVICE:-dentroio-factory${_fi_sfx}}"
FACTORY_CONFIG_DIR="${FACTORY_CONFIG_DIR:-$HOME/.config/factory-agent${_fi_sfx}}"
FACTORY_PREFS="${FACTORY_PREFS:-$FACTORY_CONFIG_DIR/prefs}"
FACTORY_LOG_DIR="${FACTORY_LOG_DIR:-$HOME/Library/Logs/factory-agent${_fi_sfx}}"

FACTORY_PORT_OFFSET="${FACTORY_PORT_OFFSET:-0}"
FACTORY_PORT_STATUS="${FACTORY_PORT_STATUS:-$((8099 + FACTORY_PORT_OFFSET))}"
FACTORY_PORT_ORCHESTRATOR="${FACTORY_PORT_ORCHESTRATOR:-$((8100 + FACTORY_PORT_OFFSET))}"
FACTORY_PORT_VAULT="${FACTORY_PORT_VAULT:-$((8201 + FACTORY_PORT_OFFSET))}"

export FACTORY_INSTANCE FACTORY_KEYCHAIN_SERVICE FACTORY_CONFIG_DIR FACTORY_PREFS \
  FACTORY_LOG_DIR FACTORY_PORT_OFFSET FACTORY_PORT_STATUS FACTORY_PORT_ORCHESTRATOR \
  FACTORY_PORT_VAULT
unset _fi_sfx
