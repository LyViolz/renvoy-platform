#!/usr/bin/env bash
# End-to-end check against a cluster where deploy/k8s/overlays/local is applied.
# Used by CI (ephemeral k3d cluster) and by `make smoke` locally.
set -euo pipefail

NS=renvoy-status
PORT=18080
cd "$(dirname "$0")/.."

kubectl -n "$NS" rollout status statefulset/postgres --timeout=180s
kubectl -n "$NS" rollout status deployment/web --timeout=180s

job="probe-$(date +%s)"
kubectl -n "$NS" create job "$job" --from=cronjob/prober
if ! kubectl -n "$NS" wait --for=condition=complete "job/$job" --timeout=180s; then
  kubectl -n "$NS" logs "job/$job" || true
  exit 1
fi
kubectl -n "$NS" logs "job/$job" | tail -n 1

kubectl -n "$NS" port-forward svc/web "$PORT:80" >/dev/null 2>&1 &
pf=$!
trap 'kill "$pf" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  curl -fs "localhost:$PORT/healthz" >/dev/null && break
  sleep 1
done

base="http://localhost:$PORT"
curl -fsS "$base/readyz" >/dev/null
expected=$(grep -c '^  - name:' deploy/k8s/base/targets.yaml)
got=$(curl -fsS "$base/api/status" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["targets"]))')
if [ "$got" != "$expected" ]; then
  echo "expected $expected targets in /api/status, got $got" >&2
  exit 1
fi
curl -fsS "$base/metrics" | grep -q '^renvoy_target_up{'
curl -fsS "$base/" | grep -q '<title>Renvoy Status</title>'

echo "smoke ok: $got targets probed, stored and served"
