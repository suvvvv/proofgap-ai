#!/usr/bin/env bash
# Deploy ProofGap: API + UI on Cloud Run (data in Firestore, Gemini key from Secret Manager),
# then Firebase Hosting in front of it.
#   ./scripts/deploy.sh <gcp-project-id> [region] [gcloud-account]
# Prereqs: billing enabled on the project; secret "gemini-api-key" holds the Gemini key
#   printf %s "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=- --project <id>
set -euo pipefail
PROJECT="${1:?usage: deploy.sh <gcp-project-id> [region] [account]}"
REGION="${2:-asia-south1}"
ACCOUNT="${3:-}"
G=(gcloud --project "$PROJECT" ${ACCOUNT:+--account "$ACCOUNT"})

"${G[@]}" services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com firebasehosting.googleapis.com
"${G[@]}" firestore databases describe --database="(default)" >/dev/null 2>&1 || \
  "${G[@]}" firestore databases create --location="$REGION" --type=firestore-native

NUM=$("${G[@]}" projects describe "$PROJECT" --format='value(projectNumber)')
SA="$NUM-compute@developer.gserviceaccount.com"
"${G[@]}" projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role=roles/datastore.user --condition=None >/dev/null
SECRET_FLAG=()
if "${G[@]}" secrets describe gemini-api-key >/dev/null 2>&1; then
  "${G[@]}" secrets add-iam-policy-binding gemini-api-key --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor >/dev/null
  SECRET_FLAG=(--set-secrets GEMINI_API_KEY=gemini-api-key:latest)
else
  echo "WARN: secret gemini-api-key not found; deploying with deterministic fallback only."
fi

"${G[@]}" run deploy proofgap --source . --region "$REGION" --allow-unauthenticated \
  --set-env-vars "STORE=firestore,GOOGLE_CLOUD_PROJECT=$PROJECT,GEMINI_MODEL=${GEMINI_MODEL:-gemini-2.5-flash}" \
  ${SECRET_FLAG[@]+"${SECRET_FLAG[@]}"} --min-instances 1 --max-instances 3 --memory 512Mi

URL=$("${G[@]}" run services describe proofgap --region "$REGION" --format='value(status.url)')
echo "Cloud Run URL: $URL"
./scripts/smoke.sh "$URL"

# Firebase Hosting (UI from CDN, /api rewritten to the Cloud Run service above).
(cd frontend && npm ci && npm run build)
sed -i.bak "s/\"region\": \"[a-z0-9-]*\"/\"region\": \"$REGION\"/g" firebase.json && rm -f firebase.json.bak
npx -y firebase-tools@15.32.1 deploy --only hosting,firestore:rules --project "$PROJECT"
echo "Firebase Hosting URL: https://$PROJECT.web.app"
