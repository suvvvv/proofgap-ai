#!/usr/bin/env bash
# T09 smoke test against a running deployment: ./scripts/smoke.sh https://<service>.run.app
set -euo pipefail
BASE="${1:-http://localhost:8000}"
INC=INC-M04-001
j() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)"; }
H=$(curl -sf "$BASE/api/health") || { echo "health check failed"; exit 1; }
echo "health:   $H"
curl -sf "$BASE/" | grep -q '<div id="root">' && echo "ui:       ok"
V=$(curl -sf "$BASE/api/incidents/$INC" | j 'd["version"]')
echo "version:  $V"
echo "ranking:  $(curl -sf "$BASE/api/incidents/$INC/plan" | j '[r["check_id"] for r in d["ranked_candidates"]]')"
echo "unknowns: $(curl -sf "$BASE/api/incidents/$INC/thread" | j '[u["batch_id"] for u in d["unknown_relationships"]]')"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/incidents/$INC/approve" -H 'Content-Type: application/json' \
  -H 'X-Demo-User: u-op-1' -d "{\"action_id\":\"A-01\",\"expected_version\":$V,\"justification\":\"smoke\"}")
echo "operator approve -> $code (expect 403)"
[ "$code" = 403 ]
echo "explain:  $(curl -sf -X POST "$BASE/api/incidents/$INC/explain" -H 'Content-Type: application/json' -d "{\"expected_version\":$V}" | j 'd["status"]+" via "+d["source"]')"
echo "SMOKE OK"
