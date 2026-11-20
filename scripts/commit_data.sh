#!/usr/bin/env bash
# Commit and push whatever changed in the data branch checkout (default ./track).
# Used by the workflows after logging a forecast or scoring finished days.
# Retries with a rebase when another run pushed to the data branch in the meantime.
set -euo pipefail
msg="${1:-Update data}"
cd "${TRACK_DIR:-track}"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then
  echo "No data changes."
  exit 0
fi
git commit -q -m "$msg"
for i in 1 2 3 4 5; do
  if git push -q origin HEAD:data; then
    echo "Pushed to data: $msg"
    exit 0
  fi
  sleep $((i * 3))
  git pull -q --rebase origin data
done
echo "::error::Could not push to the data branch"
exit 1
