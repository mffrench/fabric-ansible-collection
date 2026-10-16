# Step 1 — Expose Options with NGINX Ingress Controller

**Roadmap reference:** [`MIGRATION-ROADMAP.md`](./MIGRATION-ROADMAP.md) — Step 1
**Plan reference:** [`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) — W1, W4 (decision only, sub-task 1.2), partial W5, partial W3, partial W7
**Prerequisite:** [`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md) (Baseline CI & Test Runner Fixes)
**Status:** `[ ] pending`

---

## Overview

This deliverable builds on the working baseline established in **Step 0** ([`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md)). It introduces all new Ansible variables (`ingress_type`, `expose_*`) and makes the collection's console wait-logic aware of the `expose_console` flag, while the **nginx ingress controller remains the only supported and tested ingress backend**. No Gateway API resources, templates, or CRDs are introduced yet.

The primary goals of this step are:
1. Establish the stable variable schema that Steps 2 and 3 will build on.
2. Prove there is no regression in the working nginx-backed test suite (Scenario B baseline from Step 0).
3. Validate the extreme opposite scenario: a deployment where nothing is exposed
   through the NGINX ingress controller (`expose_console: false`,
   `expose_ca: false`, `expose_peer: false`, `expose_orderer: false`).

---

## Sub-task 1.1 — Variable abstraction (defaults in each consuming role)

**Intent:** Introduce every new variable with safe defaults so all existing
playbooks continue to work without modification. Each role declares, in its
own `defaults/main.yml`, the variables its tasks read. The roles run in
separate plays: one play per role in `docs/source/tutorials/oss-installing.rst`,
one playbook per step in `tutorial/`. A role's defaults are not visible outside
the play that runs it, so a variable declared only in `fabric_operator_crds`
is undefined in `fabric_console` and in the organization roles.

The logic shared by the two console roles (cluster-domain discovery, the
cluster-local domain facts and the sub-task 1.1b guard) lives in a small
internal role, `k8s_domain_facts`, called via `include_role`. It resolves
`cluster_domain` and sets the derived fact `ingress_domain_is_cluster_local`.
The per-endpoint Services of sub-task 1.3b are needed whether the domain is
cluster-local or not.

**Expected outcomes:**
- Each role's `defaults/main.yml` contains the variables of the table below
  for that role, and only those.
- A new internal role `roles/k8s_domain_facts` reads the cluster domain from
  the `kube-system/coredns` ConfigMap (via `kubernetes.core.k8s_info`, no
  `kubectl`, no `pods/exec`); falls back to `cluster.local` with a warning if
  discovery fails; errors if the discovered value contradicts a value the user
  set explicitly.
- Both console roles call `k8s_domain_facts` at the top of
  `tasks/k8s/create.yml`. No other role calls it: the organization roles get
  no Kubernetes dependency from this sub-task.
- `ansible-lint` and `yamllint` pass on all modified files.
- All existing tests pass without setting any new variable.

**Where each variable is declared** (✓ = in that role's `defaults/main.yml`;
the sub-task in brackets is its first consumer in that role):

| Variable | Default | `fabric_operator_crds` | `fabric_console`, `hlfsupport_console` | `endorsing_organization` | `ordering_organization` |
|---|---|---|---|---|---|
| `ingress_type` | `nginx` | ✓ (2.3) | ✓ (1.3) | ✓ (3.2) | ✓ (3.2) |
| `gateway_class_name`, `ingress_ca_port`, `ingress_grpc_orderer_port`, `ingress_grpc_peer_port` | see todo | ✓ (2.3) | | | |
| `ingress_domain` | `localho.st` (already there) | ✓ (2.3) | | | |
| `expose_console` | `true` | | ✓ (1.3) | | |
| `cluster_domain` | `""` | | ✓ (1.1) | | |
| `expose_ca` | `true` | | | ✓ (1.3b) | ✓ (1.3b) |
| `expose_peer` | `true` | | | ✓ (1.3b) | |
| `expose_orderer` | `true` | | | | ✓ (1.3b) |
| `expose_peer_operations` | `false` | | | ✓ (3.4) | |
| `expose_grpcweb` | `false` | | | ✓ (3.5) | |
| `expose_orderer_operations` | `false` | | | | ✓ (3.7) |
| `namespace` | `""` | (already there) | (already there) | ✓ (1.3b) | ✓ (1.3b) |

A variable declared in several roles must get the same value from the user:
set it in a vars file loaded by every playbook. In `tutorial/`, that file is
`common-vars.yml`: every playbook already loads it, and sub-task 1.4 writes
`ingress_type` and the `expose_*` flags there.

**New variables:**

`ingress_domain` — already in `roles/fabric_operator_crds/defaults/main.yml`
(`localho.st`), but no task reads it today. Step 2 uses it for the Gateway
listener hostnames (sub-task 2.3). It does **not** set the component FQDNs:
the operator builds them as `<namespace>-<cr_name>-<endpoint>.<domain>` from
the IBPConsole `spec.networkinfo.domain`, which the console roles fill from
`console_domain`. In this document, `ingress_domain` in an FQDN pattern
(sub-tasks 1.1b, 1.3b, 1.4b, 1.6) denotes that domain; the Ansible checks
read `console_domain`, the variable in scope where the domain is set.

`cluster_domain` — the Kubernetes cluster domain (kubelet `clusterDomain`,
e.g. `cluster.local`), the suffix of Service FQDNs
(`<svc>.<namespace>.svc.<cluster_domain>`). Declared in the console roles;
`k8s_domain_facts` uses it to detect cluster-local deployments (sub-task
1.1b). Sub-task 1.4b does not read it: the CI script has its own
`CLUSTER_DOMAIN` variable. Default: `""` (sentinel meaning "not set by the
user"); resolved at role entry to the discovered value, or to `cluster.local`
when discovery fails.

`namespace` (organization roles) — the Kubernetes namespace of the
organization's components. Read only when a component is not exposed, to
create its per-endpoint Services (sub-task 1.3b). It has the same name as in
the operator and console roles, so one vars file sets it for every playbook.
Default: `""`; the role fails when it is empty and a component is not exposed.

**Auto-discovery of `cluster_domain`:**

The cluster domain is the first zone of the `kubernetes` plugin line in the
CoreDNS Corefile, stored in the `kube-system/coredns` ConfigMap:

```
kubernetes cluster.local in-addr.arpa ip6.arpa {
```

kubeadm, kind, k3s, EKS and AKS all generate this ConfigMap; the CI bootstrap
script writes the same line (sub-task 1.4b). The ConfigMap is read with
`kubernetes.core.k8s_info`, the same Python client and kubeconfig as every other
task of the collection.

`roles/k8s_domain_facts/defaults/main.yml`:

```yaml
# Inputs, passed by the calling console role.
k8s_domain_facts_namespace: ""
# Domain of the component FQDNs: the caller's console_domain.
k8s_domain_facts_domain: ""
# User-supplied cluster domain; "" means "discover it".
k8s_domain_facts_cluster_domain: ""
# expose_* flags checked against a cluster-local domain (sub-task 1.1b).
k8s_domain_facts_expose: {}
```

`roles/k8s_domain_facts/tasks/main.yml`:

```yaml
- name: Read the CoreDNS Corefile to discover the cluster domain
  kubernetes.core.k8s_info:
    api_version: v1
    kind: ConfigMap
    namespace: kube-system
    name: coredns
  register: _coredns_cm
  failed_when: false   # missing ConfigMap or RBAC denial is handled below

- name: Extract the cluster domain from the kubernetes plugin line
  ansible.builtin.set_fact:
    _discovered_cluster_domain: >-
      {{ (_coredns_cm.resources | default([]) | first | default({})).data.Corefile
         | default('')
         | regex_search('(?m)^\s*kubernetes\s+([A-Za-z0-9.-]+)', '\1')
         | default([''], true) | first
         | regex_replace('\.$', '') }}

- name: Fail if the discovered cluster domain contradicts the user-supplied value
  ansible.builtin.fail:
    msg: >-
      The cluster domain auto-discovered from the CoreDNS Corefile
      ('{{ _discovered_cluster_domain }}') does not match the
      cluster_domain variable you set ('{{ k8s_domain_facts_cluster_domain }}').
      Either remove cluster_domain from your vars file to accept the
      auto-discovered value, or correct it to
      '{{ _discovered_cluster_domain }}'.
  when:
    - k8s_domain_facts_cluster_domain | length > 0   # user set a value
    - _discovered_cluster_domain | length > 0
    - k8s_domain_facts_cluster_domain != _discovered_cluster_domain

- name: Warn and fall back to cluster.local when discovery fails
  ansible.builtin.debug:
    msg: >-
      WARNING: could not auto-discover the cluster domain from the
      kube-system/coredns ConfigMap
      ({{ _coredns_cm.msg | default('ConfigMap not found or no kubernetes plugin line') }}).
      Using cluster_domain='cluster.local'.
      If this value is wrong, set cluster_domain explicitly in your vars file.
  when:
    - k8s_domain_facts_cluster_domain | length == 0
    - _discovered_cluster_domain | length == 0

- name: Resolve cluster_domain
  ansible.builtin.set_fact:
    cluster_domain: >-
      {{ k8s_domain_facts_cluster_domain or _discovered_cluster_domain or 'cluster.local' }}

# Only <namespace>.svc.<cluster_domain> is a usable cluster-local domain: the
# FQDN <ns>-<cr>-<endpoint>.<ns>.svc.<cluster_domain> is then exactly the FQDN
# of the per-endpoint Service created by sub-task 1.3b.
- name: Set ingress_domain_is_cluster_local fact
  ansible.builtin.set_fact:
    ingress_domain_is_cluster_local: >-
      {{ k8s_domain_facts_domain == k8s_domain_facts_namespace + '.svc.' + cluster_domain }}
    ingress_domain_is_unsupported_cluster_local: >-
      {{ k8s_domain_facts_domain != k8s_domain_facts_namespace + '.svc.' + cluster_domain
         and (k8s_domain_facts_domain == cluster_domain
              or k8s_domain_facts_domain.endswith('.' + cluster_domain)) }}
```

**Call from the console roles** — in `roles/fabric_console/tasks/k8s/create.yml`
and `roles/hlfsupport_console/tasks/k8s/create.yml`, right after the existing
"Fail if namespace not specified" task (`console_domain` is already checked in
`tasks/create.yml`):

```yaml
- name: Resolve the cluster domain and check the console domain
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.k8s_domain_facts
  vars:
    k8s_domain_facts_namespace: "{{ namespace }}"
    k8s_domain_facts_domain: "{{ console_domain }}"
    k8s_domain_facts_cluster_domain: "{{ cluster_domain }}"
    # The console sets the domain of every component, so the console play
    # checks every flag. The CA/peer/orderer flags are organization-role
    # variables: they reach this play only from the shared vars file, and
    # count as exposed when absent.
    k8s_domain_facts_expose:
      expose_console: "{{ expose_console }}"
      expose_ca: "{{ expose_ca | default(true) }}"
      expose_peer: "{{ expose_peer | default(true) }}"
      expose_orderer: "{{ expose_orderer | default(true) }}"
```

**Todo list:**
- [ ] Add to `roles/fabric_operator_crds/defaults/main.yml`:
  `ingress_type: nginx`, `gateway_class_name: fabric-envoy-gateway`,
  `ingress_ca_port: 7054`, `ingress_grpc_orderer_port: 7050`,
  `ingress_grpc_peer_port: 7051` (consumed in Step 2; inert here). Replace the
  comment of the existing `ingress_domain` default:
  ```yaml
  # Domain of the Gateway listener hostnames (gateway-api path, Step 2).
  # Must equal the console_domain of the console play: the operator builds
  # every component FQDN from the console domain, not from this variable.
  ingress_domain: localho.st
  ```
- [ ] Add to `roles/fabric_console/defaults/main.yml` and
  `roles/hlfsupport_console/defaults/main.yml`: `ingress_type: nginx`,
  `expose_console: true`, and:
  ```yaml
  # Kubernetes cluster domain (e.g. cluster.local).  Leave empty to let the
  # role read it from the kube-system/coredns ConfigMap; if that fails,
  # cluster.local is used and a warning is printed.  Set it explicitly when
  # the ConfigMap cannot be read (no access to kube-system, cluster DNS other
  # than CoreDNS) and your cluster uses a non-standard domain.  An explicit
  # value that contradicts the discovered one is an error.
  cluster_domain: ""
  ```
  Next to the existing `# console_domain: example.org` line, document the
  cluster-local value: `<namespace>.svc.<cluster_domain>` (e.g.
  `fabricinfra.svc.cluster.local`) when all components stay in-cluster and all
  `expose_*` are `false`; any other `*.<cluster_domain>` value, or a
  cluster-local domain with any `expose_*: true`, is an error (sub-task 1.1b).
- [ ] Add to `roles/endorsing_organization/defaults/main.yml`:
  `ingress_type: nginx`, `expose_ca: true`, `expose_peer: true`,
  `expose_peer_operations: false`, `expose_grpcweb: false`, `namespace: ""`.
- [ ] Add to `roles/ordering_organization/defaults/main.yml`:
  `ingress_type: nginx`, `expose_ca: true`, `expose_orderer: true`,
  `expose_orderer_operations: false`, `namespace: ""`.
- [ ] Create `roles/k8s_domain_facts/` (`defaults/main.yml`,
  `tasks/main.yml`, `meta/main.yml`) with the content above: six tasks (read
  ConfigMap, extract, conflict-error, warn-on-failure, resolve, set the
  cluster-local facts).
- [ ] Add the `include_role` call above to
  `roles/fabric_console/tasks/k8s/create.yml` and
  `roles/hlfsupport_console/tasks/k8s/create.yml`, before any task that
  branches on `expose_console` or reads `cluster_domain`.
- [ ] Add `namespace: "{{ k8s_namespace | default('default') }}"` to the play
  `vars` of `tutorial/01-create-ordering-organization-components.yml`,
  `02-create-endorsing-organization-components.yml`,
  `12-create-endorsing-organization-components.yml`,
  `97-delete-endorsing-organization-components.yml`,
  `98-delete-endorsing-organization-components.yml` and
  `99-delete-ordering-organization-components.yml`. This is the expression
  `00-deploy-fabric-console.yml` already uses.
- [ ] Add inline comments explaining every variable's purpose and when to
  override it, reusing the comments of MIGRATION-PLAN.md §5.1 (its single
  file location is superseded by the table above).
- [ ] List the new variables of each role in its page under
  `docs/source/roles/`.
- [ ] Run `ansible-lint` and `yamllint` on all modified and new files.

**Relevant context:**
- The defaults files must not contain conditional logic — only `key: value`
  defaults. All conditional logic lives in `k8s_domain_facts`.
- Why defaults in each role rather than one shared defaults file: the
  organization roles stay REST-only (no `include_role` of a Kubernetes role
  just to get defaults); each role's documentation lists the variables it
  reads; and the collection already repeats simple defaults across roles
  (`namespace`, `wait_timeout`, images). A shared role exposing its defaults
  with `include_role: public: true` would also work, but every role would have
  to call it, even on paths that never read the variables.
- Why `include_role` and not `include_tasks`: `include_tasks: set_facts.yml`
  resolves the path inside the calling role, so `hlfsupport_console` cannot
  include a task file of another role. `include_role` with the FQCN works from
  any role of the collection.
- `k8s_domain_facts` takes role-prefixed inputs and returns its results with
  `set_fact`. They are host facts, visible to the calling role after the
  include. The resolved `cluster_domain` is its only output read outside the
  role. The prefixed inputs keep the interface explicit and avoid passing
  `cluster_domain` itself, which the role overwrites.
- Reassigning `cluster_domain` with `set_fact` is safe: `set_fact` overrides
  the console role's default and play vars. Extra vars (`-e`) still win, but
  an `-e` value is non-empty, so the resolve task keeps it unchanged.
- The organization roles cannot run the sub-task 1.1b guard: they talk only to
  the console REST API and do not know the domain. The console play checks the
  CA/peer/orderer flags instead (`| default(true)` in the call above). If the
  user changes the flags between playbooks, the mismatch shows up late, in the
  module's health wait.
- Why not `kubectl exec deployment/coredns -- awk … /etc/resolv.conf` (the
  previous design): the CoreDNS image is distroless (only the `/coredns`
  binary, no `awk` or shell), so the exec always fails. Even with a shell,
  CoreDNS pods run with `dnsPolicy: Default` and inherit the node's
  `resolv.conf`, which has no cluster `search` line; `$4` would be empty, or
  a node search domain, silently taken as the cluster domain. It also required
  the `kubectl` binary and the `pods/exec` permission in `kube-system`.
- The empty-string sentinel distinguishes "user left the default" from "user
  explicitly set a value", including an explicit `cluster.local`.
- Discovery reads only the `kubernetes` plugin line. `(?m)^\s*kubernetes`
  ignores commented-out lines. A bare `kubernetes {` line (no zone) yields no
  match, and so does a missing ConfigMap (OpenShift: `openshift-dns/dns-default`;
  GKE: `kube-dns`). A trailing dot (`cluster.local.`) is stripped.
- Required permission: `get` on `configmaps` in `kube-system`. A 403 is
  handled like a missing ConfigMap (warning + fallback); `failed_when: false`
  never makes discovery fatal.
- Both cluster-local facts are read only by the sub-task 1.1b guard, in the
  same role. Sub-task 1.4b (bash) computes its own condition from
  `INGRESS_DOMAIN` and `CLUSTER_DOMAIN`; sub-task 1.3b runs regardless.
- `k8s_info` uses the kubeconfig and the `kubernetes` Python library the
  console roles already require; no `kubectl` binary is needed.

---

## Sub-task 1.1b — Cluster-local domain validation guard

**Dependencies:** sub-task 1.1 (`cluster_domain`) and the per-endpoint
Services of sub-task 1.3b: without those Services, no cluster-local value can
work ([REVIEW-MIGRATION-PLAN-STEP-1.md](./REVIEW-MIGRATION-PLAN-STEP-1.md),
"Cluster-local `ingress_domain`").

**Why only `<namespace>.svc.<cluster_domain>`:** a Service FQDN has the form
`<svc>.<ns>.svc.<cluster_domain>`. With a domain `<x>.svc.<cluster_domain>`,
the operator's FQDN `<ns>-<cr>-<endpoint>.<x>.svc.<cluster_domain>` names the
Service `<ns>-<cr>-<endpoint>` in namespace `<x>`. Sub-task 1.3b creates these
Services in the components' namespace, so `<x>` must be that namespace. Any
other value (`svc.cluster.local`, `cluster.local`, another namespace) matches
no Service.

**Why this mode:** the mode itself needs nothing beyond sub-task 1.3b: setting
the console domain to `<namespace>.svc.<cluster_domain>` is enough. It is the
only expose-none setup that needs no DNS change, because the FQDNs are already
Service names. The CoreDNS rewrites of sub-task 1.4b are written by the CI
script only; on a real cluster, `expose_*: false` with an external domain
needs the same rewrites in the cluster DNS, which is not always possible on
managed clusters (GKE uses kube-dns, not CoreDNS). This sub-task only adds the
checks that make a wrong value fail at once, instead of in the modules' health
waits (`wait_timeout`, up to several minutes).

**Intent:** When `ingress_domain` is a cluster-local suffix (detected by
`ingress_domain_is_cluster_local: true` from sub-task 1.1, i.e.
`ingress_domain == <namespace>.svc.<cluster_domain>`), every component FQDN
`<ns>-<cr>-<endpoint>.<ns>.svc.<cluster_domain>` is exactly the FQDN of the
per-endpoint Service created by sub-task 1.3b. CoreDNS resolves them without
any rewrite rule, and no Ingress object is needed or meaningful. The
following cases must be enforced at role-entry time:

| `ingress_domain` | any `expose_*: true` | Action |
|---|---|---|
| `<namespace>.svc.<cluster_domain>` | no (all `false`) | Create per-endpoint Services (1.3b); skip CoreDNS rewrites (1.4b) |
| `<namespace>.svc.<cluster_domain>` | yes (at least one) | **Fail fast** with an actionable error message |
| any other `*.<cluster_domain>` (e.g. `svc.cluster.local`, `other-ns.svc.cluster.local`) | any | **Fail fast**: such FQDNs match no Service name |
| external (e.g. `localho.st`) | any | Normal path; no change |

**Expected outcomes:**
- When `ingress_domain` is `<namespace>.svc.<cluster_domain>` and all
  `expose_*` are `false`, the play continues without error, sub-task 1.3b
  creates the per-endpoint Services, and sub-task 1.4b is skipped.
- When `ingress_domain` is any other cluster-local value, the play fails
  immediately and the error names the only supported form.
- When `ingress_domain` is cluster-local and any `expose_*` is `true`, the play
  fails immediately with a clear message naming which flags are in conflict.
- The guard is a no-op for all standard (non-cluster-local) `ingress_domain`
  values.

**Concrete task YAML** — append to `roles/k8s_domain_facts/tasks/main.yml`
(sub-task 1.1). The domain checked is the console role's `console_domain`,
passed as `k8s_domain_facts_domain`:

```yaml
- name: Fail when console_domain is a cluster-local value other than <ns>.svc.<cluster_domain>
  ansible.builtin.fail:
    msg: >-
      console_domain='{{ k8s_domain_facts_domain }}' is inside the cluster
      domain '{{ cluster_domain }}' but component FQDNs built from it match no
      Kubernetes Service. The only supported cluster-local value is
      '{{ k8s_domain_facts_namespace }}.svc.{{ cluster_domain }}'.
  when: ingress_domain_is_unsupported_cluster_local | bool

- name: Collect expose_* flags that are true (for error reporting)
  ansible.builtin.set_fact:
    _expose_flags_enabled: >-
      {{ k8s_domain_facts_expose | dict2items
         | selectattr('value', 'truthy', convert_bool=true)
         | map(attribute='key') | list }}
  when: ingress_domain_is_cluster_local | bool

- name: Fail when a cluster-local console_domain is combined with expose_* flags
  ansible.builtin.fail:
    msg: >-
      console_domain='{{ k8s_domain_facts_domain }}' is a cluster-local domain
      (cluster_domain='{{ cluster_domain }}'), which means no external Ingress
      will be created. The following expose_* flags are true (or not set in
      the vars file shared by all playbooks, which counts as true), which is
      incompatible with a cluster-local console_domain:
        {{ _expose_flags_enabled | join(', ') }}
      Either set all expose_* flags to false in the shared vars file, or use
      an external console_domain (e.g. localho.st, example.com).
  when:
    - ingress_domain_is_cluster_local | bool
    - _expose_flags_enabled | length > 0
```

**Todo list:**
- [ ] Append the three tasks above to `roles/k8s_domain_facts/tasks/main.yml`
  (after the `ingress_domain_is_cluster_local` fact-setting task from
  sub-task 1.1).
- [ ] Both console roles call `k8s_domain_facts` (sub-task 1.1), so the guard
  applies to `roles/fabric_console` and `roles/hlfsupport_console` without
  duplicate code.
- [ ] Write a unit test (using `ansible-playbook --check` or `molecule`) that:
  - passes with `console_domain: <ns>.svc.cluster.local` + all `expose_*: false`
  - fails with `console_domain: <ns>.svc.cluster.local` + `expose_console: true`
  - fails with `console_domain: <ns>.svc.cluster.local` + `expose_console: false`
    and `expose_ca` / `expose_peer` / `expose_orderer` not set (absent = exposed)
  - fails with `console_domain: svc.cluster.local` (any `expose_*`)
  - passes with `console_domain: localho.st` + any `expose_*` combination
- [ ] Run `ansible-lint` on the updated `roles/k8s_domain_facts/tasks/main.yml`.

**Relevant context:**
- `_expose_flags_enabled` is a local helper fact used only for the error message;
  it is intentionally not reused elsewhere. `truthy` with `convert_bool=true`
  also handles flags passed as strings (`"false"` is false).
- `expose_peer_operations`, `expose_orderer_operations`, and `expose_grpcweb`
  are omitted from the check because they are sub-flags of `expose_peer` /
  `expose_orderer` — if those parent flags are `false`, the sub-flags are
  irrelevant; if the parent flags are `true`, the parent-flag check fires first.
- Sub-task 1.4b skips its CoreDNS rewrites when the domain is cluster-local;
  sub-task 1.3b does **not** skip (its Services are what makes cluster-local
  FQDNs resolvable). This sub-task only handles the hard-error cases.
- The operator still creates its Ingress objects, with cluster-local hosts
  (B2). nginx would route a client presenting such an SNI, but no external
  DNS name points there. The B2 decision is unchanged by this mode.

**Open points (resolve before implementing):**
- **Console FQDN.** Sub-task 1.3b creates no Service for the console, so
  `<ns>-<console>-console.<ns>.svc.<cluster_domain>` resolves to nothing. In
  the CI expose-none leg, the nip.io wildcard still sends the console FQDN to
  nginx; with a cluster-local domain, nothing does. Check in the operator spike
  whether anything in the cluster dials that FQDN (console backend, deployer),
  and whether the console UI still works through `kubectl port-forward` when
  its host URL is the cluster-local FQDN. If needed, extend sub-task 1.3b with
  the console endpoints.
- **Where the guard runs.** The guard runs in the console roles (sub-task 1.1).
  It is skipped when the console is created outside the collection (Helm,
  kubectl, GitOps) or when the components are created with the modules
  directly. To be settled together with the roles-versus-modules question.
- **CI coverage.** The expose-none leg (sub-task 1.5) uses a nip.io domain, so
  it never runs this mode; only the unit test above covers the guard. Options:
  a third matrix leg with `console_domain: <ns>.svc.cluster.local`, or a
  documented manual check.
- **No migration.** The domain is written into the node certificates (SANs)
  and the console registry when components are created. Switching an existing
  network to a cluster-local domain means recreating it; the no-expose
  tutorial (sub-task 1.8) should say so.

---

## Sub-task 1.2 — RBAC: no change to the operator's ClusterRole

**Intent:** Settle the RBAC question of workstream W4 for Step 1: **nothing is
added** to the ClusterRole of the operator.

The `gateway.networking.k8s.io` objects (`Gateway`, `HTTPRoute`, `TLSRoute`) are
created by **Ansible tasks** in Step 2, with the permissions of the kubeconfig
used by the control node. The operator never creates them: it always creates
its own `Ingress` objects. Giving the operator rights on resources it never
touches would only widen its privileges, in both
`roles/fabric_operator_crds/templates/k8s/rbac/hlf-operator-clusterrole.yaml`
and `roles/hlfsupport_console/templates/k8s/cluster_role.yml.j2`. It would also
add a Gateway API manifest to Step 1, against acceptance criterion 9.

**Expected outcomes:**
- Both cluster role templates are unchanged by Step 1.
- Step 2 documents the rights the control node's kubeconfig needs on
  `gateway.networking.k8s.io` (see MIGRATION-STEP-2.md).

**Todo list:**
- [ ] Do not edit the two cluster role templates.
- [ ] Check in the operator source (spike, REVIEW §Recommended order) that it
  never creates or watches Gateway API objects. If it does, reopen this
  sub-task with the exact rules the operator needs.

**Relevant context:**
- MIGRATION-PLAN.md §5.4 and the "W4" mentions of MIGRATION-ROADMAP.md and
  MIGRATION-STEP-2.md still describe the earlier rule block for the operator.
  They are corrected together with Step 2.
- Review: [REVIEW-MIGRATION-PLAN-STEP-1.md](./REVIEW-MIGRATION-PLAN-STEP-1.md),
  "Documentation inconsistencies".

---

## Sub-task 1.3 — Console wait-logic for `expose_console` flag

**Intent:** Split the existing console-wait block into `expose_console: true`
and `expose_console: false` branches. When `expose_console: false` the
collection skips route/ingress discovery, relies on the readiness of the console
Deployment, and prints an informational notice instead of a public URL.

**No `uri` call to an in-cluster name.** The Ansible tasks run on the control
node, which is outside the cluster and cannot resolve
`<console>.<ns>.svc.<cluster_domain>`. The wait therefore reads the state of
the console Deployment through the Kubernetes API (`kubernetes.core.k8s_info`,
or the `wait: yes` of `kubernetes.core.k8s`), which needs a kubeconfig but no
access to cluster DNS. The roles already do this in "Wait for console
deployment to start"; the `expose_console: false` branch ends there.

**Facts about the console Service** (checked on a `fabric-operator` 1.0.9
cluster): `https://<console>.<ns>.svc.<cluster_domain>:3000` answers on
**HTTPS** (an `http://` request gets no answer); `/` and `/health` return 200
without authentication; `/ak/api/v3/health` returns 401. A URL built for an
in-cluster client (the Job of sub-task 1.5, assertion 2 of sub-task 1.6) is
therefore `https://<console>.<ns>.svc.{{ cluster_domain }}:3000/health`, with the
cluster domain taken from `cluster_domain` and never a literal `cluster.local`.


**Expected outcomes:**
- `expose_console: true` (default): existing behaviour is preserved.
- `expose_console: false`: no Ingress wait and no `uri` call; the play ends when
  the Deployment is ready and prints a notice that the console is not exposed.

**Tasks** (five, none of them an in-cluster `uri`):
1. *Wait for console Ingress to exist* — `ingress_type == 'nginx' and expose_console | bool`
2. *Set console URL from Ingress* — same guard
3. *Wait for console to respond (public URL)* (`uri`) — `expose_console | bool`
4. *Print console URL* — `expose_console | bool`
5. *Print console exposition notice* — `not expose_console | bool`

The "in-cluster Service URL" `uri` task of MIGRATION-PLAN.md §5.5 is dropped
for the reasons above.

**Todo list:**
- [ ] In `roles/hlfsupport_console/tasks/k8s/create.yml`, apply the five tasks
  to the existing Ingress wait, URL and `uri` tasks.
- [ ] In `roles/fabric_console/tasks/k8s/create.yml` and in
  `tutorial/00-deploy-fabric-console.yml`, apply tasks 4 and 5 to the final
  print.
- [ ] Use `ibp.com/v1beta1` for `IBPConsole` everywhere. The CRD
  (`roles/hlfsupport_crds/templates/console-crd.yml.j2`) serves `v1beta1`,
  `v1alpha2` and `v1alpha1`, and `v1beta1` is the storage version. The templates
  and `tutorial/00-deploy-fabric-console.yml` already create `v1beta1`; change
  the `k8s_info` and delete tasks that read `ibp.com/v1alpha2` in
  `roles/fabric_console/tasks/{k8s,openshift}/{create,delete}.yml` and
  `roles/hlfsupport_console/tasks/{k8s,openshift}/{create,delete}.yml`.
  `fabric_console/tasks/k8s/delete.yml` also picks `v1alpha1` before 2.5.0:
  keep that branch.
- [ ] Do **not** add any Gateway API (`ingress_type == 'gateway-api'`) branches
  yet — those belong in Step 2.
- [ ] Run `ansible-lint` on the modified files.

**Relevant context:**
- Task YAML for the Ingress tasks: MIGRATION-PLAN.md §5.5 (without its
  in-cluster `uri` task).
- The in-cluster console URL is only for clients running inside the cluster
  (Job, CI assertions), never for the control node.

---

## Sub-task 1.3b — One collection-owned ClusterIP Service per endpoint (`expose-none` compatibility)

**Intent:** The Fabric Operator encodes `<fqdn>:443` for **every** endpoint of
every node in Custom Resources, ConfigMaps, connection profiles and console
registry entries (`api_url`, `operations_url`, `grpcwp_url`, `osnadmin_url`).
When `expose_*: false`, those FQDNs must still reach the right container port
in-cluster, without nginx.

A single Service per node cannot do this: each node advertises **several**
endpoints on `:443`, and a Service port maps `443` to exactly **one**
`targetPort`. Adding `443 → 7051` to the operator's peer Service would send
`-operations:443` to the gRPC port. That would break the console's status
checks and its grpcweb proxy, the collection's `/healthz` waits, and
`osnadmin` channel joins
(see [REVIEW-MIGRATION-PLAN-STEP-1.md](./REVIEW-MIGRATION-PLAN-STEP-1.md) B3).

The collection therefore creates **its own ClusterIP Service per endpoint**
(per node × endpoint type), each mapping `443` to that endpoint's native
port. Each Service is paired with one CoreDNS rewrite per endpoint type
(sub-task 1.4b). The operator's own Services are **never modified**, so
operator reconciliation cannot revert anything.

**Endpoint → Service mapping** (one row = one Service per node):

| Component | Endpoint type (FQDN suffix) | Console URL field | `port` | `targetPort` |
|---|---|---|---|---|
| CA      | `ca`         | `api_url`        | 443 | 7054 |
| CA      | `operations` | `operations_url` | 443 | 9443 |
| Peer    | `peer`       | `api_url`        | 443 | 7051 |
| Peer    | `operations` | `operations_url` | 443 | 9443 |
| Peer    | `grpcweb`    | `grpcwp_url`     | 443 | 7443 |
| Orderer | `orderer`    | `api_url`        | 443 | 7050 |
| Orderer | `admin`      | `osnadmin_url`   | 443 | 9443 |
| Orderer | `operations` | `operations_url` | 443 | 8443 |
| Orderer | `grpcweb`    | `grpcwp_url`     | 443 | 7443 |

**Naming rule.** The operator builds each FQDN as
`<namespace>-<cr_name>-<endpoint>.<ingress_domain>`. The collection names
each Service after the **first DNS label** of that FQDN:

```
Service name:  <namespace>-<cr_name>-<endpoint>        e.g. default-org1peer-operations
Service FQDN:  <namespace>-<cr_name>-<endpoint>.<namespace>.svc.<cluster_domain>
```

As a result:
- CoreDNS needs **one** regex rewrite per endpoint type
  (`<ns>-*-<endpoint>.<ingress_domain>` → `<same label>.<ns>.svc.<cluster_domain>`),
  not one rule per node. The rules can be written before any node exists,
  which matters because each create module polls `operations_url/healthz`
  **inside** its own task (see `wait_for()` in
  `plugins/module_utils/ordering_services.py`). The Service and the rewrite
  must therefore exist before the module call returns.
- With `ingress_domain: <namespace>.svc.<cluster_domain>` (sub-task 1.1b), the
  operator's FQDNs **are** these Service FQDNs: no rewrite at all.
- Each Service name is a valid DNS-1035 label (≤ 63 chars, starts with a
  letter) because it is also the first label of an FQDN the operator already
  generates. An `assert` still enforces this.

**Lifecycle.** The Services are created **before** the corresponding
`certificate_authority` / `peer` / `ordering_service` module call. Until the
operator starts the pods, a Service has no endpoints, which is harmless. The
module's own health wait then succeeds through the new Service. After the
module returns, a verification task checks every URL the console reports
(`api_url`, `operations_url`, `grpcwp_url`, `osnadmin_url`) against the set
of created Services. This catches a missing endpoint type that the health
wait does not exercise (grpcweb, admin).

**Facts to confirm in the operator spike** (REVIEW §Recommended order,
action 3). They are encoded as role defaults so that a wrong guess means a
default change, not a redesign:

| # | Assumption | Default encoding |
|---|---|---|
| S1 | The operator CR name is the display name lowercased with every non-`[a-z0-9]` character removed (`Org1 CA` → `org1ca`). | `k8s_endpoint_services_cr_name_regex: '[^a-z0-9]'` |
| S2 | Ordering node CR names are `<ordering service cr_name>node<i>`, `i` = 1..N. | `k8s_endpoint_services_orderer_node_suffix: 'node'` |
| S3 | Operator pods carry the label `app: <cr_name>`, as used by the operator's own Service selector. | `k8s_endpoint_services_selector_key: app` |
| S4 | Node TLS certificates already carry every endpoint FQDN as a SAN. nginx runs in SSL-passthrough mode today, so this is low risk. | — (no change expected) |

### New internal role `k8s_endpoint_services`

The two organization roles run in separate playbooks and cannot share task
files, so the logic lives in a small role called via `include_role`. Its
Kubernetes dependency (`kubernetes.core`, a kubeconfig) is pulled in **only**
when a component is not exposed. The REST-only path of the organization roles
stays unchanged.

`roles/k8s_endpoint_services/defaults/main.yml`:

```yaml
# Namespace of the components: the caller passes its `namespace` variable.
k8s_endpoint_services_namespace: ""
# Kind of component the Services are created for: ca | peer | orderer.
k8s_endpoint_services_component: ""
# Operator CR names, one per node (see S1/S2 in MIGRATION-STEP-1.md).
k8s_endpoint_services_cr_names: []
k8s_endpoint_services_cr_name_regex: '[^a-z0-9]'
k8s_endpoint_services_orderer_node_suffix: node
k8s_endpoint_services_selector_key: app
# Endpoint types per component and the native container port each maps to.
k8s_endpoint_services_endpoints:
  ca:
    - { endpoint: ca, target_port: 7054 }
    - { endpoint: operations, target_port: 9443 }
  peer:
    - { endpoint: peer, target_port: 7051 }
    - { endpoint: operations, target_port: 9443 }
    - { endpoint: grpcweb, target_port: 7443 }
  orderer:
    - { endpoint: orderer, target_port: 7050 }
    - { endpoint: admin, target_port: 9443 }
    - { endpoint: operations, target_port: 8443 }
    - { endpoint: grpcweb, target_port: 7443 }
# Console URLs to verify after the module call (tasks_from: verify).
k8s_endpoint_services_urls: []
```

`roles/k8s_endpoint_services/tasks/main.yml` (create):

```yaml
- name: Check every Service name is a valid DNS-1035 label
  ansible.builtin.assert:
    that:
      - _svc_name is match('^[a-z]([-a-z0-9]*[a-z0-9])?$')
      - _svc_name | length <= 63
    fail_msg: >-
      Service name '{{ _svc_name }}' is not a valid DNS-1035 label. Shorten the
      namespace or the component display name.
    quiet: true
  loop: "{{ k8s_endpoint_services_cr_names | product(k8s_endpoint_services_endpoints[k8s_endpoint_services_component]) | list }}"
  vars:
    _svc_name: "{{ k8s_endpoint_services_namespace }}-{{ item.0 }}-{{ item.1.endpoint }}"

- name: Create one ClusterIP Service per endpoint
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: v1
      kind: Service
      metadata:
        name: "{{ _svc_name }}"
        namespace: "{{ k8s_endpoint_services_namespace }}"
        labels:
          app.kubernetes.io/managed-by: fabric-ansible-collection
          fabric-ansible-collection/component: "{{ k8s_endpoint_services_component }}"
          fabric-ansible-collection/instance: "{{ item.0 }}"
          fabric-ansible-collection/endpoint: "{{ item.1.endpoint }}"
      spec:
        type: ClusterIP
        selector: "{{ {k8s_endpoint_services_selector_key: item.0} }}"
        ports:
          - name: https
            port: 443
            # Must stay an int: a string targetPort is a *named* port.
            targetPort: "{{ item.1.target_port | int }}"
            protocol: TCP
  loop: "{{ k8s_endpoint_services_cr_names | product(k8s_endpoint_services_endpoints[k8s_endpoint_services_component]) | list }}"
  loop_control:
    label: "{{ _svc_name }}"
  vars:
    _svc_name: "{{ k8s_endpoint_services_namespace }}-{{ item.0 }}-{{ item.1.endpoint }}"
```

`roles/k8s_endpoint_services/tasks/verify.yml`:

```yaml
- name: Assert every console endpoint URL has a matching per-endpoint Service
  ansible.builtin.assert:
    that:
      - (item | urlsplit('hostname')).split('.') | first in _expected_names
    fail_msg: >-
      The console advertises '{{ item }}' but no Service named
      '{{ (item | urlsplit('hostname')).split('.') | first }}' was created.
      Check assumptions S1–S3 in MIGRATION-STEP-1.md sub-task 1.3b.
    quiet: true
  loop: "{{ k8s_endpoint_services_urls | select | list }}"
  vars:
    _expected_names: >-
      {{ k8s_endpoint_services_cr_names
         | product(k8s_endpoint_services_endpoints[k8s_endpoint_services_component] | map(attribute='endpoint'))
         | map('join', '-')
         | map('regex_replace', '^', k8s_endpoint_services_namespace ~ '-')
         | list }}
```

`roles/k8s_endpoint_services/tasks/delete.yml`:

```yaml
- name: Delete the per-endpoint Services of the given instances
  kubernetes.core.k8s:
    state: absent
    kind: Service
    namespace: "{{ k8s_endpoint_services_namespace }}"
    label_selectors:
      - app.kubernetes.io/managed-by=fabric-ansible-collection
      - fabric-ansible-collection/instance={{ item }}
  loop: "{{ k8s_endpoint_services_cr_names }}"
```

### Calls from the organization roles

`roles/endorsing_organization/tasks/create.yml`:

```yaml
- name: Fail if namespace is not set while a component is not exposed
  ansible.builtin.fail:
    msg: namespace must be set when expose_ca or expose_peer is false
  when:
    - not namespace
    - not (expose_ca | bool and expose_peer | bool)

- name: Create per-endpoint Services for the CA (expose-none)
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.k8s_endpoint_services
  vars:
    k8s_endpoint_services_namespace: "{{ namespace }}"
    k8s_endpoint_services_component: ca
    k8s_endpoint_services_cr_names:
      - "{{ ca_name | lower | regex_replace('[^a-z0-9]', '') }}"
  when: not expose_ca | bool

- name: Create certificate authority          # existing task, add `register`
  hyperledger.fabric_ansible_collection.certificate_authority: ...
  register: endorsing_organization_ca

- name: Verify per-endpoint Services for the CA (expose-none)
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.k8s_endpoint_services
    tasks_from: verify
  vars:
    k8s_endpoint_services_namespace: "{{ namespace }}"
    k8s_endpoint_services_component: ca
    k8s_endpoint_services_cr_names:
      - "{{ ca_name | lower | regex_replace('[^a-z0-9]', '') }}"
    k8s_endpoint_services_urls:
      - "{{ endorsing_organization_ca.certificate_authority.api_url }}"
      - "{{ endorsing_organization_ca.certificate_authority.operations_url }}"
  when: not expose_ca | bool
```

`namespace` and the `expose_*` flags are defaults of the organization roles
(sub-task 1.1), so the `when` conditions need no `| default(true)`. Every
call passes `k8s_endpoint_services_namespace: "{{ namespace }}"` and is
guarded by its component's flag (`not expose_peer | bool`,
`not expose_orderer | bool`).

Same pattern for the peers (before *Create peer* / *Create multiple peers*):

```yaml
    k8s_endpoint_services_component: peer
    k8s_endpoint_services_cr_names: >-
      {{ ([peer_name] if peers == 1
          else range(1, peers + 1) | map('string')
               | map('regex_replace', '^', peer_name) | list)
         | map('lower') | map('regex_replace', '[^a-z0-9]', '') | list }}
```

Verify with `api_url`, `operations_url` and `grpcwp_url` of each registered
peer. For *Create multiple peers*, use the `results` list.

`roles/ordering_organization/tasks/create.yml`: the same namespace check
(with `expose_orderer` instead of `expose_peer`) and CA block, plus, before
*Create ordering service*:

```yaml
    k8s_endpoint_services_component: orderer
    k8s_endpoint_services_cr_names: >-
      {{ range(1, ordering_service_nodes + 1) | map('string')
         | map('regex_replace', '^', (ordering_service_name | lower
               | regex_replace('[^a-z0-9]', '')) ~ 'node')
         | list }}
```

After the module call, run the verify step with `api_url`, `operations_url`,
`grpcwp_url` and `osnadmin_url` of every element of the registered
`ordering_service` list. `osnadmin_url` is empty on Fabric < 2.4.1, and
`select` drops empty values.

The `delete.yml` of each organization role calls
`tasks_from: delete` with the same `cr_names`, guarded by the same `when`.

**Expected outcomes:**
- With `expose_ca/peer/orderer: false`, the namespace contains one Service per
  row of the mapping table for every node, each listening on `443` only.
- The operator's own Services are byte-for-byte unchanged.
- `curl -k https://<ns>-<peer>-operations.<ingress_domain>/healthz` from an
  in-cluster pod returns `{"status":"OK"}` (port 9443 reached, not 7051).
- The module health waits pass without nginx in the path.
- The verify step fails loudly (naming S1–S3) when the console advertises an
  endpoint without a matching Service.
- `ansible-lint` passes on the new role and all modified task files.

**Todo list:**
- [ ] Create `roles/k8s_endpoint_services/` (`defaults/main.yml`,
  `tasks/main.yml`, `tasks/verify.yml`, `tasks/delete.yml`, `meta/main.yml`)
  with the content above.
- [ ] Add the create / verify blocks around the CA and peer module calls in
  `roles/endorsing_organization/tasks/create.yml`, and register the module
  outputs (`endorsing_organization_ca`, `endorsing_organization_peer`,
  `endorsing_organization_peers`).
- [ ] Add the create / verify blocks around the CA and ordering-service
  module calls in `roles/ordering_organization/tasks/create.yml`, and
  register the module outputs.
- [ ] Add the delete calls to both organization roles' `delete.yml`.
- [ ] Run the operator spike and adjust the S1–S3 defaults if needed.
- [ ] Document the new role in `docs/source/roles/` (internal, but its
  defaults are user-overridable).
- [ ] Run `ansible-lint` on the new role and all modified task files.

**Relevant context:**
- Sub-task 1.3b runs whenever the component is not exposed, **including**
  when `ingress_domain` is cluster-local. Only the CoreDNS rewrites (1.4b)
  are skipped in that case.
- Partial exposure (e.g. `expose_peer: false`, `expose_ca: true`) works on
  the Service side. The CI per-endpoint-type rewrites of sub-task 1.4b,
  however, assume CA, peer and orderer are **all** unexposed, because the
  `-operations` suffix is shared by all three components. Mixed modes need
  exact per-FQDN rewrites and are out of scope for Step 1 CI.
- The port variables `ingress_grpc_peer_port`, `ingress_grpc_orderer_port`
  and `ingress_ca_port` from sub-task 1.1 remain Gateway-API listener ports
  for Step 2. They are **not** the native target ports above.

---

## Sub-task 1.4 — `run-tests.sh` variable injection for Step 1 flags

**Intent:** Extend the stabilized `run-tests.sh` (fixed in Step 0) to inject the newly introduced `INGRESS_TYPE` and `EXPOSE_*` variables into `tutorial/common-vars.yml`.

*(Note: Baseline fixes for positional argument crashes, `TEST_RUN_ID` stamping, and connection variable injection are implemented in [`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md) Sub-task 0.2).*

**Expected outcomes:**
- `run-tests.sh` reads `INGRESS_TYPE` (default: `nginx`) and all `EXPOSE_*` flags from the environment (defaulting to safe values).
- `ingress_type` and `expose_*` flags are patched into `common-vars.yml` via `yq` prior to playbook execution.

**Todo list:**
- [ ] Update `.github/scripts/run-tests.sh` to include `yq` patching for `ingress_type` and the six `expose_*` boolean variables into `common-vars.yml`.
- [ ] Confirm that `INGRESS_TYPE`, `EXPOSE_CA`, `EXPOSE_PEER`, `EXPOSE_ORDERER`,
  `EXPOSE_PEER_OPERATIONS`, `EXPOSE_ORDERER_OPERATIONS`, and `EXPOSE_GRPCWEB`
  all default to safe values when not explicitly set.
- [ ] Verify `bash -n .github/scripts/run-tests.sh` passes syntax validation.

**Relevant context:**
- Baseline script: `.github/scripts/run-tests.sh` (as delivered in Step 0)
- Reference implementation: MIGRATION-PLAN.md §5.3.3
- Variable injection rationale (why `common-vars.yml` instead of `-e @file`):
  MIGRATION-PLAN.md §5.3.1 and the note following §5.3.3

---

## Sub-task 1.4b — CoreDNS per-endpoint-type rewrites for the `expose-none` CI leg

**Intent:** When `expose_*: false` with an external `ingress_domain` (CI:
`<ip>.nip.io` or `localho.st`), the existing CoreDNS wildcard rewrites
(`rewrite name regex (.*)\.<domain> host.ingress.internal`) send every
component FQDN to the nginx ClusterIP, which silently routes traffic through
nginx when the intent is to bypass it. This sub-task adds **one rewrite rule
per endpoint type** (`ca`, `peer`, `orderer`, `operations`, `grpcweb`,
`admin`). Each rule maps
`<ns>-<cr>-<endpoint>.<ingress_domain>` to the per-endpoint Service
`<ns>-<cr>-<endpoint>.<ns>.svc.<cluster_domain>` created by sub-task 1.3b.
Every endpoint therefore lands on its own native port: `-operations` reaches
9443/8443, `-grpcweb` reaches 7443 and `-admin` reaches 9443, never the API
port.

The dialled hostname stays the original FQDN, so TLS SANs remain valid and no
`csr_hosts` change or re-enrollment is needed.

**Cluster-local domain exception:** when `ingress_domain` is
`<namespace>.svc.<cluster_domain>`, the FQDNs are already the per-endpoint
Service FQDNs. No rewrite is applied.

**Design constraints:**
- The rules are applied by the CI bootstrap script
  (`.github/scripts/kind_with_nginx.sh`), **not by any Ansible role task**,
  consistent with MIGRATION-PLAN.md §1.1.
- They are written in `apply_coredns_override` at **cluster bootstrap,
  before any playbook runs**. The rules are patterns, so they do not depend
  on node names, and the console and the module health waits need them
  during `build_network.sh`.
- The existing `Corefile` content (the `localho.st` / nip.io wildcards to
  `host.ingress.internal`, the `hosts` block, the `kubernetes` plugin) is
  **kept**. The endpoint rules are inserted **before** the wildcards. With
  rewrite's default `stop` behaviour, the first matching rule wins, so
  endpoint FQDNs never reach the wildcard, while the console FQDN
  (`-console`, `-proxy`, matching no endpoint rule) still goes to nginx.
- `CLUSTER_DOMAIN` is not discovered: this function writes the `kubernetes`
  plugin line itself, so it uses the same `CLUSTER_DOMAIN` variable
  (default `cluster.local`) in both places.
- Each `name regex` rule has a matching `answer name` rule so that clients
  receive an answer for the name they asked for.

**Generated rule (one per endpoint type).** Example for namespace `default`,
ingress domain `127-0-0-1.nip.io` and endpoint type `operations`:

```
rewrite stop {
    name regex ^(default-[a-z0-9]+-operations)\.127-0-0-1\.nip\.io {1}.default.svc.cluster.local
    answer name ^(default-[a-z0-9]+-operations)\.default\.svc\.cluster\.local {1}.127-0-0-1.nip.io
}
```

`[a-z0-9]+` matches the operator CR name (assumption S1 in sub-task 1.3b: no
dashes). That prevents `default-org1peer-operations` from being confused with
a CR whose own name ends in an endpoint word.

**Expected outcomes:**
- In the `expose-none` leg, the CoreDNS ConfigMap contains six endpoint
  rewrite blocks ahead of the existing wildcards. In the `expose-all` leg, it
  is unchanged.
- From an in-cluster pod, `nslookup <ns>-<peer>-operations.<domain>` returns
  the ClusterIP of Service `<ns>-<peer>-operations`, which is neither the
  nginx ClusterIP nor the `<ns>-<peer>-peer` ClusterIP.
- The console FQDN still resolves to the nginx ClusterIP.
- CoreDNS is restarted after the ConfigMap is applied.
- The function is the direct prototype for the equivalent function in
  `kind_with_envoy_gateway.sh` introduced in Step 2.

**Todo list:**
- [ ] In `.github/scripts/kind_with_nginx.sh`, add the inputs (they default to
  the values the tutorial already uses):
  ```bash
  NAMESPACE=${NAMESPACE:-default}
  CLUSTER_DOMAIN=${CLUSTER_DOMAIN:-cluster.local}
  # INGRESS_DOMAIN defaults to NIP_DOMAIN inside apply_coredns_override
  ```
- [ ] Add a helper that prints the endpoint rewrite blocks:
  ```bash
  # coredns_endpoint_rewrites NAMESPACE INGRESS_DOMAIN CLUSTER_DOMAIN
  # One rewrite per endpoint type: <ns>-<cr>-<endpoint>.<domain> -> per-endpoint
  # Service <ns>-<cr>-<endpoint>.<ns>.svc.<cluster_domain> (MIGRATION-STEP-1 1.3b).
  coredns_endpoint_rewrites() {
    local ns="$1" domain="$2" cluster_domain="$3"
    local domain_re="${domain//./\\.}"
    local cluster_domain_re="${cluster_domain//./\\.}"
    local endpoint
    for endpoint in ca peer orderer operations grpcweb admin; do
      printf '        rewrite stop {\n'
      printf '            name regex ^(%s-[a-z0-9]+-%s)\\.%s {1}.%s.svc.%s\n' \
        "${ns}" "${endpoint}" "${domain_re}" "${ns}" "${cluster_domain}"
      printf '            answer name ^(%s-[a-z0-9]+-%s)\\.%s\\.svc\\.%s {1}.%s\n' \
        "${ns}" "${endpoint}" "${ns}" "${cluster_domain_re}" "${domain}"
      printf '        }\n'
    done
  }
  ```
- [ ] In `apply_coredns_override`, compute the block only for a
  non-cluster-local `expose-none` run, and insert it right after `ready`,
  before the existing wildcard rewrites:
  ```bash
  INGRESS_DOMAIN=${INGRESS_DOMAIN:-${NIP_DOMAIN}}
  ENDPOINT_REWRITES=""
  if [[ "${EXPOSE_CA:-true}" == "false" \
     && "${EXPOSE_PEER:-true}" == "false" \
     && "${EXPOSE_ORDERER:-true}" == "false" \
     && "${INGRESS_DOMAIN}" != "${NAMESPACE}.svc.${CLUSTER_DOMAIN}" ]]; then
    ENDPOINT_REWRITES=$(coredns_endpoint_rewrites \
      "${NAMESPACE}" "${INGRESS_DOMAIN}" "${CLUSTER_DOMAIN}")
  fi
  ```
  ```
      .:53 {
          errors
          health {
             lameduck 5s
          }
          ready
  ${ENDPOINT_REWRITES}
          rewrite name regex (.*)\.localho\.st host.ingress.internal
          rewrite name regex (.*)\.${NIP_DOMAIN} host.ingress.internal
          hosts { ... unchanged ... }
          kubernetes ${CLUSTER_DOMAIN} in-addr.arpa ip6.arpa { ... unchanged ... }
          ...
  ```
- [ ] Make sure the `EXPOSE_*`, `NAMESPACE` and `INGRESS_DOMAIN` variables are
  exported **before** `kind_with_nginx.sh` runs in `fvtest.yml` (the matrix
  `env` of sub-task 1.5), because the script now runs before the playbooks.
- [ ] Run `bash -n .github/scripts/kind_with_nginx.sh`.
- [ ] Locally, run `kubectl -n kube-system get cm coredns -o yaml` after
  bootstrap with `EXPOSE_*=false` and check the six blocks and the unchanged
  wildcard / `hosts` lines.

**Relevant context:**
- Only CA, peer and orderer get endpoint rules. The console keeps resolving
  through the wildcard. With `expose_console: false`, the collection and the
  Job reach it through its in-cluster Service URL (sub-tasks 1.3 and 1.5),
  not through its FQDN.
- The rules are pattern-based, so they also cover nodes added later
  (`peers: N`, extra orderer nodes) without touching CoreDNS again.
- Partial exposure is not covered by these rules: see the last note of
  sub-task 1.3b.
- Sub-task 1.6 assertions 3–6 verify this end to end. When `INGRESS_DOMAIN`
  is cluster-local, assertion 6 is skipped (no rewrite to verify).

---

## Sub-task 1.5 — CI workflow: `expose-none` matrix leg with in-cluster Ansible runner

**Intent:** Extend `fvtest.yml` with a second matrix leg (`expose-none`) that
validates the extreme opposite scenario on the nginx path. Because the
`expose-none` leg routes every endpoint FQDN to a per-endpoint ClusterIP Service
through in-cluster CoreDNS rewrites (sub-tasks 1.3b and 1.4b), the GitHub
Actions runner — which is **outside** the KIND cluster — cannot resolve those
FQDNs: its `:443` traffic would still reach nginx through the KIND host-port
mapping, which is exactly the path this leg must not use.
The `expose-none` leg therefore runs the tutorial Ansible playbooks **from inside
the cluster** using a Kubernetes Job.

**Expected outcomes:**
- `fvtest.yml` runs two legs on every push:
  1. `expose-all` — all `expose_*: true`; playbooks run directly on the runner
     (current behaviour, no change to this path).
  2. `expose-none` — all `expose_*: false`; playbooks run inside the KIND
     cluster as a Kubernetes Job.
- `fail-fast: false` is set so both legs always complete.
- The `expose-none` leg succeeds: build, join, and deploy all exit 0.

**Job manifest specification:**

The Kubernetes Job YAML (committed to `.github/k8s/ansible-runner-job.yml` or
inlined in the CI script) must specify:

- **Container image**: an image containing Python 3, Ansible,
  `hyperledger.fabric_ansible_collection` (installed from the collection
  tarball built in the same CI run), the Hyperledger Fabric `peer` binary, and
  `configtxlator`. Use the same set of dependencies that the Actions runner
  installs for the `expose-all` leg. Base the image on
  `hyperledger/fabric-tools:<version>` and layer Ansible on top; document the
  resulting Dockerfile at `.github/docker/ansible-runner/Dockerfile`.
- **`restartPolicy: Never`** and `backoffLimit: 0` — failures surface as a
  failed Job rather than silent retries.
- **Tutorial files in the image**: the `tutorial/` directory is copied into the
  image at `/workspace/tutorial` and the image is rebuilt on every CI run. A
  ConfigMap mount is not an option: it is read-only (the playbooks write their
  JSON identity files into the working directory), it flattens the directory
  tree (`--from-file` does not recurse) and it is limited to 1 MiB.
- **Permissions**: a `ServiceAccount` (`ansible-runner`) with a `Role` and a
  `RoleBinding` in the network namespace, referenced by `serviceAccountName`.
  The Job creates and deletes the per-endpoint Services (sub-task 1.3b), so the
  role needs `get`, `list`, `create`, `update`, `patch` and `delete` on
  `services`, and `get` / `list` on `deployments` for the console readiness
  wait. `kubernetes.core` uses the in-cluster configuration: no kubeconfig is
  mounted. Start from this minimal set and widen it only on a `Forbidden`
  error.
- **`api_endpoint` override**: the in-cluster console Service URL
  `https://<console-svc>.<namespace>.svc.<cluster_domain>:3000` (HTTPS, see
  sub-task 1.3).
- **Environment variables** injected for: `INGRESS_TYPE`, `EXPOSE_CA`,
  `EXPOSE_PEER`, `EXPOSE_ORDERER`, `EXPOSE_CONSOLE`, `WAIT_TIMEOUT`,
  `K8S_NAMESPACE`.
- **Job command** (with `set -e`):
  ```bash
  set -e
  cd /workspace/tutorial
  bash build_network.sh build
  bash join_network.sh join
  bash deploy_smart_contract.sh
  ```

**Todo list:**
- [ ] Add a `scenario` matrix dimension to the `fvtest` job in
  `.github/workflows/fvtest.yml` with values `[expose-all, expose-none]`.
  Set `fail-fast: false` on the matrix.
- [ ] For `expose-all`: set `EXPOSE_CONSOLE=true`, `EXPOSE_CA=true`,
  `EXPOSE_PEER=true`, `EXPOSE_ORDERER=true` in `$GITHUB_ENV`. Keep existing
  runner-side `run-tests.sh` invocation — this path is unchanged.
- [ ] For `expose-none`: set all four `EXPOSE_*` flags to `false` in
  `$GITHUB_ENV`. Keep `INGRESS_TYPE=nginx`.
- [ ] Create `.github/docker/ansible-runner/Dockerfile` based on
  `hyperledger/fabric-tools:<version>` with Ansible and
  `hyperledger.fabric_ansible_collection` layered on top, and the `tutorial/`
  directory copied to `/workspace/tutorial`.
- [ ] Create `.github/k8s/ansible-runner-job.yml` with the `ServiceAccount`,
  `Role`, `RoleBinding` and `Job`.
- [ ] Add the following CI steps, each guarded by
  `if: matrix.scenario == 'expose-none'`:
  1. **Build and load runner image**: build the collection tarball, then
     `docker build -t ansible-runner:ci -f .github/docker/ansible-runner/Dockerfile .`
     (the repository is the build context, so the image contains `tutorial/`
     and the tarball), then `kind load docker-image ansible-runner:ci`
  2. **Apply the manifests** (ServiceAccount, Role, RoleBinding, Job):
     `kubectl apply -f .github/k8s/ansible-runner-job.yml`
  3. **Wait for Job completion**:
     `kubectl wait --for=condition=complete --timeout=20m job/ansible-runner`
  4. **Retrieve logs** (unconditional, runs even on failure — use
     `if: always() && matrix.scenario == 'expose-none'`):
     `kubectl logs job/ansible-runner`
  5. **Assert Job succeeded**:
     ```bash
     phase=$(kubectl get job ansible-runner \
       -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')
     [ "$phase" == "True" ] || exit 1
     ```
- [ ] Add `name: FV test (nginx / ${{ matrix.scenario }})` to the job.
- [ ] Run `yamllint` on the modified workflow file.
- [ ] Commit `.github/k8s/ansible-runner-job.yml` and
  `.github/docker/ansible-runner/Dockerfile` as part of this sub-task.

**Relevant context:**
- The `expose-all` leg is entirely unaffected by this sub-task — the `if:`
  conditions ensure the Job steps are skipped when `matrix.scenario == 'expose-all'`.
- The Job image must be available inside the KIND cluster (use
  `kind load docker-image` after building locally or in CI).
- Gateway API (`ingress_type: gateway-api`) matrix legs are **not** added in
  this step; leave a comment stub for Step 2.
- Reference full matrix design: MIGRATION-PLAN.md §5.3.4.

---

## Sub-task 1.6 — In-cluster service reachability assertions

**Intent:** Define explicit, automatable assertions for the `expose-none` CI leg
that verify in-cluster reachability without relying on the external runner's
network access. All assertions run as ephemeral pods via
`kubectl run --rm -i --restart=Never` and execute as a CI step **after** the
in-cluster Ansible Job from sub-task 1.5 completes.

**Expected outcomes:**
- Six named assertions all pass in the `expose-none` leg.
- The `expose-all` leg is unaffected (assertions are guarded by
  `if: matrix.scenario == 'expose-none'`).
- Any single failing assertion produces a clear, actionable error message
  identifying the misconfigured resource.

**Todo list:**

- [ ] **Assertion 1 — No external Ingress objects for CA/peer/orderer**
  (runner-side, no ephemeral pod needed):
  ```bash
  NS="${K8S_NAMESPACE:-default}"
  count=$(kubectl get ingress -n "$NS" -o name \
    | grep -cvE 'console' || true)
  [ "$count" -eq 0 ] \
    || (echo "Unexpected Ingress objects found for non-console components" && exit 1)
  ```
  _Failure indicates_: an `expose_*` flag was not honoured by the operator, or
  the Ansible role created Ingress objects despite `expose_*: false`.

- [ ] **Assertion 2 — Console ClusterIP Service responds** at its in-cluster
  URL, over HTTPS (self-signed certificate, hence `-k`), on the unauthenticated
  `/health` path (see sub-task 1.3; `/ak/api/v3/health` answers 401):
  ```bash
  NS="${NAMESPACE:-default}"
  kubectl run curl-console --image=curlimages/curl:8.10.1 \
    --restart=Never --rm -i --namespace "$NS" -- \
    curl -skf "https://${CONSOLE_NAME:-hlf-console}.${NS}.svc.${CLUSTER_DOMAIN:-cluster.local}:3000/health"
  ```
  _Failure indicates_: the console pod is not running, the Service selector is
  wrong, or the protocol or the health path changed.

- [ ] **Assertions 3–6 — common preamble.** Endpoints are discovered from
  the labelled Services of sub-task 1.3b, so no node name is hardcoded:
  ```bash
  NS="${NAMESPACE:-default}"
  DOMAIN="${INGRESS_DOMAIN}"
  SEL=app.kubernetes.io/managed-by=fabric-ansible-collection
  svcs_of() {  # svcs_of <endpoint-type> -> Service names
    kubectl get svc -n "$NS" -l "$SEL,fabric-ansible-collection/endpoint=$1" \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
  }
  incluster() {  # incluster <name> <image> <cmd...>
    kubectl run "$1" --image="$2" --restart=Never --rm -i --quiet \
      --namespace "$NS" --command -- "${@:3}"
  }
  ```

- [ ] **Assertion 3 — One Service per endpoint, correct target port, ready
  backends.** Static check of the endpoint → port mapping table (sub-task
  1.3b). It proves that `-operations`, `-grpcweb` and `-admin` do not
  target the API port:
  ```bash
  declare -A want=( [ca/ca]=7054 [ca/operations]=9443
                    [peer/peer]=7051 [peer/operations]=9443 [peer/grpcweb]=7443
                    [orderer/orderer]=7050 [orderer/admin]=9443
                    [orderer/operations]=8443 [orderer/grpcweb]=7443 )
  for key in "${!want[@]}"; do
    comp="${key%/*}" ep="${key#*/}"
    names=$(kubectl get svc -n "$NS" \
      -l "$SEL,fabric-ansible-collection/component=$comp,fabric-ansible-collection/endpoint=$ep" \
      -o jsonpath='{.items[*].metadata.name}')
    [ -n "$names" ] || { echo "No $comp '$ep' Service found"; exit 1; }
    for svc in $names; do
      port=$(kubectl get svc -n "$NS" "$svc" -o jsonpath='{.spec.ports[?(@.port==443)].targetPort}')
      [ "$port" = "${want[$key]}" ] \
        || { echo "$svc: 443 -> $port, expected ${want[$key]}"; exit 1; }
      addrs=$(kubectl get endpoints -n "$NS" "$svc" -o jsonpath='{.subsets[*].addresses[*].ip}')
      [ -n "$addrs" ] \
        || { echo "$svc has no ready backend (selector assumption S3?)"; exit 1; }
    done
  done
  ```
  The `orderer/admin` entry is expected only on Fabric ≥ 2.4.1 (operator
  gate). Drop it from `want` for older pinned versions.
  _Failure indicates_: sub-task 1.3b skipped a component or endpoint type, or
  used a wrong target port, or the selector (S3) matches no pod.

- [ ] **Assertion 4 — Every operations endpoint answers `/healthz` on `:443`
  through its FQDN.** This exercises CoreDNS rewrite + per-endpoint Service
  + port 9443/8443, the path used by the console status checks and the
  collection's health waits:
  ```bash
  urls=$(svcs_of operations | sed "s|.*|https://&.${DOMAIN}/healthz|")
  incluster healthz curlimages/curl:8.10.1 sh -c '
    for u in '"$(echo $urls)"'; do
      curl -sk --connect-timeout 5 "$u" | grep -q "\"status\":\"OK\"" \
        || { echo "FAIL $u"; exit 1; }
    done'
  ```
  _Failure indicates_: the `operations` rewrite is missing, the Service
  targets the API port, or the node is unhealthy.

- [ ] **Assertion 5 — API, CA, grpcweb and admin endpoints accept TLS on
  `:443` through their FQDNs.** The CA `-ca` endpoint must return `/cainfo`
  JSON. For gRPC, grpcweb and the mTLS-only admin endpoint, a TLS-level
  answer is enough: curl exit 0, 35 (handshake alert, e.g. a client
  certificate is required) or 56. Exits 6, 7 and 28 (DNS failure, connection
  refused, timeout) fail. Port correctness is already proven by assertion 3:
  ```bash
  ca_urls=$(svcs_of ca | sed "s|.*|https://&.${DOMAIN}/cainfo|")
  tls_urls=$(for ep in peer orderer grpcweb admin; do svcs_of "$ep"; done \
    | sed "s|.*|https://&.${DOMAIN}/|")
  incluster tls-check curlimages/curl:8.10.1 sh -c '
    for u in '"$(echo $ca_urls)"'; do
      curl -sk --connect-timeout 5 "$u" | grep -q caName || { echo "FAIL $u"; exit 1; }
    done
    for u in '"$(echo $tls_urls)"'; do
      rc=0; curl -sk -o /dev/null --connect-timeout 5 "$u" || rc=$?
      case $rc in 0|35|56) ;; *) echo "FAIL $u (curl exit $rc)"; exit 1;; esac
    done'
  ```
  _Failure indicates_: a rewrite for that endpoint type is missing, or the
  Service has no backend.

- [ ] **Assertion 6 — Each endpoint FQDN resolves to its own Service's
  ClusterIP** (not nginx, and not a sibling endpoint's Service). This
  confirms the sub-task 1.4b rewrites. Skipped when `INGRESS_DOMAIN` is
  cluster-local:
  ```bash
  pairs=$(kubectl get svc -n "$NS" -l "$SEL" \
    -o jsonpath='{range .items[*]}{.metadata.name}={.spec.clusterIP}{" "}{end}')
  incluster dns-check busybox:1.36.1 sh -c '
    for p in '"${pairs}"'; do
      fqdn="${p%%=*}.'"${DOMAIN}"'"; want="${p#*=}"
      got=$(nslookup "$fqdn" | awk "/^Address/ {a=\$2} END {print a}")
      [ "$got" = "$want" ] || { echo "FAIL $fqdn -> $got, expected $want"; exit 1; }
    done'
  ```
  _Failure indicates_: `coredns_endpoint_rewrites` was not emitted (check
  the `EXPOSE_*` / `INGRESS_DOMAIN` env passed to `kind_with_nginx.sh`), the
  `[a-z0-9]+` CR pattern does not match (assumption S1), or CoreDNS was not
  restarted.

- [ ] Add all six assertions as a single `"Verify expose-none reachability"` step
  in `fvtest.yml`, conditioned on `if: matrix.scenario == 'expose-none'`.
- [ ] Use `set -euo pipefail` at the top of the step's `run:` block so the
  first failing assertion aborts the step. Commands whose non-zero exit is
  expected are wrapped as `rc=0; cmd || rc=$?`.

**Relevant context:**
- Nothing is hardcoded: the namespace, the console name and the cluster domain
  of assertions 1 and 2 come from the CI environment. Assertions 3–6 take the
  list of endpoints from the Services the collection created (labels), so every
  organization (Org1, Org2, …) and every node is covered, whatever the CI
  namespace, domain (`default`, `<ip>.nip.io`, `localho.st`) or randomised
  names.
- Assertions 3–6 cover **every** endpoint of **every** node, discovered from
  the `fabric-ansible-collection/*` labels. Adding peers or orderer nodes
  needs no change here.
- Sub-tasks 1.3b and 1.4b must be complete before assertions 3–6 can pass.

---

## Sub-task 1.7 — Tutorial: nginx expose-all scenario (no-regression)

**Intent:** Update or create a tutorial that explicitly demonstrates the
current default nginx deployment (all services exposed). This is a reference
baseline that confirms no regression and documents the `expose_*` variable schema
for users.

**Expected outcomes:**
- Tutorial page at `docs/source/tutorials/nginx-expose-all.rst` (new) or updated
  inline in `docs/source/tutorials/oss-installing.rst` with a dedicated section.
- Documents `ingress_type: nginx` (default), `expose_console: true`, and the
  other `expose_*: true` defaults.
- Shows how to set these variables in a vars file (e.g. `common-vars.yml`) or
  via `ansible-playbook -e @vars.yml`.
- Documents the existing `kubectl get ingress` verification steps.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Decide whether to add a new page or a section in the existing
  `oss-installing.rst`; document the decision in the plan file.
- [ ] Add a "Variables reference" table listing all `expose_*` and `ingress_type`
  variables with their defaults and effects (as specified in MIGRATION-PLAN.md §5.1).
- [ ] Add a verification step showing `kubectl get ingress -n <namespace>` output
  when all services are exposed.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Files to update: `docs/source/tutorials/oss-installing.rst`,
  `docs/source/tutorials/hlfsupport-installing.rst`.
- Role reference files: `docs/source/roles/fabric-operator-crds.rst`,
  `docs/source/roles/fabric-console.rst`.

---

## Sub-task 1.8 — Tutorial: nginx no-expose scenario

**Intent:** Create a new tutorial that demonstrates the extreme opposite scenario:
deploying a Hyperledger Fabric network on a single cluster where no service is
exposed externally through the NGINX ingress controller. This is the canonical
Scenario A (in-cluster only) tutorial.

**Expected outcomes:**
- New tutorial page at
  `docs/source/tutorials/nginx-no-expose.rst`.
- Demonstrates setting `expose_console: false`, `expose_ca: false`,
  `expose_peer: false`, `expose_orderer: false` in a vars file.
- Explains that the collection will health-check the console via its in-cluster
  ClusterIP Service URL and print a notice instead of a public URL.
- Explains that Fabric components communicate via ClusterIP Services inside the
  cluster.
- Shows that `kubectl get ingress -n <namespace>` returns no resources.
- Added to the `toctree` in `docs/source/index.rst`.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Create `docs/source/tutorials/nginx-no-expose.rst` with:
  - Prerequisites section (nginx ingress controller installed but routes not
    required for in-cluster use).
  - Example vars file showing all `expose_*: false` and `ingress_type: nginx`.
  - Step-by-step playbook execution using `ansible-playbook -e @no-expose-vars.yml`.
  - Verification: `kubectl get ingress` returns empty; console notice message
    appears in playbook output.
  - Explanation of when to use this scenario (single-cluster bootstrap, GitOps
    lead-org setup, development environment).
- [ ] Add `nginx-no-expose` to the `toctree` in `docs/source/index.rst`.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Scenario A rationale: PRE-ANALYSIS.md §2.4 and §2.5.
- Console notice message implementation: sub-task 1.3 above.
- In-cluster console URL: `https://{{ console }}.{{ namespace }}.svc.{{ cluster_domain }}:3000`
  (health path `/health`, see sub-task 1.3)

---

## Acceptance criteria for Step 1

A Step 1 delivery is considered complete when all of the following pass:

1. `ansible-lint` and `yamllint` pass on all modified files.
2. `run-tests.sh` correctly injects all `ingress_type` and `expose_*` variables into `common-vars.yml` (and passes `bash -n` validation).
3. `fvtest.yml` matrix runs two legs: `nginx/expose-all` and
   `nginx/expose-none`; both complete successfully with `fail-fast: false`.
4. The `nginx/expose-all` leg is byte-for-byte equivalent in test coverage to
   the pre-Step-1 single-leg run — no existing test scenario has been removed
   or weakened.
5. The `nginx/expose-none` leg runs the tutorial playbooks inside the KIND
   cluster via a Kubernetes Job (sub-task 1.5) and all six reachability
   assertions pass (sub-task 1.6): no Ingress objects for CA/peer/orderer;
   console health endpoint returns HTTP 200 in-cluster; one Service per
   endpoint exists with the expected `443 → targetPort` and ready backends;
   every operations FQDN answers `/healthz` on `:443`; every API, CA, grpcweb
   and admin FQDN accepts TLS on `:443`; each endpoint FQDN resolves to its
   own Service's ClusterIP.
6. In `expose-none` mode the collection creates **one ClusterIP Service per
   endpoint** (CA: `ca`, `operations`; peer: `peer`, `operations`, `grpcweb`;
   orderer: `orderer`, `admin`, `operations`, `grpcweb`), each mapping `443`
   to that endpoint's native port (sub-task 1.3b), with **one CoreDNS rewrite
   per endpoint type** (sub-task 1.4b). The operator's own Services are left
   unmodified, and console registry entries are not mutated.
7. Cluster-local domain handling (sub-tasks 1.1 and 1.1b):
   - Setting `console_domain: <namespace>.svc.<cluster_domain>` with all
     `expose_*: false` runs without error: the per-endpoint Services are
     created and no CoreDNS rewrite is applied.
   - Setting `console_domain: <namespace>.svc.<cluster_domain>` with any
     `expose_*: true` (or a CA/peer/orderer flag missing from the console
     play) causes the console play to fail immediately with a message listing
     the conflicting flags.
   - Setting any other `*.<cluster_domain>` value (e.g. `svc.cluster.local`)
     fails immediately, naming the only supported form.
   - The cluster domain is auto-discovered from the `kube-system/coredns`
     ConfigMap (`kubernetes` plugin line); when discovery fails, a warning is
     printed (not an error) and `cluster.local` is used. An explicit
     `cluster_domain` that contradicts the discovered value fails the play.
8. `docs/source` builds without warnings (`make -C docs html`).
9. No Gateway API CRD, template, task, or Kubernetes resource is introduced —
   the Gateway API path is entirely absent from the codebase at this stage.
10. Each role declares in its own `defaults/main.yml` the new variables it
    reads (sub-task 1.1 table); no role reads a variable declared only in
    another role.
