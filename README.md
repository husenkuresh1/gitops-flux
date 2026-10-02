# gitops-flux

Test repository for the Headlamp "Edit in Git" POC.

Flux syncs the `local/` folder to a local cluster. Changes to these files are made
through Pull Requests created from Headlamp, and Flux applies them after merge.

- `local/_namespace.yaml`: the `poc` namespace
- `local/web/`: a small web app (podinfo) with a Deployment, Service and ConfigMap

## Multi-cluster demo

The other top-level folders have the shape of a real multi-cluster Flux repository: the same
number of clusters, app folders, namespaces, files and objects, but only dummy content (nginx
Deployments, podinfo HelmReleases, and placeholder ConfigMaps for custom resources the demo
clusters do not run). All names are generic.

| Folder | Synced by | Runs on |
|---|---|---|
| `prod-east/` | primary + secondary | local k3s (HelmReleases at 0 replicas, to save memory) |
| `mgmt-dev/` | primary + secondary | kind cluster `demo-mgmt-dev` |
| `lab/` | one Kustomization, with a `kustomization.yaml` | kind cluster `demo-lab` |
| `prod-west/`, `staging/`, `mgmt/`, `observability/` | primary + secondary | Git only |
| `archive/` | not synced | — (shows "in Git, but not applied") |

Each cluster has two GitRepositories over this repository: **primary** applies everything except
files and folders named `1-*`, and **secondary** applies only those, after primary.

- `scripts/demo-up.sh FOLDER kind|k3s` starts syncing a folder; `scripts/demo-down.sh` removes it.
  They only ever use the local k3s (`default`) or `kind-demo-*` contexts, and refuse to start if
  the cluster already has an object with the same name.
- `bootstrap/FOLDER.yaml`: the GitRepositories and Kustomizations applied once; Flux manages them
  from Git after that.
- `scripts/generate-demo.py` regenerates the folders from the shape of a source repository.
