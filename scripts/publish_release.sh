#!/usr/bin/env bash
# Publish the workflow outputs of one run as a GitHub pre-release.
#
#   publish_release.sh PREFIX TITLE ART_DIR [EXTRA_FILE ...]
#
# Every sub-directory of ART_DIR (one per downloaded workflow artifact) becomes PREFIX-<name>.zip; EXTRA_FILEs
# are attached as they are. PROVENANCE.json records the repository, commit, run, pinned inputs (pins/stage0.env)
# and the job results passed in $RESULTS (toJSON(needs)); SHA256SUMS.txt covers every attached file.
# The release tag is PREFIX-run-<run number>.
set -euo pipefail
PREFIX=$1; TITLE=$2; ART=$3; shift 3
REL=rel-$PREFIX
rm -rf "$REL"; mkdir -p "$REL"
for d in "$ART"/*/; do
  [ -d "$d" ] || continue
  n=$(basename "$d")
  (cd "$d" && zip -q -r -X "../../$REL/$PREFIX-$n.zip" .)
done
for f in "$@"; do cp "$f" "$REL/"; done
python3 -I - "$REL/PROVENANCE.json" <<'PY'
import json, os, sys
pins = {}
if os.path.exists("pins/stage0.env"):
    for line in open("pins/stage0.env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); pins[k] = v
results = {}
try:
    results = {k: v.get("result") for k, v in json.loads(os.environ.get("RESULTS", "{}")).items()}
except Exception as e:
    results = {"error": str(e)}
prov = {"repository": os.environ.get("GITHUB_REPOSITORY"), "commit": os.environ.get("GITHUB_SHA"),
        "workflow": os.environ.get("GITHUB_WORKFLOW"), "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_number": os.environ.get("GITHUB_RUN_NUMBER"), "pins": pins, "job_results": results,
        "runner_image": (os.environ.get("ImageOS", "") + " " + os.environ.get("ImageVersion", "")).strip()}
open(sys.argv[1], "w").write(json.dumps(prov, indent=1, sort_keys=True) + "\n")
print(json.dumps(prov, indent=1, sort_keys=True))
PY
(cd "$REL" && sha256sum -- * > SHA256SUMS.txt && cat SHA256SUMS.txt)
TAG="$PREFIX-run-${GITHUB_RUN_NUMBER}"
gh release create "$TAG" "$REL"/* --prerelease --target "$GITHUB_SHA" --title "$TITLE (run ${GITHUB_RUN_NUMBER})" \
  --notes "APK Builder 005 Stage 0 feasibility evidence produced by CI (nothing here is phone-tested). Inputs, commit and job results: PROVENANCE.json; checksums: SHA256SUMS.txt. Third-party content keeps its own licence (see the licence and NOTICE files inside each archive)."
echo "released $TAG"
