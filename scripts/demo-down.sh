#!/usr/bin/env bash
# Removes one demo cluster folder.
#
#   scripts/demo-down.sh FOLDER kind   deletes kind cluster "demo-FOLDER"
#   scripts/demo-down.sh FOLDER k3s    deletes the demo's Flux objects on the local k3s; Flux then
#                                      prunes everything they applied
set -euo pipefail

folder=${1:?usage: demo-down.sh FOLDER kind|k3s}
target=${2:?usage: demo-down.sh FOLDER kind|k3s}
repo=$(cd "$(dirname "$0")/.." && pwd)

case $target in
  kind) kind delete cluster --name "demo-$folder" ;;
  k3s)
    server=$(kubectl config view -o jsonpath='{.clusters[?(@.name=="default")].cluster.server}')
    [[ $server == https://127.0.0.1:* ]] || { echo "Context default is not the local k3s ($server)." >&2; exit 1; }
    # Kustomizations first, so Flux prunes what they applied, then their GitRepositories.
    names=$(python3 -c 'import sys, yaml; print(" ".join(d["metadata"]["name"] for d in yaml.safe_load_all(open(sys.argv[1])) if d["kind"] == "Kustomization"))' "$repo/bootstrap/$folder.yaml")
    kubectl --context default -n flux-system delete kustomizations.kustomize.toolkit.fluxcd.io $names --wait
    kubectl --context default delete -f "$repo/bootstrap/$folder.yaml" --ignore-not-found
    ;;
  *) echo "Target must be kind or k3s." >&2; exit 1 ;;
esac
