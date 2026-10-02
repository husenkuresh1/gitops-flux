#!/usr/bin/env bash
# Starts Flux syncing one demo cluster folder.
#
#   scripts/demo-up.sh FOLDER kind   creates kind cluster "demo-FOLDER" (context kind-demo-FOLDER)
#   scripts/demo-up.sh FOLDER k3s    uses the local k3s cluster (context "default")
#
# Only the local k3s and kind-demo-* contexts are ever used, so no remote cluster can be touched.
set -euo pipefail

folder=${1:?usage: demo-up.sh FOLDER kind|k3s}
target=${2:?usage: demo-up.sh FOLDER kind|k3s}
repo=$(cd "$(dirname "$0")/.." && pwd)
[[ -f "$repo/bootstrap/$folder.yaml" ]] || { echo "No bootstrap/$folder.yaml: not a synced demo folder." >&2; exit 1; }

case $target in
  kind)
    context=kind-demo-$folder
    if ! kind get clusters | grep -qx "demo-$folder"; then
      kind create cluster --name "demo-$folder" --image kindest/node:v1.33.1 --wait 120s
    fi
    kind load docker-image nginx:1.27-alpine --name "demo-$folder"
    ;;
  k3s)
    context=default
    server=$(kubectl config view -o jsonpath="{.clusters[?(@.name==\"$context\")].cluster.server}")
    [[ $server == https://127.0.0.1:* ]] || { echo "Context $context is not the local k3s ($server)." >&2; exit 1; }
    ;;
  *) echo "Target must be kind or k3s." >&2; exit 1 ;;
esac

if ! kubectl --context "$context" -n flux-system get deploy kustomize-controller >/dev/null 2>&1; then
  flux install --context "$context"
fi

"$repo/scripts/check-clashes.py" "$context" "$folder"
kubectl --context "$context" apply -f "$repo/bootstrap/$folder.yaml"

echo
echo "Flux now syncs $folder on $context. Watch it with:"
echo "  flux --context $context get kustomizations --watch"
