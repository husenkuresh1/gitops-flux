# flux-compare demo

Demo data for the **flux-compare** Headlamp plugin: the same shop runs on two
clusters with deliberate differences, so each comparison shows a different kind
of divergence.

| Cluster | Where | Headlamp name | Bootstrap |
|---|---|---|---|
| prod | local k3s | `dev-peter-prod` | `kubectl apply -f bootstrap/prod.yaml` |
| staging | kind cluster `staging` | `dev-staging` | `kubectl apply -f bootstrap/staging.yaml` |

Each cluster has two Flux Kustomizations, `apps` (HelmReleases in namespace
`shop`) and `status-page` (plain Kustomize in namespace `ops`).

## Applications

| App | Kind | prod | staging | What the comparison shows |
|---|---|---|---|---|
| storefront | HelmRelease | podinfo 6.15.0 | podinfo 6.15.0 | **No differences.** Different clusters, UIDs and timestamps are filtered out. |
| checkout | HelmRelease | chart **6.14.0** | chart 6.15.0 | **Both healthy, different versions.** Intent (chart version), source (`Chart.yaml`), rendered manifest and runtime image digest all differ. |
| payments | HelmRelease | image tag **6.15.1-hotfix** (does not exist) | 6.15.0 | **Works on staging, broken on prod.** Intent shows the values change and Ready=False; runtime shows 0/1 ready and image-pull events. |
| catalog | HelmRelease | 2 replicas, `logLevel: warn` | 1 replica, `logLevel: debug` | **Same version, environment-specific config.** The fake `auth.apiToken` differs and is shown only as a hash. |
| search | HelmRelease | yes (legacy, chart 6.13.0) | — | Exists on one side only. |
| reviews | HelmRelease | — | yes (beta) | Exists on one side only. |
| status-page | Kustomization (plain YAML) | banner "All systems operational" | banner "Maintenance window…" | **Kustomize path:** source files differ (`configmap.yaml`, `secret.yaml`), live ConfigMap differs, Secret compared by hash, no rendered layer. |
| apps | Kustomization | — | — | **Whole-environment view:** source shows which files differ between `clusters/prod/apps` and `clusters/staging/apps`; live shows objects present on one side only. |

All secret-looking values here are fake demo strings.

## Before the demo (2 minutes)

1. Both clusters healthy: `flux --context default get hr -n shop` and
   `flux --context kind-staging get hr -n shop`; only prod `payments` is `False`.
2. Sign in to Headlamp, then open **dev-peter-prod** and **dev-staging** once each
   from Home. Headlamp only holds an apexkube token for clusters opened through
   the cluster chooser; a cluster that was never opened shows "Unauthorized" in
   every layer of the comparison.
3. Open Compare and run step 1 once, so the first live click is fast.

## Demo script (about 5 minutes)

Open Headlamp → **Compare**.

1. **Baseline.** A = `dev-peter-prod` / HelmRelease `shop/storefront`, B = `dev-staging` / same.
   Headline: no differences. Point out that the raw objects differ in UIDs,
   resourceVersions and timestamps, and none of that is shown.
2. **Broken on one cluster.** Pick `shop/payments` on both sides. The headline
   names the Flux intent layer: `spec.values.image.tag` added on prod and Ready `True → False`.
   Open Runtime: prod 0/1 ready with `ErrImagePull`/`BackOff`, staging 1/1.
3. **Version skew.** Pick `shop/checkout`. Intent: chart version 6.14.0 vs 6.15.0.
   Source: `Chart.yaml` changed. Runtime: different image digests, both healthy.
4. **Config drift and secrets.** Pick `shop/catalog`, then turn on **Read Helm storage**.
   Rendered: values differ (`replicaCount`, `logLevel`, `auth.apiToken` shown as
   `sha256:…` on both sides, never in plain text); the Deployment's `spec.replicas` differs.
5. **Plain Kustomize.** Pick Kustomization `flux-system/status-page` on both sides.
   Source shows the changed files; Rendered is "not applicable"; Live shows the
   ConfigMap banner change and the Secret compared by hash.
   The headline points at the Flux intent because `spec.path` differs
   (`clusters/prod/…` vs `clusters/staging/…`). That difference is expected in a
   folder-per-environment repo, and it is the motivating example for
   "expected-difference rules" on the roadmap.
6. **Whole environment.** Pick Kustomization `flux-system/apps`. Source lists
   `search.yaml` (prod only) and `reviews.yaml` (staging only); Live lists
   `HelmRelease search` and `HelmRelease reviews` as one-sided.
7. **Share.** Copy link: the comparison is fully described by the URL.

## Reset

    kubectl --context <ctx> -n flux-system delete kustomization apps status-page
    kubectl --context <ctx> -n flux-system delete gitrepository compare-demo
