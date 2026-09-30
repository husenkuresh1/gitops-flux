# gitops-flux

Test repository for the Headlamp "Edit in Git" POC.

Flux syncs the `local/` folder to a local cluster. Changes to these files are made
through Pull Requests created from Headlamp, and Flux applies them after merge.

- `local/_namespace.yaml`: the `poc` namespace
- `local/web/`: a small web app (podinfo) with a Deployment, Service and ConfigMap
