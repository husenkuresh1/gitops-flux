#!/usr/bin/env python3
"""
Generates a demo GitOps tree with the same shape as a real Flux repository, but none of its content.

From the source repository it reads only folder and file names, and each YAML document's kind and
namespace. Everything written is generic: cluster folders get the names given on the command line,
app folders, namespaces and object names come from a word list, and every object is a dummy
(nginx Deployments, podinfo HelmReleases, placeholder ConfigMaps for custom resources).

What is kept, so the demo behaves like the real repository:
  - the same number of clusters, app folders, namespaces, files and documents per file;
  - `1-*` files and folders, which the primary/secondary GitRepository ignore rules split on;
  - each cluster's Flux sync objects (GitRepository + Kustomization), with the same ignore rules,
    pointed at this repository;
  - kustomization.yaml files, with their resource lists renamed to match.

Usage:
  scripts/generate-demo.py SOURCE_DIR OUT_DIR --repo-url URL \\
      --cluster real-name=demo-name ...   (clusters Flux syncs)
      --folder real-name=demo-name ...    (folders copied but not synced)
"""
import argparse
import os
import re
import shutil
import sys
from collections import Counter, defaultdict

import yaml

WORDS = """
web api auth cart catalog checkout orders payments inventory search reviews shipping notify mailer
texts reports analytics billing invoices users profiles sessions gateway frontend backend worker
scheduler queue cache storage uploads media images thumbs pdfgen chat comments feeds recommend ads
pricing tax currency geo maps weather news blog docs wiki forum support tickets status metrics logs
tracing alerts backup cron config vault-ui audit admin portal landing signup login oauth tokens
ledger wallet rewards coupons loyalty survey forms booking calendar events tasks projects boards
kanban timesheet payroll hr crm leads deals quotes contracts assets fleet devices sensors iot
telemetry ingest etl warehouse lake stream pubsub broker relay proxy edge cdn dns certs mesh
registry builds deploy release canary preview sandbox playground demo-app hello echo ping health
probe uptime pager oncall runbook incident chaos loadgen bench seed fixtures mock stub
""".split()

# Structural names kept as they are: Flux's own, Kubernetes system namespaces, and generic words.
KEEP = {
    'flux-system', 'gitrepository', 'helmrepository', 'kustomization', 'default', 'kube-system',
    'kube-public', 'kube-node-lease', 'policies', 'dashboards', 'daily', 'weekly', 'monthly',
    'schedules', 'database', 'primary', 'secondary', 'kust',
}

# File-name endings that only name a kind; anything else is replaced by the document's kind.
KIND_SUFFIXES = {
    'helmrelease', 'helmrepository', 'gitrepository', 'kustomization', 'sec', 'secret', 'cm',
    'configmap', 'pvc', 'pvcs', 'deployment', 'svc', 'service', 'sa', 'httproute', 'imagepolicy',
    'imagerepository', 'imageupdateautomation', 'clusterrole', 'clusterrolebinding', 'role',
    'rolebinding', 'networkpolicy', 'cluster', 'objectstore', 'schedule', 'statefulset', 'cronjob',
    'job', 'policy', 'clusterpolicy', 'ingress', 'certificate', 'clusterissuer', 'gateway',
    'gatewayclass', 'envoyproxy', 'components', 'crds', 'values', 'plan', 'backup',
}

KUSTOMIZATION_FILES = {'kustomization.yaml', 'kustomization.yml', 'Kustomization'}
SYSTEM_NAMESPACES = {'default', 'kube-system', 'kube-public', 'kube-node-lease', 'flux-system'}

# Kinds written as real (dummy) objects; every other kind becomes a placeholder ConfigMap.
REAL_KINDS = {
    'Namespace', 'Deployment', 'Service', 'ConfigMap', 'Secret', 'ServiceAccount', 'Role',
    'RoleBinding', 'ClusterRole', 'ClusterRoleBinding', 'HelmRelease', 'HelmRepository',
}
CLUSTER_SCOPED = {'Namespace', 'ClusterRole', 'ClusterRoleBinding'}

