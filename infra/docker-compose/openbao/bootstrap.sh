#!/bin/sh
# Brings up real (non-dev) OpenBao unattended: starts the server, initializes
# it on the very first boot (writing unseal keys + the bootstrap root token
# to the same persistent volume as the encrypted data — see the compose
# file's comment on this project's accepted trust model for the reasoning),
# unseals it on every boot using those persisted keys, and ensures the
# fixed CS_OPENBAO_TOKEN value exists as a real, permanent, root-equivalent
# token so the backend's own config never has to change across re-inits.
set -e

export BAO_ADDR="http://127.0.0.1:8200"
DATA_DIR="/openbao/data"
INIT_FILE="$DATA_DIR/init.json"

bao server -config=/openbao/config.hcl &
BAO_PID=$!

echo "bootstrap: waiting for openbao to respond..."
i=0
while [ "$i" -lt 60 ]; do
  if bao status >/tmp/status.out 2>&1; then
    break
  fi
  if grep -qi "Sealed" /tmp/status.out 2>/dev/null; then
    break
  fi
  i=$((i + 1))
  sleep 1
done

INITIALIZED=$(bao status -format=json 2>/dev/null | jq -r '.initialized // false')

if [ "$INITIALIZED" != "true" ]; then
  echo "bootstrap: first boot — initializing (keys saved to persisted volume)"
  bao operator init -key-shares=3 -key-threshold=2 -format=json > "$INIT_FILE"
fi

UNSEAL_KEY_1=$(jq -r '.unseal_keys_b64[0]' "$INIT_FILE")
UNSEAL_KEY_2=$(jq -r '.unseal_keys_b64[1]' "$INIT_FILE")
ROOT_TOKEN=$(jq -r '.root_token' "$INIT_FILE")

SEALED=$(bao status -format=json 2>/dev/null | jq -r '.sealed // true')
if [ "$SEALED" = "true" ]; then
  echo "bootstrap: unsealing..."
  bao operator unseal "$UNSEAL_KEY_1" >/dev/null
  bao operator unseal "$UNSEAL_KEY_2" >/dev/null
fi

export BAO_TOKEN="$ROOT_TOKEN"

if ! bao secrets list -format=json 2>/dev/null | jq -e 'has("secret/")' >/dev/null 2>&1; then
  echo "bootstrap: enabling kv-v2 secrets engine at secret/"
  bao secrets enable -path=secret -version=2 kv || true
fi

if [ -n "$CS_OPENBAO_TOKEN" ]; then
  if ! bao token lookup "$CS_OPENBAO_TOKEN" >/dev/null 2>&1; then
    echo "bootstrap: creating fixed application token"
    bao token create -id="$CS_OPENBAO_TOKEN" -policy=root -orphan -ttl=87600h >/dev/null || true
  fi
else
  echo "bootstrap: WARNING — CS_OPENBAO_TOKEN not set, skipping fixed-token creation"
fi

echo "bootstrap: ready"
wait "$BAO_PID"
