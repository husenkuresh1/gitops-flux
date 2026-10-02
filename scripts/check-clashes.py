#!/usr/bin/env python3
"""
Refuses to bootstrap a demo cluster folder onto a cluster that already has objects with the same
kind, namespace and name (Flux would take them over, and could delete them later).

Usage: scripts/check-clashes.py CONTEXT DEMO_FOLDER
"""
import glob
import json
import os
import subprocess
import sys

import yaml

RESOURCES = {
    'Namespace': 'namespaces', 'Secret': 'secrets', 'ConfigMap': 'configmaps',
    'ServiceAccount': 'serviceaccounts', 'Service': 'services', 'Deployment': 'deployments.apps',
    'Role': 'roles.rbac.authorization.k8s.io', 'RoleBinding': 'rolebindings.rbac.authorization.k8s.io',
    'ClusterRole': 'clusterroles.rbac.authorization.k8s.io',
    'ClusterRoleBinding': 'clusterrolebindings.rbac.authorization.k8s.io',
    'HelmRelease': 'helmreleases.helm.toolkit.fluxcd.io',
    'HelmRepository': 'helmrepositories.source.toolkit.fluxcd.io',
    'GitRepository': 'gitrepositories.source.toolkit.fluxcd.io',
    'Kustomization': 'kustomizations.kustomize.toolkit.fluxcd.io',
}
# Shared on purpose: the namespace Flux runs in (protected from pruning by the generator).
ALLOWED = {('Namespace', '', 'flux-system')}

context, folder = sys.argv[1], sys.argv[2]
repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
wanted = set()
paths = glob.glob(os.path.join(repo, folder, '**', '*.y*ml'), recursive=True)
paths.append(os.path.join(repo, 'bootstrap', f'{folder}.yaml'))
for path in paths:
    for doc in yaml.safe_load_all(open(path)):
        if not doc or str(doc.get('apiVersion', '')).startswith('kustomize.config'):
            continue
        meta = doc['metadata']
        wanted.add((doc['kind'], meta.get('namespace', ''), meta['name']))

existing = set()
for kind, resource in RESOURCES.items():
    result = subprocess.run(['kubectl', '--context', context, 'get', resource, '-A', '-o', 'json'],
                            capture_output=True, text=True)
    if result.returncode != 0:
        continue  # the API is not installed yet, so nothing of that kind can clash
    for item in json.loads(result.stdout)['items']:
        labels = item['metadata'].get('labels') or {}
        if labels.get('kustomize.toolkit.fluxcd.io/namespace') == 'flux-system' and \
                labels.get('kustomize.toolkit.fluxcd.io/name') in {d[2] for d in wanted if d[0] == 'Kustomization'}:
            continue  # already applied by this demo's own Kustomizations
        existing.add((kind, item['metadata'].get('namespace', ''), item['metadata']['name']))

clashes = sorted((wanted & existing) - ALLOWED)
if clashes:
    print(f'Refusing: {len(clashes)} objects in {folder} already exist on {context}:')
    for kind, namespace, name in clashes:
        print(f'  {kind} {namespace + "/" if namespace else ""}{name}')
    sys.exit(1)
print(f'No clashes: {len(wanted)} objects in {folder}, none already on {context}.')
