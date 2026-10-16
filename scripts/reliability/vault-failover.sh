#!/usr/bin/env bash
# This script deliberately disrupts Vault for a failover test.
if [[ "${UTRAVS_RUN_FAILOVER:-}" != "yes" ]]; then
  echo "Set UTRAVS_RUN_FAILOVER=yes only when you intend to run the disruptive test." >&2
  exit 2
fi
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
umask 077
STATE="${UTRAVS_STATE_DIR:-$HOME/.local/state/utravs}"
mkdir -p "$STATE/logs"
now_ms() { python3 -c 'import time; print(time.time_ns() // 1000000)'; }

OUT="$STATE/evidence/reliability/vault-failover-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"
echo "$OUT" > "$STATE/vault-evidence-path"

ACTIVE=$(kubectl -n vault get pods -l vault-active=true \
  -o jsonpath='{.items[0].metadata.name}')
READY=$(kubectl -n vault get sts vault \
  -o jsonpath='{.status.readyReplicas}')
ALLOWED=$(kubectl -n vault get pdb vault \
  -o jsonpath='{.status.disruptionsAllowed}')

echo "Active=$ACTIVE Ready=$READY AllowedDisruptions=$ALLOWED"

if [[ -z "$ACTIVE" || "$READY" != "3" || "$ALLOWED" -lt 1 ]]; then
  echo "STOP: Vault preflight failed"
  exit 1
fi

kubectl -n vault get pods -o wide > "$OUT/before-pods.txt"
kubectl -n vault get pods -L vault-active,vault-sealed \
  > "$OUT/before-roles.txt"

kubectl -n messaging port-forward \
  deployment/utravs-producer 18080:8080 \
  >"$STATE/logs/vault-producer-pf.log" 2>&1 &

PF_PID=$!
trap 'kill "$PF_PID" 2>/dev/null || true' EXIT
sleep 3

probe() {
  local n="$1"
  curl -sS --max-time 8 -o /dev/null -w '%{http_code}' \
    -X POST http://127.0.0.1:18080/events \
    -H 'Content-Type: application/json' \
    -d "{\"event_type\":\"vault_failover_probe\",\"booking_id\":\"VAULT-FO-$n\",\"payload\":{\"seq\":\"$n\"}}" \
    2>/dev/null || true
}

BEFORE=$(probe before)
echo "Baseline HTTP=$BEFORE"

if [[ "$BEFORE" != "201" ]]; then
  echo "STOP: Producer baseline failed"
  exit 1
fi

(
  for i in $(seq 1 40); do
    TS=$(now_ms)
    CODE=$(probe "$i")
    echo "$TS sample=$i HTTP=$CODE"
    sleep 1
  done
) | tee "$OUT/traffic.log" &

MONITOR_PID=$!
sleep 3

START=$(now_ms)
echo "FAILURE_START_MS=$START" | tee "$OUT/failover.txt"

printf '{"apiVersion":"policy/v1","kind":"Eviction","metadata":{"name":"%s","namespace":"vault"}}' "$ACTIVE" \
  | kubectl create --raw \
    "/api/v1/namespaces/vault/pods/$ACTIVE/eviction" -f -

echo "Eviction requested for $ACTIVE"

NEW_ACTIVE=""
for i in $(seq 1 60); do
  CURRENT=$(kubectl -n vault get pods -l vault-active=true \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

  if [[ -n "$CURRENT" && "$CURRENT" != "$ACTIVE" ]]; then
    NEW_ACTIVE="$CURRENT"
    END=$(now_ms)
    echo "NEW_ACTIVE=$NEW_ACTIVE" | tee -a "$OUT/failover.txt"
    echo "LEADER_SWITCH_OBSERVED_MS=$((END-START))" \
      | tee -a "$OUT/failover.txt"
    break
  fi
  sleep 1
done

wait "$MONITOR_PID"

kubectl -n vault get pods -L vault-active,vault-sealed \
  | tee "$OUT/after-roles.txt"

echo "=== Consumer Processing ==="
kubectl -n messaging logs \
  -l app=utravs-consumer \
  -c consumer \
  --since=10m --prefix=true --max-log-requests=10 \
  | grep 'VAULT-FO-' \
  | tail -10 \
  | tee "$OUT/consumer-processing.txt" || true

echo "=== RESULT ==="
echo "Old Active: $ACTIVE"
echo "New Active: ${NEW_ACTIVE:-NOT DETECTED}"
echo "Evidence: $OUT"