NGINX_IMAGE = 'nginx:1.27-alpine'
PODINFO_REPO = 'oci://ghcr.io/stefanprodan/charts'


def _block_strings(dumper, value):
    style = '|' if '\n' in value else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style=style)


yaml.SafeDumper.add_representer(str, _block_strings)

# Words that are ordinary YAML keys in the generated objects, not names from the source.
YAML_VOCABULARY = {'containers', 'resources', 'metadata', 'labels', 'annotations', 'images', 'data'}


class Names:
    """Maps real identifiers to generic words, the same way everywhere."""

    def __init__(self, identifiers):
        self.map = {}
        words = iter(WORDS)
        for i, real in enumerate(sorted(identifiers - KEEP)):
            self.map[real] = next(words, None) or f'app-{i + 1:03d}'

    def __call__(self, real):
        if real is None:
            return None
        if real.startswith('1-'):
            return '1-' + self(real[2:])
        return real if real in KEEP else self.map.get(real, real)


def owner_of(folders, fallback):
    """The app a file belongs to: its nearest folder that is not structural or a `1-*` folder."""
    owner = next((p for p in reversed(folders) if p not in KEEP and not p.startswith('1-')), None)
    return owner or (folders[0] if folders else fallback)


def load_docs(path):
    try:
        with open(path) as f:
            return [d for d in yaml.safe_load_all(f) if d is not None], True
    except Exception:
        return [], False


def ignore_rules(text, clusters, folders, names):
    """Rewrites a GitRepository ignore text: same rules, generic names."""
    rename = {**folders, **clusters}

    def segment(s):
        if s in rename:
            return rename[s]
        if '*' in s or s in ('', '..', '.'):
            return s
        return names(s)

    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            out.append(re.sub(r"[a-z0-9][a-z0-9-]*", lambda m: rename.get(m.group(0), names.map.get(m.group(0), m.group(0))), line))
        elif stripped:
            neg = stripped.startswith('!')
            body = stripped[1:] if neg else stripped
            out.append(('!' if neg else '') + '/'.join(segment(s) for s in body.split('/')))
        else:
            out.append(line)
    return '\n'.join(out) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source')
    parser.add_argument('out')
    parser.add_argument('--repo-url', required=True)
    parser.add_argument('--branch', default='main')
    parser.add_argument('--cluster', action='append', default=[], help='real=demo, a folder Flux syncs')
    parser.add_argument('--folder', action='append', default=[], help='real=demo, copied but not synced')
    parser.add_argument('--helm-replicas', action='append', default=[],
                        help='N for every cluster, or demo-name=N for one (podinfo pods per HelmRelease; default 1)')
    parser.add_argument('--git-interval', default='1m')
    args = parser.parse_args()

    clusters = dict(c.split('=', 1) for c in args.cluster)
    folders = dict(f.split('=', 1) for f in args.folder)
    roots = {**clusters, **folders}
    helm_replicas = defaultdict(lambda: 1)
    for value in args.helm_replicas:
        if '=' in value:
            name, count = value.split('=', 1)
            helm_replicas[name] = int(count)
        else:
            helm_replicas.default_factory = lambda n=int(value): n

    # Pass 1: every identifier (folders, namespaces, HelmRepository names) and every file.
    identifiers = set()
    files = []  # (root, relative path)
    for root in roots:
        base = os.path.join(args.source, root)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            rel_dir = os.path.relpath(dirpath, base)
            parts = [] if rel_dir == '.' else rel_dir.split('/')
            identifiers.update(p[2:] if p.startswith('1-') else p for p in parts)
            for name in sorted(filenames):
                rel = os.path.join(*parts, name) if parts else name
                files.append((root, rel))
                if name.endswith(('.yaml', '.yml')) and name not in KUSTOMIZATION_FILES:
                    for doc in load_docs(os.path.join(dirpath, name))[0]:
                        if not isinstance(doc, dict):
                            continue
                        meta = doc.get('metadata') or {}
                        if doc.get('kind') == 'Namespace':
                            identifiers.add(meta.get('name'))
                        if meta.get('namespace'):
                            identifiers.add(meta['namespace'])
                        if doc.get('kind') == 'HelmRepository':
                            identifiers.add(meta.get('name'))
    identifiers.discard(None)
    names = Names(identifiers)

    # File renames, per root, so kustomization.yaml resource lists can follow them.
    renamed = {}
    for root, rel in files:
        parts = rel.split('/')
        name = parts[-1]
        dirs = [names(p) for p in parts[:-1]]
        if name in KUSTOMIZATION_FILES or name == '_namespace.yaml':
            new = name
        elif name.lower() == 'readme.md':
            new = 'README.md'
        elif not name.endswith(('.yaml', '.yml')):
            continue  # other notes and scripts are not copied
        else:
            prefix = '1-' if name.startswith('1-') else ''
            stem, ext = os.path.splitext(name[len(prefix):])
            suffix = stem.rsplit('-', 1)[-1] if '-' in stem else ''
            if suffix not in KIND_SUFFIXES:
                docs = [d for d in load_docs(os.path.join(args.source, root, rel))[0] if isinstance(d, dict)]
                suffix = (docs[0].get('kind') or 'manifest').lower() if docs else 'manifest'
            owner = owner_of(dirs, roots[root])
            if dirs[:1] == ['flux-system']:
                # Flux's own files are named after their object, as in the source.
                docs = [d for d in load_docs(os.path.join(args.source, root, rel))[0] if isinstance(d, dict)]
                first = str(((docs[0].get('metadata') or {}).get('name')) or '') if docs else ''
                if docs and docs[0].get('kind') == 'HelmRepository':
                    owner = names(first)
                elif first in KEEP:
                    owner = first
                elif root in first:
                    owner = first.replace(root, roots[root])
            new = f'{prefix}{owner}-{suffix}{ext}'
        target = '/'.join(dirs + [new])
        n = 2
        while target in {v for (r, _), v in renamed.items() if r == root}:
            stem, ext = os.path.splitext(new)
            pre = '1-' if stem.startswith('1-') else ''
            base_stem = stem[len(pre):]
            owner, _, suffix = base_stem.rpartition('-')
            target = '/'.join(dirs + [f'{pre}{owner}-{n}-{suffix}{ext}'])
            n += 1
        renamed[(root, rel)] = target

    out_counts = defaultdict(Counter)
    src_counts = defaultdict(Counter)
    bootstrap = defaultdict(list)

    for root in roots:
        shutil.rmtree(os.path.join(args.out, roots[root]), ignore_errors=True)

    for root in roots:
        demo_root = roots[root]
        used_names = defaultdict(Counter)  # (kind, namespace) -> name counts
        helm_repos = []  # generic HelmRepository (name, namespace) written for this root
        pending_releases = []  # HelmRelease docs whose sourceRef is checked at the end
        written = {}  # target path -> list of docs or text

        def unique(kind, namespace, wanted):
            # flux-system already holds Flux's own objects (e.g. the Secret "flux-system"): never reuse a name there.
            if namespace == 'flux-system' and kind != 'HelmRepository':
                wanted = f'demo-{wanted}'
            key = (kind, namespace or '')
            used_names[key][wanted] += 1
            count = used_names[key][wanted]
            return wanted if count == 1 else f'{wanted}-{count}'

        root_files = [rel for r, rel in files if r == root]
        for rel in root_files:
            if (root, rel) not in renamed:
                continue
            target = renamed[(root, rel)]
            src = os.path.join(args.source, root, rel)
            name = rel.split('/')[-1]
            folder_parts = [names(p) for p in rel.split('/')[:-1]]
            owner = owner_of(folder_parts, demo_root)
            src_counts[demo_root]['files'] += 1

            if name.lower() == 'readme.md':
                written[target] = f'# {owner}\n\nDemo folder: dummy objects with the same shape as a real deployment.\n'
                continue

            if name in KUSTOMIZATION_FILES:
                docs, _ = load_docs(src)
                kust = docs[0] if docs and isinstance(docs[0], dict) else {}
                here = os.path.dirname(rel)
                resources = []
                for res in kust.get('resources') or []:
                    full = os.path.normpath(os.path.join(here, res))
                    mapped = renamed.get((root, full))
                    if mapped:
                        resources.append(os.path.relpath(mapped, os.path.dirname(target) or '.'))
                    elif os.path.isdir(os.path.join(args.source, root, full)):
                        resources.append('/'.join(names(p) for p in res.split('/')))
                written[target] = [{
                    'apiVersion': 'kustomize.config.k8s.io/v1beta1',
                    'kind': 'Kustomization',
                    'resources': resources,
                }]
                continue

            docs, ok = load_docs(src)
            docs = [d for d in docs if isinstance(d, dict)] or [{}]
            folder_ns = None
            out_docs = []
            for doc in docs:
                kind = doc.get('kind') or 'Manifest'
                api = str(doc.get('apiVersion') or '')
                meta = doc.get('metadata') or {}
                src_counts[demo_root]['documents'] += 1
                ns = names(meta.get('namespace')) if meta.get('namespace') else None

                if kind == 'Namespace':
                    ns_name = names(meta.get('name'))
                    namespace_doc = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns_name}}
                    if ns_name in SYSTEM_NAMESPACES:
                        # Flux must never delete a namespace the cluster depends on, even if Git drops it.
                        namespace_doc['metadata']['annotations'] = {'kustomize.toolkit.fluxcd.io/prune': 'disabled'}
                    out_docs.append(namespace_doc)
                    continue

                # The cluster's own Flux sync objects: same settings, generic names, this repository.
                if kind == 'GitRepository' and api.startswith('source.toolkit') and root in clusters:
                    spec = doc.get('spec') or {}
                    url = str(spec.get('url') or '')
                    if not re.search(r'/releases(\.git)?$', url, re.I):
                        out_docs.append(('placeholder', doc, ns))  # another repository
                        continue
                    gr_name = meta.get('name', '').replace(root, demo_root)
                    gr = {
                        'apiVersion': 'source.toolkit.fluxcd.io/v1',
                        'kind': 'GitRepository',
                        'metadata': {'name': gr_name, 'namespace': 'flux-system'},
                        'spec': {
                            'interval': args.git_interval,
                            'url': args.repo_url,
                            'ref': {'branch': args.branch},
                        },
                    }
                    if spec.get('ignore'):
                        gr['spec']['ignore'] = ignore_rules(spec['ignore'], clusters, folders, names)
                    out_docs.append(gr)
                    bootstrap[demo_root].append(gr)
                    continue
                if kind == 'Kustomization' and api.startswith('kustomize.toolkit') and root in clusters:
                    spec = doc.get('spec') or {}
                    source = spec.get('sourceRef') or {}
                    path = str(spec.get('path') or '')
                    if not path.strip('./').startswith(root):
                        out_docs.append(('placeholder', doc, ns))
                        continue
                    ks = {
                        'apiVersion': 'kustomize.toolkit.fluxcd.io/v1',
                        'kind': 'Kustomization',
                        'metadata': {'name': meta.get('name', '').replace(root, demo_root), 'namespace': 'flux-system'},
                        'spec': {
                            **({'dependsOn': spec['dependsOn']} if spec.get('dependsOn') else {}),
                            'interval': spec.get('interval', '10m'),
                            'path': path.replace(root, demo_root),
                            'prune': True,
                            'sourceRef': {'kind': 'GitRepository', 'name': str(source.get('name', '')).replace(root, demo_root)},
                        },
                    }
                    out_docs.append(ks)
                    bootstrap[demo_root].append(ks)
                    continue

                if kind == 'HelmRepository':
                    hr_name, hr_ns = names(meta.get('name')), ns or 'flux-system'
                    helm_repos.append((hr_name, hr_ns))
                    out_docs.append({
                        'apiVersion': 'source.toolkit.fluxcd.io/v1',
                        'kind': 'HelmRepository',
                        'metadata': {'name': unique(kind, hr_ns, hr_name), 'namespace': hr_ns},
                        'spec': {'type': 'oci', 'interval': '1h', 'url': PODINFO_REPO},
                    })
                    continue

                if kind not in REAL_KINDS or (folder_parts[:1] == ['flux-system'] and kind not in ('Secret',)):
                    out_docs.append(('placeholder', doc, ns))
                    continue

                namespace = None if kind in CLUSTER_SCOPED else (ns or 'default')
                obj_name = unique(kind, namespace, owner)
                metadata = {'name': obj_name, **({'namespace': namespace} if namespace else {})}
                if kind == 'Deployment':
                    out_docs.append({
                        'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': metadata,
                        'spec': {
                            'replicas': 1,
                            'selector': {'matchLabels': {'app': obj_name}},
                            'template': {
                                'metadata': {'labels': {'app': obj_name}},
                                'spec': {'containers': [{
                                    'name': 'web', 'image': NGINX_IMAGE,
                                    'ports': [{'containerPort': 80}],
                                    'resources': {'requests': {'cpu': '5m', 'memory': '8Mi'}, 'limits': {'memory': '32Mi'}},
                                }]},
                            },
                        },
                    })
                elif kind == 'Service':
                    out_docs.append({
                        'apiVersion': 'v1', 'kind': 'Service', 'metadata': metadata,
                        'spec': {'selector': {'app': owner}, 'ports': [{'port': 80, 'targetPort': 80}]},
                    })
                elif kind == 'ConfigMap':
                    out_docs.append({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': metadata,
                                     'data': {'greeting': f'hello from {owner}'}})
                elif kind == 'Secret':
                    out_docs.append({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': metadata,
                                     'type': 'Opaque', 'stringData': {'password': 'not-a-real-secret'}})
                elif kind == 'ServiceAccount':
                    out_docs.append({'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': metadata})
                elif kind in ('Role', 'ClusterRole'):
                    out_docs.append({'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': kind, 'metadata': metadata,
                                     'rules': [{'apiGroups': [''], 'resources': ['configmaps'], 'verbs': ['get', 'list']}]})
                elif kind in ('RoleBinding', 'ClusterRoleBinding'):
                    role_kind = 'Role' if kind == 'RoleBinding' else 'ClusterRole'
                    out_docs.append({
                        'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': kind, 'metadata': metadata,
                        'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': role_kind, 'name': obj_name},
                        'subjects': [{'kind': 'ServiceAccount', 'name': 'default', 'namespace': namespace or 'default'}],
                    })
                elif kind == 'HelmRelease':
                    sp = doc.get('spec') or {}
                    ref = ((sp.get('chart') or {}).get('spec') or {}).get('sourceRef') or {}
                    release = {
                        'apiVersion': 'helm.toolkit.fluxcd.io/v2', 'kind': 'HelmRelease', 'metadata': metadata,
                        'spec': {
                            'interval': '1h',
                            'chart': {'spec': {
                                'chart': 'podinfo', 'version': '6.*',
                                'sourceRef': {'kind': 'HelmRepository',
                                              'name': names(ref.get('name')) if ref.get('kind') == 'HelmRepository' else None,
                                              'namespace': names(ref.get('namespace')) if ref.get('namespace') else 'flux-system'},
                            }},
                            'values': {
                                'replicaCount': helm_replicas[demo_root],
                                'ui': {'message': f'Hello from {obj_name}'},
                                'resources': {'requests': {'cpu': '5m', 'memory': '16Mi'}, 'limits': {'memory': '64Mi'}},
                            },
                        },
                    }
                    pending_releases.append(release)
                    out_docs.append(release)
                if folder_ns is None and namespace:
                    folder_ns = namespace

            # Placeholders: ConfigMaps standing in for custom resources the demo clusters do not run.
            final = []
            for item in out_docs:
                if isinstance(item, tuple):
                    _, doc, ns = item
                    kind = doc.get('kind') or 'Manifest'
                    namespace = ns or folder_ns or ('flux-system' if folder_parts[:1] == ['flux-system'] else 'default')
                    final.append({
                        'apiVersion': 'v1', 'kind': 'ConfigMap',
                        'metadata': {'name': unique('ConfigMap', namespace, f'{owner}-{kind.lower()}'), 'namespace': namespace,
                                     'annotations': {'demo.gitops/stands-in-for': kind}},
                        'data': {'note': f'Placeholder for a {kind}; the demo cluster does not run its controller.'},
                    })
                else:
                    final.append(item)
            written[target] = final

        # HelmReleases point at a HelmRepository that exists in this root.
        known = set(helm_repos)
        for release in pending_releases:
            ref = release['spec']['chart']['spec']['sourceRef']
            if (ref['name'], ref['namespace']) not in known:
                if not helm_repos:
                    helm_repos.append(('podinfo', 'flux-system'))
                    known.add(helm_repos[0])
                    written['flux-system/podinfo-helmrepository.yaml'] = [{
                        'apiVersion': 'source.toolkit.fluxcd.io/v1', 'kind': 'HelmRepository',
                        'metadata': {'name': 'podinfo', 'namespace': 'flux-system'},
                        'spec': {'type': 'oci', 'interval': '1h', 'url': PODINFO_REPO},
                    }]
                ref['name'], ref['namespace'] = helm_repos[0]

        # Namespaces used must exist: create the ones the source relied on the cluster having.
        declared = set()
        used = set()
        for docs in written.values():
            if isinstance(docs, list):
                for d in docs:
                    if d.get('kind') == 'Namespace':
                        declared.add(d['metadata']['name'])
                    elif d.get('metadata', {}).get('namespace'):
                        used.add(d['metadata']['namespace'])
        missing = sorted(used - declared - SYSTEM_NAMESPACES)
        if missing and root in clusters:
            written['_namespaces-created-by-cluster.yaml'] = [
                {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': n}} for n in missing
            ]

        for target, content in written.items():
            path = os.path.join(args.out, demo_root, target)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                if isinstance(content, str):
                    f.write(content)
                else:
                    f.write('---\n'.join(yaml.safe_dump(d, sort_keys=False) for d in content))
                    for d in content:
                        out_counts[demo_root][d['kind']] += 1
                        out_counts[demo_root]['documents'] += 1
                        if (d.get('metadata') or {}).get('annotations', {}).get('demo.gitops/stands-in-for'):
                            out_counts[demo_root]['placeholders'] += 1
            out_counts[demo_root]['files'] += 1

    # Bootstrap: the sync objects to apply once per cluster; Flux manages them from Git after that.
    os.makedirs(os.path.join(args.out, 'bootstrap'), exist_ok=True)
    for demo_root, docs in bootstrap.items():
        with open(os.path.join(args.out, 'bootstrap', f'{demo_root}.yaml'), 'w') as f:
            f.write('---\n'.join(yaml.safe_dump(d, sort_keys=False) for d in docs))

    # Summary, and a check that no source name leaked into the output.
    print(f"{'folder':16} {'src files':>9} {'files':>6} {'src docs':>8} {'docs':>6} {'ns':>4} {'Deploy':>6} {'HelmRel':>7} {'placeholders':>12}")
    for root, demo_root in roots.items():
        c, s = out_counts[demo_root], src_counts[demo_root]
        print(f"{demo_root:16} {s['files']:>9} {c['files']:>6} {s['documents']:>8} {c['documents']:>6} {c['Namespace']:>4} "
              f"{c['Deployment']:>6} {c['HelmRelease']:>7} {c['placeholders']:>12}")
    leaks = set()
    real_tokens = (set(roots) | identifiers) - KEEP - set(WORDS) - set(roots.values())
    real_tokens = {t for t in real_tokens if len(t) > 3} - YAML_VOCABULARY
    for dirpath, _, filenames in os.walk(args.out):
        if '/.git' in dirpath or dirpath.endswith('.git') or '/scripts' in dirpath:
            continue
        for name in filenames:
            path = os.path.join(dirpath, name)
            text = open(path, errors='ignore').read() + ' ' + os.path.relpath(path, args.out)
            tokens = set(re.findall(r'[A-Za-z0-9][A-Za-z0-9_-]*', text))
            leaks |= tokens & real_tokens
    if leaks:
        print(f'\nWARNING: {len(leaks)} source names appear in the output: {sorted(leaks)}', file=sys.stderr)
        sys.exit(1)
    print('\nNo source names in the output.')


if __name__ == '__main__':
    main()
