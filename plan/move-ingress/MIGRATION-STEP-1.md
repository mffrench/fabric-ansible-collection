# Step 1 — Expose Options with NGINX Ingress Controller

**Roadmap reference:** [`MIGRATION-ROADMAP.md`](./MIGRATION-ROADMAP.md) — Step 1
**Plan reference:** [`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) — W1, partial W5, partial W3, partial W7 (W4 moved to Step 2)
**Prerequisite:** [`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md) (Baseline CI & Test Runner Fixes)
**Status:** `[ ] pending`

---

## Overview

This deliverable builds on the working baseline established in **Step 0** ([`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md)). It introduces all new Ansible variables (`ingress_type`, `expose_*`) and makes the collection's console wait-logic aware of the `expose_console` flag, while the **nginx ingress controller remains the only supported and tested ingress backend**. No Gateway API resources, templates, or CRDs are introduced yet.

The primary goals of this step are:
1. Establish the stable variable schema that Steps 2 and 3 will build on.
2. Prove there is no regression in the working nginx-backed test suite (the all-exposed baseline from Step 0).
3. Validate the extreme opposite scenario: a deployment where nothing is exposed
   through the NGINX ingress controller (`expose_console: false`,
   `expose_ca: false`, `expose_peer: false`, `expose_orderer: false`).

**Domain and URL design.** This step follows
[`URL-MANAGEMENT-NEW.md`](./URL-MANAGEMENT-NEW.md) (decisions D1–D5, checks
of 2026-10-16). How URLs are built today is in
[`URL-MANAGEMENT-EXISTING.md`](./URL-MANAGEMENT-EXISTING.md). In short:
`exposed_domain` (formerly `console_domain`) builds the console URL;
`hlf_network_domain` builds the node FQDNs; when it equals the cluster
domain, node FQDNs are Kubernetes Service FQDNs and need no CoreDNS rewrite.
Scenario letters below follow URL-MANAGEMENT-NEW.md §4: **A** everything
exposed (default), **B** nothing exposed with a cluster-local HLF domain
(Step 1 target, CI leg `expose-none-internal`), **C** nothing exposed with
the previous flat FQDNs (CI leg `expose-none`).

---

## Sub-task 1.1 — Shared role `network_domains` (variables, domains, facts)

**Design reference:** [`URL-MANAGEMENT-NEW.md`](./URL-MANAGEMENT-NEW.md)
§3 (variables), §6 (scope), §10 (decisions D1–D5). How URLs are built today:
[`URL-MANAGEMENT-EXISTING.md`](./URL-MANAGEMENT-EXISTING.md).

**Intent:** Introduce every new variable with safe defaults, so all existing
playbooks keep working unchanged, and compute the domain facts **once**, in
one place reachable from every role. This replaces the earlier
`fabric_operator_crds/tasks/k8s/set_facts.yml` design, which could not work
(REVIEW-MIGRATION-PLAN-STEP-1.md, "Variables and facts"):

- defaults of `fabric_operator_crds` are not visible from `fabric_console`,
  `endorsing_organization` or `ordering_organization` (separate playbooks);
- `include_tasks: set_facts.yml` from `hlfsupport_console` looks for the file
  in its own role;
- `ingress_domain_is_cluster_local` was used in the organization roles
  without ever being defined there;
- `cluster_domain` discovery through `kubectl exec deployment/coredns -- awk`
  always fails (distroless image, `dnsPolicy: Default`, needs `pods/exec`).

The logic therefore lives in a new internal role, `network_domains`, that
every role calls with `include_role` (`public: true`).

**Variables** (defaults in `roles/network_domains/defaults/main.yml`):

| Variable | Meaning | Default |
|---|---|---|
| `ingress_type` | Ingress backend; only `nginx` in Step 1 | `nginx` |
| `expose_console`, `expose_ca`, `expose_peer`, `expose_orderer` | Component reachable from outside the cluster | `true` |
| `expose_peer_operations`, `expose_orderer_operations`, `expose_grpcweb` | Sub-flags, consumed in Step 3 | `false` |
| `exposed_domain` | Domain users see: console URL and console TLS SAN, even when not exposed. **Replaces `ingress_domain`**, which no task or template ever used. | `""` → `console_domain` |
| `console_domain` | **Deprecated alias** of `exposed_domain` (D5), still mandatory-or-`exposed_domain` | — |
| `hlf_network_domain` | Domain of the HLF nodes. `= cluster_domain`: node FQDNs are Kubernetes Service FQDNs. Otherwise: previous flat FQDNs. | `""` → `exposed_domain` (D2) |
| `cluster_domain` | Kubernetes cluster DNS zone | `""` → read from `kube-system/coredns` |
| `unexposed_ingress_class` | Ingress class no controller serves (D3) | `none` |
| `neutralize_node_ingresses` | Also apply it to unexposed node CRs (D4, sub-task 1.3c) | `false` |
| `gateway_class_name`, `ingress_ca_port`, `ingress_grpc_orderer_port`, `ingress_grpc_peer_port` | Gateway API settings, inert until Step 2 | `fabric-envoy-gateway`, 7054, 7050, 7051 |

Caller-provided: `network_domains_namespace` (namespace of the console and of
every node), `network_domains_console_name`.

**Facts** (computed; names distinct from the inputs, so an input passed with
`-e` never hides a computed value):

| Fact | Value |
|---|---|
| `network_domains_exposed_domain` | `exposed_domain` or `console_domain`, lowercased, no trailing dot |
| `network_domains_hlf_network_domain` | `hlf_network_domain` or the exposed domain |
| `network_domains_cluster_domain` | resolved cluster domain (`""` when not needed, see below) |
| `hlf_network_domain_is_cluster_local` | `hlf_network_domain == cluster_domain` (D1) |
| `hlf_node_domain` | `<namespace>.svc.<cluster_domain>` if cluster-local, else the HLF network domain. It is the value of the node CRs' `spec.domain`. |
| `console_url` | `https://<namespace>-<console_name>-console.<exposed_domain>` |
| `console_incluster_url` | `https://<console_name>.<namespace>.svc.<cluster_domain>:3000` |

**Validation (fail fast):**

| # | Rule |
|---|---|
| — | `exposed_domain` and `console_domain`, when both set, are equal; at least one is set |
| V1 | `exposed_domain` is neither the cluster domain nor inside it |
| V2 | `hlf_network_domain` is the cluster domain or outside it; a sub-zone (`default.svc.cluster.local`) is rejected, naming the cluster domain as the value to use |
| V3 | cluster-local `hlf_network_domain` ⇒ `expose_ca`, `expose_peer`, `expose_orderer` all `false` (`expose_console` free) |
| V4 | `<namespace>-<console_name>-console` ≤ 63 characters |
| V5 | after each node module call, every returned URL host ends with `.` + `hlf_node_domain` (`tasks_from: verify_urls`, sub-task 1.3b) |

**Resolution of `cluster_domain`.** The cluster domain is read from the
Corefile in the `kube-system/coredns` ConfigMap, the source of truth CoreDNS
itself uses. Its `kubernetes` plugin line lists the cluster domain, then the
reverse zones:

```
kubernetes cluster.local in-addr.arpa ip6.arpa {
```

This only needs `get` on one ConfigMap through `kubernetes.core.k8s_info`. It
runs only when the cluster domain matters: a component is unexposed, the HLF
network domain differs from the exposed one, `cluster_domain` is set, or the
caller asks for it (`network_domains_resolve_cluster_domain`). With the
defaults (everything exposed, one domain) the role needs **no cluster
access**, so the REST-only path of the organization roles is unchanged.

| Lookup result | `cluster_domain` set by the user | Outcome |
|---|---|---|
| discovered `D` | empty (default) | `D` |
| discovered `D` | `D` | `D` (double-checked) |
| discovered `D` | `X ≠ D` | **fail**: names both values |
| not discoverable | `X` | **warning**: could not verify, trusting `X` |
| not discoverable | empty | **fail**: asks the user to set `cluster_domain` |

"Not discoverable" covers an absent or unreadable ConfigMap, or one without a
`kubernetes` line: GKE with kube-dns, OpenShift (`openshift-dns/dns-default`),
CoreDNS under another name, restricted RBAC. Comparisons are
case-insensitive and ignore a trailing dot. The role never guesses
`cluster.local`.

**Prototype.** The full role is in
[`.url_management_new_checks/network_domains/roles/network_domains/`](./.url_management_new_checks/network_domains/roles/network_domains/)
(`defaults/main.yml`, `tasks/main.yml`, `tasks/cluster_domain.yml`,
`tasks/verify_urls.yml`). On 2026-10-16 it passed `yamllint` and
`ansible-lint` (production profile), and all 13 cases of
`test.yml` against the live KIND CoreDNS ConfigMap (scenarios A, B, C, D;
alias and its conflict; V1, V2, V3; cluster-domain match, mismatch, and
case/trailing dot), plus `test_extra_vars.yml` with an empty
`-e cluster_domain=`. Core of `tasks/main.yml`:

```yaml
- name: Set the HLF network facts
  ansible.builtin.set_fact:
    hlf_network_domain_is_cluster_local: >-
      {{ network_domains_cluster_domain != ''
         and network_domains_hlf_network_domain == network_domains_cluster_domain }}

- name: Set the HLF node domain
  ansible.builtin.set_fact:
    hlf_node_domain: >-
      {{ (network_domains_namespace ~ '.svc.' ~ network_domains_cluster_domain)
         if hlf_network_domain_is_cluster_local | bool
         else network_domains_hlf_network_domain }}
```

**Calls** (each role, at the top of `tasks/create.yml` and `tasks/delete.yml`,
before any task that branches on `expose_*` or a domain fact):

```yaml
- name: Compute the network domains
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.network_domains
    public: true
  vars:
    network_domains_namespace: "{{ namespace }}"        # k8s_namespace in the organization roles
    network_domains_console_name: "{{ console_name }}"  # console in hlfsupport_console; omitted in the organization roles
```

| Caller | Uses |
|---|---|
| `fabric_console`, `hlfsupport_console` (+ `tutorial/00-deploy-fabric-console.yml`, what CI runs) | `exposed_domain`, `hlf_node_domain`, `console_url`, `console_incluster_url` (sub-tasks 1.3, 1.3a) |
| `endorsing_organization`, `ordering_organization` | `hlf_node_domain`, `hlf_network_domain_is_cluster_local`, `verify_urls` (sub-task 1.3b) |
| `fabric_operator_crds` | nothing in Step 1. Its unused `ingress_domain` default is removed. |

**Expected outcomes:**
- `roles/network_domains/` exists, with the variables and facts above.
- Every role listed above includes it; no role reads another role's
  defaults.
- With no new variable set, the role computes `hlf_node_domain =
  console_domain`, prints the `console_domain` deprecation notice, and reads
  nothing from the cluster.
- `ansible-lint` and `yamllint` pass on all modified files.
- All existing tests pass without setting any new variable.

**Todo list:**
- [ ] Copy the prototype into `roles/network_domains/` and add
  `meta/main.yml` (internal role, no dependencies).
- [ ] Include it in `roles/fabric_console/tasks/create.yml`,
  `roles/hlfsupport_console/tasks/create.yml`, both organization roles'
  `create.yml` and `delete.yml`, and `tutorial/00-deploy-fabric-console.yml`.
- [ ] Replace the `console_domain not specified` checks in
  `roles/fabric_console/tasks/create.yml:10-13` and
  `roles/hlfsupport_console/tasks/create.yml:10-13` by the role's own check.
- [ ] Remove `ingress_domain: localho.st` from
  `roles/fabric_operator_crds/defaults/main.yml:46`.
- [ ] Add `exposed_domain` and `hlf_network_domain` to
  `tutorial/common-vars.yml`, commented out, with their defaults.
- [ ] Move `test.yml` / `test_case.yml` / `test_extra_vars.yml` from the
  prototype to the collection's test tree (or a molecule scenario).
- [ ] Run `ansible-lint` and `yamllint` on all modified and new files.

**Relevant context:**
- The defaults file holds no logic; all logic is in the tasks.
- `public: true` exposes the role's defaults to the caller, so a caller can
  use `expose_*` directly after the include.
- In ansible-core 2.18, a templated `set_fact: "{{ dict }}"` is a silent
  no-op (found while testing). The role never uses that form.
- Port variables `ingress_*_port` are Gateway API listener ports for Step 2,
  **not** the native target ports of sub-task 1.3b.
- The identity that runs the playbooks needs `get` on
  `kube-system/configmaps/coredns` for the `cluster_domain` lookup. Without
  it, `cluster_domain` must be set by hand. The in-cluster CI Job gets it
  through its own Role (sub-task 1.5).
- The former sub-task 1.2 (`gateway.networking.k8s.io` RBAC rules) moved to
  [`MIGRATION-STEP-2.md`](./MIGRATION-STEP-2.md) sub-task 2.0 on 2026-10-16:
  Step 1 introduces no Gateway API object (acceptance criterion 9).

---

## Sub-task 1.1b — Validation tests for the domain rules

**Intent:** Freeze the behaviour of `network_domains` with automated tests,
so the rules of sub-task 1.1 (alias, V1–V4, cluster-domain reconciliation,
D1) cannot regress. The rules themselves live in the role; this sub-task only
adds the tests and their CI hook.

| `exposed_domain` | `hlf_network_domain` | `expose_ca/peer/orderer` | Expected |
|---|---|---|---|
| `127-0-0-1.nip.io` (or via `console_domain`) | unset | `true` | pass: `hlf_node_domain = 127-0-0-1.nip.io`, no cluster read (scenario A) |
| `example.com` | `cluster.local` | `false` | pass: `hlf_node_domain = default.svc.cluster.local`, cluster-local, **no CoreDNS rewrite** (scenario B) |
| `example.com` | `cluster.local` | `false`, console exposed | pass (console may be exposed) |
| `example.com` | `cluster.local` | any `true` | **fail** V3, naming the flags |
| `example.com` | `default.svc.cluster.local` | any | **fail** V2, naming `cluster.local` |
| `svc.cluster.local` | any | any | **fail** V1 |
| `127-0-0-1.nip.io` | unset | `false` | pass: previous flat FQDNs, rewrites needed (scenario C) |
| `example.com` | `fabric.example.com` | `true` | pass: `hlf_node_domain = fabric.example.com` (scenario D) |
| `a.example.com` + `console_domain: b.example.com` | — | — | **fail**: alias conflict |
| — | — | `cluster_domain: corp.internal` on a `cluster.local` cluster | **fail**: mismatch |

**Expected outcomes:**
- The table above runs as one test playbook against a KIND cluster (it needs
  the real `kube-system/coredns` ConfigMap) and in CI (`expose-all` leg, no
  extra cluster).
- Each failing case fails with the role's message, not a template error.

**Todo list:**
- [ ] Port the prototype `test.yml` (13 cases, 2026-10-16: all pass) to the
  collection's test tree.
- [ ] Add a "network_domains rules" step to `fvtest.yml`, before
  `run-tests.sh`.
- [ ] Add a case with the ConfigMap unreadable (a ServiceAccount without
  `get configmaps` in `kube-system`): set `cluster_domain` → warning; unset →
  failure.

**Relevant context:**
- `expose_peer_operations`, `expose_orderer_operations` and `expose_grpcweb`
  are sub-flags of `expose_peer` / `expose_orderer` and are not checked by V3.

---

## Sub-task 1.3 — Console wait-logic for `expose_console` flag

**Intent:** Make the console wait and the printed URL independent of whether
the console is exposed. The console URL is always `console_url`, built from
`exposed_domain` (sub-task 1.1); only how the collection **reaches** the
console changes.

**What exists today** (the "split" is not the same in both roles):
- `roles/hlfsupport_console/tasks/k8s/create.yml:146-173` waits for the
  console Ingress, reads `console_url` from its host, polls it, prints it.
- `roles/fabric_console/tasks/k8s/create.yml:40-59` only waits for the
  Deployment and prints a URL it builds itself. There is no Ingress wait to
  split.
- CI uses neither role: `tutorial/00-deploy-fabric-console.yml` creates an
  inline `IBPConsole` and waits for the Deployment. It must get the same
  changes, or CI never exercises them.

**Expected outcomes:**
- `expose_console: true` (default): unchanged behaviour. `hlfsupport_console`
  still waits for its Ingress and polls `console_url`.
- `expose_console: false`:
  - no Ingress wait;
  - readiness is the console Deployment's `Available` condition
    (`kubernetes.core.k8s_info`), because the Ansible control node cannot
    resolve `console_incluster_url` when it runs outside the cluster;
  - a notice prints `console_url` (not served yet), `console_incluster_url`
    and how to expose it later (URL-MANAGEMENT-NEW.md §5.1).
- The console serves **HTTPS** on port 3000 (athena terminates TLS,
  URL-MANAGEMENT-NEW.md §5.3; checked 2026-10-16, check 4). Every in-cluster
  console URL in this plan is `https://<console>.<ns>.svc.<cluster_domain>:3000`,
  never `http://`.

**Todo list:**
- [ ] `roles/hlfsupport_console/tasks/k8s/create.yml`: guard the existing
  "Wait for console ingress to exist", "Set console URL from console
  ingress" and "Wait for console ingress to start" tasks with
  `expose_console | bool`.
- [ ] Add, guarded by `not expose_console | bool`:
  - `Wait for console Deployment to be Available` (`k8s_info`, `until`
    the `Available` condition is `True`);
  - `Print console exposition notice` (`console_url`, `console_incluster_url`,
    pointer to the manual exposure examples).
- [ ] `roles/fabric_console/tasks/k8s/create.yml:57-59` and
  `tutorial/00-deploy-fabric-console.yml:143-145`: print `console_url`, and
  the same notice when `expose_console: false`.
- [ ] Do **not** add any Gateway API (`ingress_type == 'gateway-api'`) branch
  yet; it belongs in Step 2.
- [ ] Run `ansible-lint` on the modified files.

**Relevant context:**
- MIGRATION-PLAN.md §5.5 has a first draft of these tasks; it predates the
  `exposed_domain` / `console_url` design and uses `http://`. Follow this
  sub-task instead.
- Health path: the CI checks use `/ak/api/v3/health` with Basic auth (it
  returns 401 without credentials). Use the same path everywhere.

---

## Sub-task 1.3a — `IBPConsole`: exposed domain, HLF node domain, unexposed Ingress

**Design reference:** URL-MANAGEMENT-NEW.md §2, §5.2, §7.1 (C2, C3, C6).

**Intent:** Render the three console fields that decouple the domains,
without changing the CR in the default case. All three fields already exist
in the operator's `IBPConsole` CRD (G2: no operator change).

| Field | Value | Rendered when |
|---|---|---|
| `spec.networkinfo.domain` | `network_domains_exposed_domain` | always (as today, from `console_domain`) |
| `spec.deployer.domain` | `hlf_node_domain` | `hlf_node_domain != network_domains_exposed_domain` |
| `spec.ingress.class` | `unexposed_ingress_class` (`none`) | `not expose_console` |

Scenario B (`exposed_domain: example.com`, `hlf_network_domain: cluster.local`,
nothing exposed, namespace `default`) renders:

```yaml
spec:
  networkinfo:
    domain: "example.com"                  # console URL + console TLS SAN
  deployer:
    domain: "default.svc.cluster.local"    # every CA / peer / orderer FQDN
  ingress:
    class: "none"                          # console Ingress kept, not served
```

**Checked on 2026-10-16** (URL-MANAGEMENT-NEW.md §9): `deployer.domain`
reaches the node CRs and their URLs and TLS SANs (check 1); nginx stops
serving an Ingress of class `none` and serves it again when set back to
`nginx` (check 2); the console certificate names only the `exposed_domain`
host (check 4).

**Finding F1: the deployer reads its domain only at startup.** Patching
`spec.deployer.domain` on a running console updates the deployer ConfigMap,
but nodes created afterwards keep the old domain until the console pod
restarts. Hence:
- The field is rendered when the console is **created**: the normal path.
- On an existing console, the role compares the live
  `spec.deployer.domain` with `hlf_node_domain`. If they differ, it restarts
  the console Deployment after the CR update (`kubectl rollout restart`
  equivalent: patch the pod template annotation
  `kubectl.kubernetes.io/restartedAt`) and prints a warning: nodes created
  before keep their old domain and certificates (URL-MANAGEMENT-NEW.md §4.4).

**Expected outcomes:**
- Default variables: the rendered `IBPConsole` is the same as today, minus
  the duplicate `networkinfo:` key of the `fabric_console` templates (YAML
  kept the last copy; both held the same value).
- Scenario B: the three fields above are rendered; the console Ingress is
  unserved.
- Changing `hlf_network_domain` on an existing console restarts it and warns.

**Todo list:**
- [ ] `roles/fabric_console/templates/{k8s,openshift}/hlf-operations-console.yaml.j2`:
  `networkinfo.domain: "{{ network_domains_exposed_domain }}"`; remove the
  second `networkinfo:` block (`:34-35`); add the conditional `deployer:`
  and `ingress:` blocks.
- [ ] `roles/hlfsupport_console/templates/{k8s,openshift}/console.yml.j2`:
  same.
- [ ] `tutorial/00-deploy-fabric-console.yml`: same, on the inline CR
  (`hlf_console_domain` stays the input of `exposed_domain`).
- [ ] **Fix the `IBPConsole` `apiVersion` in every read and delete** (review,
  "Documentation inconsistencies" — it is a bug, not only a wording issue).
  The operator's CRDs serve **only `ibp.com/v1beta1`** (checked 2026-10-16 on
  KIND: `ibpconsoles.ibp.com` and `ibppeers.ibp.com` list a single version,
  `v1beta1`). Querying the running console with `kubernetes.core.k8s_info`:
  `api_version: ibp.com/v1alpha2` returns **0 resources and no error**
  (`api_found: false`); `ibp.com/v1beta1` finds it. So today "Determine if
  console exists" always concludes there is no console. Change to
  `ibp.com/v1beta1`:
  - `roles/fabric_console/tasks/k8s/create.yml:20`,
    `roles/fabric_console/tasks/openshift/create.yml:8`;
  - `roles/hlfsupport_console/tasks/k8s/create.yml:89`,
    `roles/hlfsupport_console/tasks/openshift/create.yml:85`;
  - `roles/hlfsupport_console/tasks/{k8s,openshift}/delete.yml:28`;
  - `roles/fabric_console/tasks/{k8s,openshift}/delete.yml:28`, which pick
    `v1alpha2` / `v1alpha1` from `product_version` and never `v1beta1`.
  The templates and `tutorial/00-{deploy,delete}-fabric-console.yml` already
  use `v1beta1`.
- [ ] Add the "domain changed on an existing console" detection and restart.
  It reads the live `IBPConsole`, so it depends on the `apiVersion` fix above.
- [ ] Render the templates for scenarios A and B with `ansible-playbook
  --check --diff` and compare with the examples above.

**Relevant context:**
- With the wrong `apiVersion`, `hlfsupport_console` also never sees an
  existing console in its upgrade path
  (`roles/hlfsupport_console/tasks/k8s/create.yml:113,122`: delete and
  recreate on `operator_upgrade`), so the fix changes upgrade behaviour too.
  Test an upgrade run (console already present) after the fix.
- The console's own Service is named after the CR (`hlf-console`, port
  `optools` 3000): that is `console_incluster_url`.
- The console certificate does not name `console_incluster_url`'s host
  (finding F2). The collection never verifies certificates
  (`validate_certs=False`), so it is unaffected; a strict in-cluster client
  needs `console_tls_secret` with that name as an extra SAN.

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
`<namespace>-<cr_name>-<endpoint>.<hlf_node_domain>` (`hlf_node_domain`
from sub-task 1.1, i.e. the node CRs' `spec.domain`). The collection names
each Service after the **first DNS label** of that FQDN:

```
Service name:  <namespace>-<cr_name>-<endpoint>        e.g. default-org1peer-operations
Service FQDN:  <namespace>-<cr_name>-<endpoint>.<namespace>.svc.<cluster_domain>
```

As a result:
- **Cluster-local HLF domain** (`hlf_network_domain_is_cluster_local`,
  scenario B): `hlf_node_domain` is `<namespace>.svc.<cluster_domain>`, so
  the operator's FQDNs **are** these Service FQDNs. No CoreDNS rewrite at all
  (checked 2026-10-16 on a CA: URL-MANAGEMENT-NEW.md §9 check 1).
- **Otherwise** (scenario C): CoreDNS needs **one** regex rewrite per
  endpoint type (`<ns>-*-<endpoint>.<hlf_node_domain>` → `<same
  label>.<ns>.svc.<cluster_domain>`, sub-task 1.4b), not one per node. The
  rules can be written before any node exists, which matters because each
  create module polls `operations_url/healthz` **inside** its own task (see
  `wait_for()` in `plugins/module_utils/ordering_services.py`). The Service
  and the rewrite must therefore exist before the module call returns.
- Each Service name is a valid DNS-1035 label (≤ 63 chars, starts with a
  letter) because it is also the first label of an FQDN the operator already
  generates. An `assert` still enforces this.

**Lifecycle.** The Services are created **before** the corresponding
`certificate_authority` / `peer` / `ordering_service` module call. Until the
operator starts the pods, a Service has no endpoints, which is harmless. The
module's own health wait then succeeds through the new Service. After the
module returns, two checks run:
1. **V5** (`network_domains`, `tasks_from: verify_urls`): every returned URL
   host ends with `.` + `hlf_node_domain`. It catches a console deployed
   with another domain, or a `k8s_namespace` different from the console
   namespace.
2. **Service match** (`k8s_endpoint_services`, `tasks_from: verify`): every
   returned URL (`api_url`, `operations_url`, `grpcwp_url`, `osnadmin_url`)
   has a created Service. It catches a wrong CR name (S1) or a missing
   endpoint type the health wait does not exercise (grpcweb, admin).

**How the CR name is known before the module call (S1).** The console, not
the operator, derives the CR name from the display name
(URL-MANAGEMENT-EXISTING.md §3): lowercase, characters outside
`[a-zA-Z0-9-_]` removed, prefix `ibp` if it starts with a digit, truncated
to 64, **a suffix added when the name is taken**, then `-` and `_` removed.
"Lowercase and remove non-`[a-z0-9]`" is right only for a fresh, letter-first
name. So:
- The pre-call name follows the simple rule and is **checked** against the
  first label of the returned URLs (check 2 above). A mismatch fails with a
  message naming the actual CR name.
- On reruns, the CR name is read from the returned URLs, not re-derived.
- A deterministic alternative is to send the CR name as the API `id` field,
  which athena uses verbatim (*athena* `libs/comp_formatting_lib.js:538,
  719-726`). The modules don't expose it today; adding an optional `id`
  parameter is a small plugin change, out of scope unless the check above
  fails in practice.

**Open finding F3** (URL-MANAGEMENT-NEW.md §9.1): a CA created with display
name `Check1 CA` was stored as `Check1`, and a later module call with
`Check1 CA` did not find it. Reproduce with a clean create (no failed health
wait) before relying on display names here.

**Assumptions** (encoded as role defaults, so that a wrong guess means a
default change, not a redesign):

| # | Assumption | Default encoding | Status |
|---|---|---|---|
| S1 | Fresh CR name = display name lowercased, every non-`[a-z0-9]` removed (`Org1 CA` → `org1ca`) | `k8s_endpoint_services_cr_name_regex: '[^a-z0-9]'` | **Partly true**: see above; checked after each call |
| S2 | Ordering node CR names are `<ordering service cr_name>node<i>`, `i` = 1..N | `k8s_endpoint_services_orderer_node_suffix: 'node'` | **Confirmed in source** (*operator* `pkg/offering/base/orderer/orderer.go:428`, `override/orderernode.go:59`) |
| S3 | Operator pods carry the label `app: <cr_name>` | `k8s_endpoint_services_selector_key: app` | **Confirmed on a CA** (2026-10-16: Service selector `app: check1`, per-endpoint Services got ready backends) |
| S4 | Node TLS certificates carry every endpoint FQDN as a SAN | — | **Confirmed**: in source for peer/orderer/CA (URL-MANAGEMENT-EXISTING.md §4.2), and on a CA with `hlf_node_domain = default.svc.cluster.local` (strict TLS passed) |

### New internal role `k8s_endpoint_services`

The three organization roles are separate playbooks and cannot share task
files, so the logic lives in a small role called via `include_role`. Its
Kubernetes dependency (`kubernetes.core`, a kubeconfig) is pulled in **only**
when a component is not exposed. The REST-only path of the organization roles
stays unchanged.

`roles/k8s_endpoint_services/defaults/main.yml`:

```yaml
# Namespace of the console and the nodes, passed by the caller.
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
      The CR name derived from the display name was wrong (assumption S1 of
      MIGRATION-STEP-1.md sub-task 1.3b); the console's CR name is the part
      between '{{ k8s_endpoint_services_namespace }}-' and the endpoint suffix.
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

`roles/endorsing_organization/tasks/create.yml` (after the
`network_domains` include of sub-task 1.1, which makes `expose_*` and
`hlf_node_domain` available):

```yaml
- name: Create per-endpoint Services for the CA (unexposed)
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.k8s_endpoint_services
  vars:
    k8s_endpoint_services_namespace: "{{ k8s_namespace }}"
    k8s_endpoint_services_component: ca
    k8s_endpoint_services_cr_names:
      - "{{ ca_name | lower | regex_replace('[^a-z0-9]', '') }}"   # S1, checked below
  when: not expose_ca | bool

- name: Create certificate authority          # existing task, add `register`
  hyperledger.fabric_ansible_collection.certificate_authority: ...
  register: endorsing_organization_ca

- name: Check the CA URLs use the HLF node domain (V5)
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.network_domains
    tasks_from: verify_urls
  vars:
    network_domains_urls:
      - "{{ endorsing_organization_ca.certificate_authority.api_url }}"
      - "{{ endorsing_organization_ca.certificate_authority.operations_url }}"

- name: Verify per-endpoint Services for the CA (unexposed)
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.k8s_endpoint_services
    tasks_from: verify
  vars:
    k8s_endpoint_services_namespace: "{{ k8s_namespace }}"
    k8s_endpoint_services_component: ca
    k8s_endpoint_services_cr_names:
      - "{{ ca_name | lower | regex_replace('[^a-z0-9]', '') }}"
    k8s_endpoint_services_urls:
      - "{{ endorsing_organization_ca.certificate_authority.api_url }}"
      - "{{ endorsing_organization_ca.certificate_authority.operations_url }}"
  when: not expose_ca | bool
```

V5 runs in **every** scenario (it holds today too, URL-MANAGEMENT-NEW.md
§8). The Service blocks run only for unexposed components.

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

`roles/ordering_organization/tasks/create.yml`: the same CA block, plus,
before *Create ordering service*:

```yaml
    k8s_endpoint_services_component: orderer
    k8s_endpoint_services_cr_names: >-
      {{ range(1, ordering_service_nodes + 1) | map('string')
         | map('regex_replace', '^', (ordering_service_name | lower
               | regex_replace('[^a-z0-9]', '')) ~ 'node')
         | list }}
```

After the module call, run V5 and the verify step with `api_url`,
`operations_url`, `grpcwp_url` and `osnadmin_url` of every element of the
registered `ordering_service` list. `osnadmin_url` is empty on Fabric < 2.4.1,
and `select` drops empty values (checked by V5 case 5, 2026-10-16).

The `delete.yml` of each organization role calls
`tasks_from: delete` with the same `cr_names`, guarded by the same `when`.

**Expected outcomes:**
- With `expose_ca/peer/orderer: false`, the namespace contains one Service per
  row of the mapping table for every node, each listening on `443` only.
- The operator's own Services are byte-for-byte unchanged.
- From an in-cluster pod,
  `curl -k https://<ns>-<peer>-operations.<hlf_node_domain>/healthz` returns
  `{"status":"OK"}` (port 9443 reached, not 7051). Reproduced on a CA,
  scenario B, 2026-10-16.
- The module health waits pass without nginx in the path, when the
  playbooks run in-cluster (sub-task 1.5). From outside the cluster they
  cannot resolve cluster-local names (finding F4).
- V5 fails when a returned URL is not under `hlf_node_domain`; the verify
  step fails when a returned URL has no matching Service, naming the actual
  CR name.
- `ansible-lint` passes on the new role and all modified task files.

**Todo list:**
- [ ] Create `roles/k8s_endpoint_services/` (`defaults/main.yml`,
  `tasks/main.yml`, `tasks/verify.yml`, `tasks/delete.yml`, `meta/main.yml`)
  with the content above. `k8s_endpoint_services_namespace` is passed by the
  caller (no `k8s_namespace` default inside the role).
- [ ] Add the create / V5 / verify blocks around the CA and peer module calls
  in `roles/endorsing_organization/tasks/create.yml`, and register the module
  outputs (`endorsing_organization_ca`, `endorsing_organization_peer`,
  `endorsing_organization_peers`).
- [ ] Add the create / V5 / verify blocks around the CA and ordering-service
  module calls in `roles/ordering_organization/tasks/create.yml`, and
  register the module outputs.
- [ ] Add the delete calls to both organization roles' `delete.yml`.
- [ ] Make the verify step's failure message print the CR name read from the
  returned URL, so an S1 mismatch is fixable at once.
- [ ] Reproduce finding F3 (display name stored differently) with a clean
  create; adjust the module call if it holds.
- [ ] Document the new role in `docs/source/roles/` (internal, but its
  defaults are user-overridable).
- [ ] Run `ansible-lint` on the new role and all modified task files.

**Relevant context:**
- Sub-task 1.3b runs whenever the component is not exposed, **including**
  when `hlf_network_domain_is_cluster_local`. Only the CoreDNS rewrites
  (1.4b) are skipped in that case.
- Organization roles: `expose_ca`, `expose_peer`, `expose_orderer` and
  `hlf_node_domain` come from the `network_domains` include (sub-task 1.1),
  not from another role's defaults.
- Adding `kubernetes.core.k8s` tasks to these roles introduces a dependency
  on a kubeconfig and the `kubernetes` Python library, which their REST-only
  path does not have today. It is pulled in **only** when a component is
  unexposed (review, "Organization roles").
- Partial exposure (e.g. `expose_peer: false`, `expose_ca: true`) works on
  the Service side. The CI per-endpoint-type rewrites of sub-task 1.4b,
  however, assume CA, peer and orderer are **all** unexposed, because the
  `-operations` suffix is shared by all three components. Mixed modes need
  exact per-FQDN rewrites and are out of scope for Step 1 CI.
- The port variables `ingress_grpc_peer_port`, `ingress_grpc_orderer_port`
  and `ingress_ca_port` from sub-task 1.1 remain Gateway-API listener ports
  for Step 2. They are **not** the native target ports above.

---

## Sub-task 1.3c — Opt-in neutralization of node Ingress objects

**Design reference:** URL-MANAGEMENT-NEW.md §5.4 (decision D4).

**Intent:** The operator creates an nginx Ingress for every CA, peer and
orderer node, with no setting to turn it off (review B2). In scenario B its
hosts are cluster-local, so they don't resolve outside the cluster, but nginx
still forwards a client that sends the right SNI. With
`neutralize_node_ingresses: true`, the organization roles set
`spec.ingress.class: <unexposed_ingress_class>` on the CR of each unexposed
node after its module call. The Ingress is kept but no longer served.

**Checked on 2026-10-16** on a CA (URL-MANAGEMENT-NEW.md §9 checks 2, 3, 7):
- nginx stops serving the Ingress (`/cainfo` through nginx: 200 → 404);
- a later update through the console keeps `spec.ingress.class`;
- the CR patch does not restart the node pod (same UID, 0 restarts); the
  Ingress class changes within ~4 s.

**Expected outcomes:**
- Default (`false`): nothing changes.
- `true`: after each node module call, the node CR has
  `spec.ingress.class: none`, the Ingress `ingressClassName: none`, and nginx
  answers 404 for every endpoint host of that node.
- Per component: only unexposed components are patched.

**Todo list:**
- [ ] In both organization roles, after each node module call (and after
  V5), patch `IBPCA` / `IBPPeer` / `IBPOrderer` (one per ordering node) with
  `spec.ingress.class: "{{ unexposed_ingress_class }}"` when
  `neutralize_node_ingresses | bool and not expose_<component> | bool`.
  The CR names come from the returned URLs (sub-task 1.3b).
- [ ] Wait until each Ingress shows `ingressClassName == unexposed_ingress_class`.
- [ ] Repeat check 3 on a **peer** update before considering a `true`
  default (D4).
- [ ] Add the neutralized case to assertion 1 of sub-task 1.6.

**Relevant context:**
- The class must be set on the **CR**, not the Ingress: the operator rebuilds
  the Ingress from the CR on every spec change.
- Exposure window: between CR creation and the patch (the module blocks until
  the node is healthy), the endpoints are reachable through nginx. Closing it
  needs an operator change, out of scope.

---

## Sub-task 1.4 — `run-tests.sh` variable injection for Step 1 flags

**Intent:** Extend the stabilized `run-tests.sh` (fixed in Step 0) to inject the newly introduced `INGRESS_TYPE` and `EXPOSE_*` variables into `tutorial/common-vars.yml`.

*(Note: Baseline fixes for positional argument crashes, `TEST_RUN_ID` stamping, and connection variable injection are implemented in [`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md) Sub-task 0.2).*

**Expected outcomes:**
- `run-tests.sh` reads `INGRESS_TYPE` (default: `nginx`) and all `EXPOSE_*` flags from the environment (defaulting to safe values).
- `ingress_type` and `expose_*` flags are patched into `common-vars.yml` via `yq` prior to playbook execution.
- It also patches `exposed_domain`, `hlf_network_domain` and `cluster_domain`
  from `EXPOSED_DOMAIN`, `HLF_NETWORK_DOMAIN` and `CLUSTER_DOMAIN`, **only
  when set**. Unset, the `network_domains` defaults apply (`console_domain`
  alias, no cluster read), so the `expose-all` leg is unchanged.
- These go to `common-vars.yml`, not `-e`: every playbook (console and
  organizations) then reads the same values (URL-MANAGEMENT-NEW.md §6.3).

**Todo list:**
- [ ] Update `.github/scripts/run-tests.sh` to include `yq` patching for `ingress_type` and the six `expose_*` boolean variables into `common-vars.yml`.
- [ ] Patch `exposed_domain`, `hlf_network_domain` and `cluster_domain` when
  their environment variables are non-empty.
- [ ] Make `deploy-console.sh` read `common-vars.yml` the same way, so the
  console gets the same `hlf_network_domain` as the organizations (it
  renders `spec.deployer.domain`, sub-task 1.3a).
- [ ] For the in-cluster Job (sub-task 1.5):
  - take `TEST_RUN_ID` from the environment when set, instead of generating
    it (Step 0 stamping), so two runs can target the same network;
  - `KEEP_NETWORK=true`: skip the final `join_network.sh destroy` and the
    cleanup trap;
  - `RUN_TESTS_MODE=destroy`: patch the vars files, then only run
    `join_network.sh destroy`;
  - skip the `.venv` activation and `_cfg/console-env.sh` sourcing when they
    don't exist (already the case for `console-env.sh`).
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

**Intent:** When `expose_*: false` and the node FQDNs are **not**
cluster-local (scenario C: `hlf_network_domain` left at `exposed_domain`, in
CI `<ip>.nip.io` or `localho.st`), the existing CoreDNS wildcard rewrites
(`rewrite name regex (.*)\.<domain> host.ingress.internal`) send every
component FQDN to the nginx ClusterIP, which silently routes traffic through
nginx when the intent is to bypass it. This sub-task adds **one rewrite rule
per endpoint type** (`ca`, `peer`, `orderer`, `operations`, `grpcweb`,
`admin`). Each rule maps
`<ns>-<cr>-<endpoint>.<hlf_network_domain>` to the per-endpoint Service
`<ns>-<cr>-<endpoint>.<ns>.svc.<cluster_domain>` created by sub-task 1.3b.
Every endpoint therefore lands on its own native port: `-operations` reaches
9443/8443, `-grpcweb` reaches 7443 and `-admin` reaches 9443, never the API
port.

The dialled hostname stays the original FQDN, so TLS SANs remain valid and no
`csr_hosts` change or re-enrollment is needed.

**Decision tree** (URL-MANAGEMENT-NEW.md §4.5, decision D1):

| CA, peer and orderer all unexposed? | `hlf_network_domain == cluster_domain`? | CoreDNS |
|---|---|---|
| no | — | no endpoint rewrite (nodes go through nginx) |
| yes | yes (scenario B) | **no rewrite**: node FQDNs are `<service>.<ns>.svc.<cluster_domain>`, real Service FQDNs. Checked 2026-10-16 on a CA (URL-MANAGEMENT-NEW.md §9 check 1). |
| yes | no (scenario C) | one rewrite per endpoint type (this sub-task) |

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
HLF network domain `127-0-0-1.nip.io` and endpoint type `operations`:

```
rewrite stop {
    name regex ^(default-[a-z0-9]+-operations)\.127-0-0-1\.nip\.io {1}.default.svc.cluster.local
    answer name ^(default-[a-z0-9]+-operations)\.default\.svc\.cluster\.local {1}.127-0-0-1.nip.io
}
```

`[a-z0-9]+` matches the operator CR name: athena removes `-` and `_` from it
(URL-MANAGEMENT-EXISTING.md §3), so it never contains a dash. That prevents
`default-org1peer-operations` from being confused with a CR whose own name
ends in an endpoint word. Scenario B needs no such pattern.

**Expected outcomes:**
- In the `expose-none` leg (scenario C), the CoreDNS ConfigMap contains six
  endpoint rewrite blocks ahead of the existing wildcards. In the
  `expose-all` and `expose-none-internal` (scenario B) legs, it is unchanged.
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
  # HLF_NETWORK_DOMAIN defaults to NIP_DOMAIN (= exposed domain) inside
  # apply_coredns_override
  ```
- [ ] Add a helper that prints the endpoint rewrite blocks:
  ```bash
  # coredns_endpoint_rewrites NAMESPACE HLF_NETWORK_DOMAIN CLUSTER_DOMAIN
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
- [ ] In `apply_coredns_override`, compute the block only for scenario C
  (all nodes unexposed, HLF network domain not cluster-local), and insert it
  right after `ready`, before the existing wildcard rewrites:
  ```bash
  HLF_NETWORK_DOMAIN=${HLF_NETWORK_DOMAIN:-${NIP_DOMAIN}}
  ENDPOINT_REWRITES=""
  if [[ "${EXPOSE_CA:-true}" == "false" \
     && "${EXPOSE_PEER:-true}" == "false" \
     && "${EXPOSE_ORDERER:-true}" == "false" \
     && "${HLF_NETWORK_DOMAIN}" != "${CLUSTER_DOMAIN}" ]]; then
    ENDPOINT_REWRITES=$(coredns_endpoint_rewrites \
      "${NAMESPACE}" "${HLF_NETWORK_DOMAIN}" "${CLUSTER_DOMAIN}")
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
- [ ] Make sure the `EXPOSE_*`, `NAMESPACE`, `HLF_NETWORK_DOMAIN` and
  `CLUSTER_DOMAIN` variables are exported **before** `kind_with_nginx.sh`
  runs in `fvtest.yml` (the matrix `env` of sub-task 1.5), because the script
  now runs before the playbooks. They must match what `run-tests.sh` writes
  to `common-vars.yml` (sub-task 1.4).
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
- Sub-task 1.6 assertions 3–6 verify this end to end. In scenario B
  (`HLF_NETWORK_DOMAIN == CLUSTER_DOMAIN`), assertion 6 checks plain
  kube-dns resolution instead of a rewrite.
- This script hard-codes `CLUSTER_DOMAIN` because it writes the Corefile
  itself. The Ansible side reads it from that same Corefile
  (`network_domains`, sub-task 1.1), so both always agree.

---

## Sub-task 1.5 — CI workflow: `expose-none` matrix leg with in-cluster Ansible runner

**Intent:** Extend `fvtest.yml` with matrix legs that validate the
unexposed scenarios on the nginx path. Their node FQDNs only resolve inside
the cluster: through CoreDNS rewrites in scenario C (sub-task 1.4b), or
because they are Service FQDNs in scenario B. The GitHub Actions runner,
**outside** the KIND cluster, cannot resolve them: its `:443` traffic would
still reach nginx through the KIND host-port mapping, which is exactly the
path these legs must not use (confirmed locally on 2026-10-16: the module
health wait fails with `nodename nor servname provided`, finding F4).
These legs therefore run the tutorial Ansible playbooks **from inside the
cluster** using a Kubernetes Job.

| Leg | Scenario | `EXPOSE_*` | `HLF_NETWORK_DOMAIN` | CoreDNS rewrites | Runner |
|---|---|---|---|---|---|
| `expose-all` | A (no regression) | `true` | unset (= exposed domain) | none | Actions runner (unchanged) |
| `expose-none` | C (previous FQDNs) | `false` | unset (= exposed domain) | 6 per endpoint type | in-cluster Job |
| `expose-none-internal` | **B (Step 1 target)** | `false` | `cluster.local` | **none** | in-cluster Job |

**Expected outcomes:**
- `fvtest.yml` runs the three legs of the table above.
- `fail-fast: false` is set so every leg always completes.
- Both unexposed legs succeed: build, join, and deploy all exit 0.
- The `expose-none-internal` leg is the first end-to-end run of scenario B
  (URL-MANAGEMENT-NEW.md §9 check 5).

**Job design.** Three decisions settle the review's in-cluster Job findings
(read-only ConfigMap, flattened tree, 1 MiB limit, no ServiceAccount):

| # | Gap | Decision |
|---|---|---|
| J1 | How the tutorial reaches the Job | **Bake it into the runner image.** `tutorial/` (436 KB, ~80 files, one binary chaincode package `fabcar@1.0.0.tgz`) is copied into a writable directory of the image. No ConfigMap: no read-only mount, no flattening, no size limit. The playbooks write their `*.json` / `*.bin` identity and config files next to themselves (`tutorial/.gitignore`), which now just works. |
| J2 | ServiceAccount and RBAC | A dedicated ServiceAccount `ansible-runner` with a namespaced Role, plus a small Role in `kube-system` for the CoreDNS ConfigMap (manifest below). |
| J3 | Variable injection inside the Job | **The Job runs `run-tests.sh`**, not the tutorial scripts directly. It thus gets the same `yq` patching as the runner leg (connection, `expose_*`, domains, sub-task 1.4) and the same build → join → deploy → destroy sequence. `API_ENDPOINT` is `console_incluster_url`. |

**Runner image** — `.github/docker/ansible-runner/Dockerfile`. It extends the
collection image the repository already builds (`Dockerfile` at the root,
published by `.github/workflows/main.yml`). That image already has Ansible,
the collection, `kubernetes.core`, `fabric-sdk-py`, `openshift`, the Fabric
`peer`, `osnadmin` and `configtxlator` binaries, and an entrypoint that works
under a random UID. Only the test-only tools and files are added:

```dockerfile
# Built in CI from the repository root:
#   docker build -t fabric-ansible-collection:ci .
#   docker build -t ansible-runner:ci -f .github/docker/ansible-runner/Dockerfile .
ARG BASE_IMAGE=fabric-ansible-collection:ci
FROM ${BASE_IMAGE}
# Test-only tools: jq, shasum (TEST_RUN_ID stamping), pip for yq.
USER root
RUN microdnf install -y jq perl-Digest-SHA python3-pip && microdnf clean -y all
USER 7051
# Python yq (run-tests.sh uses `yq -yi`, which mikefarah's yq does not support).
RUN python3.9 -m pip install --user yq
# Writable copy of the tests: run-tests.sh does `cd tutorial` relative to the repo root.
COPY --chown=7051:0 .github/scripts /workspace/.github/scripts
COPY --chown=7051:0 tutorial /workspace/tutorial
USER root
RUN chmod -R g=u /workspace
USER 7051
WORKDIR /workspace
ENTRYPOINT [ "/docker-entrypoint.sh" ]
CMD [ ".github/scripts/run-tests.sh" ]
```

- The base image is built in the **same** CI run from the checked-out commit,
  so the Job tests the collection under test, not a published release.
- **Built and tried on 2026-10-16** (local KIND, arm64): both images build;
  the runner has `yq` (Python, `-yi` works), `jq`, `shasum`, `peer` 2.5.9,
  `ansible-playbook`, `kubernetes.core` 2.4.0; `/workspace/tutorial` is
  writable, also under a random UID with group 0 (OpenShift-style). Run as a
  pod with the `ansible-runner` ServiceAccount, it read `kube-system/coredns`
  through `kubernetes.core` (in-cluster token, no kubeconfig) and got HTTP
  200 from `console_incluster_url`. The base image has no `pip`, `jq` or
  `shasum`, hence the extra packages.
- Fabric version: the base image builds `peer` v2.5.9, while the runner leg
  installs 2.4.7 (`fvtest.yml`). Both talk to the same console-deployed
  nodes; align them in Step 0 (already listed in REVIEW-MIGRATION-PLAN-STEP-0.md).
- `run-tests.sh` must work without `_cfg/console-env.sh` (it already falls
  back to environment variables) and skip the `.venv` activation when absent.

**RBAC** — `.github/k8s/ansible-runner-rbac.yml`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata: {name: ansible-runner, namespace: default}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: ansible-runner, namespace: default}
rules:
  # Per-endpoint Services (sub-task 1.3b)
  - apiGroups: [""]
    resources: [services]
    verbs: [get, list, create, patch, update, delete]
  # Node CRs: read for checks, patch for neutralize_node_ingresses (sub-task 1.3c)
  - apiGroups: [ibp.com]
    resources: [ibpcas, ibppeers, ibporderers]
    verbs: [get, list, patch]
  # Wait for the Ingress class after neutralization (sub-task 1.3c)
  - apiGroups: [networking.k8s.io]
    resources: [ingresses]
    verbs: [get, list]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: ansible-runner, namespace: default}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: ansible-runner}
subjects: [{kind: ServiceAccount, name: ansible-runner, namespace: default}]
---
# cluster_domain lookup (sub-task 1.1): read only the coredns ConfigMap
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: ansible-runner-coredns, namespace: kube-system}
rules:
  - apiGroups: [""]
    resources: [configmaps]
    resourceNames: [coredns]
    verbs: [get]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: ansible-runner-coredns, namespace: kube-system}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: ansible-runner-coredns}
subjects: [{kind: ServiceAccount, name: ansible-runner, namespace: default}]
```

**Checked on 2026-10-16** with `kubectl auth can-i --as
system:serviceaccount:default:ansible-runner`: allowed to create/delete
Services, patch `ibppeers`/`ibporderers`, read Ingresses and
`kube-system/configmaps/coredns`; denied any other `kube-system` ConfigMap,
creating `ibppeers` or Deployments, and reading Secrets. Both manifests pass
`kubectl apply --dry-run=server`.

The Job never creates CAs, peers or orderers itself: it asks the console's
REST API, and the console's deployer and the operator create them with their
own ServiceAccounts. `kubernetes.core` inside the pod authenticates with the
mounted ServiceAccount token (in-cluster config); no kubeconfig is copied in.

**Job** — `.github/k8s/ansible-runner-job.yml`:

```yaml
apiVersion: batch/v1
kind: Job
metadata: {name: ansible-runner, namespace: default}
spec:
  backoffLimit: 0                 # a failed run must fail the CI step, not retry
  activeDeadlineSeconds: 3600
  template:
    spec:
      serviceAccountName: ansible-runner
      restartPolicy: Never
      containers:
        - name: runner
          image: ansible-runner:ci
          imagePullPolicy: Never  # loaded with `kind load docker-image`
          envFrom:
            - configMapRef: {name: ansible-runner-env}   # created by the CI step below
          env:
            - name: API_SECRET
              valueFrom: {secretKeyRef: {name: ansible-runner-auth, key: API_SECRET}}
```

`ansible-runner-env` holds, from the leg's `$GITHUB_ENV`: `API_ENDPOINT`
(= `console_incluster_url`, `https://hlf-console.default.svc.<cluster_domain>:3000`),
`API_AUTHTYPE`, `API_KEY`, `K8S_NAMESPACE`, `INGRESS_TYPE`, `EXPOSE_CONSOLE`,
`EXPOSE_CA`, `EXPOSE_PEER`, `EXPOSE_ORDERER`, `EXPOSED_DOMAIN`,
`HLF_NETWORK_DOMAIN`, `CLUSTER_DOMAIN`, `WAIT_TIMEOUT`. The console serves
**HTTPS** on 3000 with a certificate for the `exposed_domain` host (checked
2026-10-16, check 4); the modules don't verify certificates, so this works.

**Teardown.** `run-tests.sh` destroys the network at the end
(`join_network.sh destroy`). The sub-task 1.6 assertions need the network
**alive**, so the first Job runs `run-tests.sh` with `KEEP_NETWORK=true`, and
a last CI step runs a second Job, `ansible-runner-destroy`, with
`RUN_TESTS_MODE=destroy` (both options added to `run-tests.sh` in sub-task
1.4). The CI step generates `TEST_RUN_ID` once and passes it to both Jobs.

**Todo list:**
- [ ] Add a `scenario` matrix dimension to the `fvtest` job in
  `.github/workflows/fvtest.yml` with values
  `[expose-all, expose-none, expose-none-internal]`. Set `fail-fast: false`
  on the matrix.
- [ ] For `expose-all`: set `EXPOSE_CONSOLE=true`, `EXPOSE_CA=true`,
  `EXPOSE_PEER=true`, `EXPOSE_ORDERER=true` in `$GITHUB_ENV`. Keep existing
  runner-side `run-tests.sh` invocation — this path is unchanged.
- [ ] For `expose-none`: set all four `EXPOSE_*` flags to `false` in
  `$GITHUB_ENV`. Keep `INGRESS_TYPE=nginx`.
- [ ] For `expose-none-internal`: same, plus
  `HLF_NETWORK_DOMAIN=cluster.local` and `CLUSTER_DOMAIN=cluster.local`,
  exported before `kind_with_nginx.sh` and the console deployment (the
  console must be **created** with `spec.deployer.domain`, finding F1).
- [ ] Create `.github/docker/ansible-runner/Dockerfile`,
  `.github/k8s/ansible-runner-rbac.yml` and `.github/k8s/ansible-runner-job.yml`
  as above.
- [ ] Add the following CI steps, each guarded by
  `if: matrix.scenario != 'expose-all'`:
  1. **Build and load the images**:
     ```bash
     docker build -t fabric-ansible-collection:ci .
     docker build -t ansible-runner:ci -f .github/docker/ansible-runner/Dockerfile .
     kind load docker-image ansible-runner:ci
     ```
  2. **Apply RBAC**: `kubectl apply -f .github/k8s/ansible-runner-rbac.yml`
  3. **Create the Job inputs**:
     ```bash
     kubectl create configmap ansible-runner-env \
       --from-literal=API_ENDPOINT="https://${CONSOLE_NAME}.${K8S_NAMESPACE}.svc.${CLUSTER_DOMAIN:-cluster.local}:3000" \
       --from-literal=API_AUTHTYPE="${API_AUTHTYPE}" --from-literal=API_KEY="${API_KEY}" \
       --from-literal=K8S_NAMESPACE="${K8S_NAMESPACE}" --from-literal=KEEP_NETWORK=true \
       --from-literal=TEST_RUN_ID="$(openssl rand -hex 20)" \
       --from-literal=INGRESS_TYPE="${INGRESS_TYPE}" \
       --from-literal=EXPOSE_CONSOLE="${EXPOSE_CONSOLE}" --from-literal=EXPOSE_CA="${EXPOSE_CA}" \
       --from-literal=EXPOSE_PEER="${EXPOSE_PEER}" --from-literal=EXPOSE_ORDERER="${EXPOSE_ORDERER}" \
       --from-literal=EXPOSED_DOMAIN="${EXPOSED_DOMAIN:-}" \
       --from-literal=HLF_NETWORK_DOMAIN="${HLF_NETWORK_DOMAIN:-}" \
       --from-literal=CLUSTER_DOMAIN="${CLUSTER_DOMAIN:-}" --from-literal=WAIT_TIMEOUT=1800
     kubectl create secret generic ansible-runner-auth --from-literal=API_SECRET="${API_SECRET}"
     ```
  4. **Run the Job**: `kubectl apply -f .github/k8s/ansible-runner-job.yml`
  5. **Wait for it** (fails fast on a failed Job):
     ```bash
     kubectl wait --for=jsonpath='{.status.conditions[?(@.status=="True")].type}'=Complete \
       --timeout=60m job/ansible-runner \
     || { kubectl get job ansible-runner -o jsonpath='{.status.conditions}'; exit 1; }
     ```
  6. **Retrieve logs** (`if: always() && matrix.scenario != 'expose-all'`):
     `kubectl logs job/ansible-runner --all-containers`
  7. **Reachability assertions** (sub-task 1.6), network still alive.
  8. **Destroy** (`if: always() && matrix.scenario != 'expose-all'`): a
     second Job, `ansible-runner-destroy`, same image and inputs plus
     `RUN_TESTS_MODE=destroy`; wait for it and print its logs like steps 5–6.
- [ ] Add `name: FV test (nginx / ${{ matrix.scenario }})` to the job.
- [ ] Run `yamllint` on the workflow and the two manifests.
- [ ] Try the Job locally first on the KIND cluster used for the
  URL-MANAGEMENT-NEW.md checks (scenario C needs no console change; scenario B
  needs the console re-created with `spec.deployer.domain`).

**Relevant context:**
- The `expose-all` leg is entirely unaffected by this sub-task — the `if:`
  conditions ensure the Job steps are skipped when `matrix.scenario == 'expose-all'`.
- A `kubectl wait --for=condition=complete` alone waits the full timeout
  when the Job fails; the `jsonpath` form above returns as soon as the Job
  has any final condition, and the `||` branch reports it.
- The Job image must be available inside the KIND cluster (`kind load
  docker-image`, `imagePullPolicy: Never`).
- Each Job starts from a fresh copy of the image, so nothing patched by the
  first Job survives into the destroy Job. Both therefore run `run-tests.sh`,
  which re-applies the same patching, with the **same** `TEST_RUN_ID` taken
  from `ansible-runner-env`: the randomised org and node names (Step 0
  stamping) are identical, and the destroy finds what the first Job
  created.
- Gateway API (`ingress_type: gateway-api`) matrix legs are **not** added in
  this step; leave a comment stub for Step 2.
- Reference full matrix design: MIGRATION-PLAN.md §5.3.4.

---

## Sub-task 1.6 — In-cluster service reachability assertions

**Intent:** Define explicit, automatable assertions for the unexposed CI
legs (`expose-none`, `expose-none-internal`) that verify in-cluster
reachability without relying on the external runner's network access. All assertions run as ephemeral pods via
`kubectl run --rm -i --restart=Never` and execute as a CI step **after** the
in-cluster Ansible Job from sub-task 1.5 completes.

**Expected outcomes:**
- Six named assertions all pass in both unexposed legs.
- The `expose-all` leg is unaffected (assertions are guarded by
  `if: matrix.scenario != 'expose-all'`).
- Any single failing assertion produces a clear, actionable error message
  identifying the misconfigured resource.

**Todo list:**

- [ ] **Assertion 1 — Unexposed Ingress objects are not served by nginx.**
  The operator **always** creates the console and node Ingress objects (B2;
  no setting turns that off), so "no Ingress object" can never hold. The
  console Ingress must have class `unexposed_ingress_class` (sub-task 1.3a);
  the node Ingress hosts must be under `hlf_node_domain`, and, with
  `neutralize_node_ingresses: true` (sub-task 1.3c), their class too:
  ```bash
  NS="${NAMESPACE:-default}"; UNSERVED="${UNEXPOSED_INGRESS_CLASS:-none}"
  cls=$(kubectl get ingress -n "$NS" "$CONSOLE_NAME" -o jsonpath='{.spec.ingressClassName}')
  [ "$cls" = "$UNSERVED" ] || { echo "console Ingress class '$cls', expected '$UNSERVED'"; exit 1; }
  code=$(curl -sk -o /dev/null -w '%{http_code}' "$CONSOLE_URL/ak/api/v3/health")
  [ "$code" = 404 ] || { echo "console still served by nginx (HTTP $code)"; exit 1; }
  ```
  _Failure indicates_: the console CR did not get `spec.ingress.class`, or
  nginx serves the class (checked 2026-10-16: it does not, check 2).

- [ ] **Assertion 2 — Console ClusterIP Service responds** at
  `console_incluster_url` (HTTPS, Basic auth):
  ```bash
  kubectl run curl-console \
    --image=curlimages/curl:8.10.1 --restart=Never --rm -i --quiet \
    --namespace "$NS" --command -- \
    curl -sfk -u "$API_KEY:$API_SECRET" \
    "https://${CONSOLE_NAME}.${NS}.svc.${CLUSTER_DOMAIN:-cluster.local}:3000/ak/api/v3/health"
  ```
  _Failure indicates_: the console pod is not running, the Service selector is
  wrong, or the credentials are wrong (401).

- [ ] **Assertions 3–6 — common preamble.** Endpoints are discovered from
  the labelled Services of sub-task 1.3b, so no node name is hardcoded:
  ```bash
  NS="${NAMESPACE:-default}"
  # hlf_node_domain: <ns>.svc.<cluster_domain> in scenario B, the HLF network domain otherwise
  if [ "${HLF_NETWORK_DOMAIN:-}" = "${CLUSTER_DOMAIN:-cluster.local}" ]; then
    DOMAIN="${NS}.svc.${CLUSTER_DOMAIN:-cluster.local}"
  else
    DOMAIN="${HLF_NETWORK_DOMAIN:-${EXPOSED_DOMAIN}}"
  fi
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
  ClusterIP** (not nginx, and not a sibling endpoint's Service). In scenario
  C this confirms the sub-task 1.4b rewrites; in scenario B the FQDN is the
  Service FQDN itself, so it confirms plain kube-dns resolution:
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
  _Failure indicates_: in scenario C, `coredns_endpoint_rewrites` was not
  emitted (check the `EXPOSE_*` / `HLF_NETWORK_DOMAIN` env passed to
  `kind_with_nginx.sh`), the `[a-z0-9]+` CR pattern does not match, or
  CoreDNS was not restarted. In scenario B, the console was not created
  with `spec.deployer.domain` (finding F1).

- [ ] Add all six assertions as a single `"Verify unexposed reachability"` step
  in `fvtest.yml`, conditioned on `if: matrix.scenario != 'expose-all'`.
- [ ] Use `set -euo pipefail` at the top of the step's `run:` block so the
  first failing assertion aborts the step. Commands whose non-zero exit is
  expected are wrapped as `rc=0; cmd || rc=$?`.

**Relevant context:**
- `CONSOLE_NAME`, `CONSOLE_URL`, `API_KEY`, `API_SECRET` come from
  `_cfg/console-env.sh` / the CI environment (`deploy-console.sh`).
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
- Documents `exposed_domain` (and the `console_domain` deprecation),
  `hlf_network_domain` (default: `exposed_domain`) and `cluster_domain`.
- Shows how to set these variables in a vars file (e.g. `common-vars.yml`) or
  via `ansible-playbook -e @vars.yml`.
- Documents the existing `kubectl get ingress` verification steps.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Decide whether to add a new page or a section in the existing
  `oss-installing.rst`; document the decision in the plan file.
- [ ] Add a "Variables reference" table listing all `expose_*`,
  `ingress_type`, domain variables, `unexposed_ingress_class` and
  `neutralize_node_ingresses` with their defaults and effects (sub-task 1.1).
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
- Demonstrates scenario B in a vars file: `expose_console: false`,
  `expose_ca: false`, `expose_peer: false`, `expose_orderer: false`,
  `exposed_domain: <public domain>`, `hlf_network_domain: cluster.local`.
- Explains that the console URL is still built from `exposed_domain`, and
  that its TLS certificate already covers it, so the console can be exposed
  later by hand (nginx Ingress or Gateway API `TLSRoute`, URL-MANAGEMENT-NEW.md
  §5.3), or by re-running the console role with `expose_console: true`.
- Explains that node FQDNs are Kubernetes Service FQDNs
  (`<ns>-<cr>-<endpoint>.<ns>.svc.cluster.local`), served by the per-endpoint
  Services, with no CoreDNS change.
- Shows `kubectl get ingress -n <namespace>`: the Ingress objects exist
  (the operator always creates them) with class `none` for the console, and
  for the nodes when `neutralize_node_ingresses: true`.
- Added to the `toctree` in `docs/source/index.rst`.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Create `docs/source/tutorials/nginx-no-expose.rst` with:
  - Prerequisites section (nginx ingress controller installed but routes not
    required for in-cluster use).
  - Example vars file for scenario B (above) and `ingress_type: nginx`.
  - Step-by-step playbook execution using `ansible-playbook -e @no-expose-vars.yml`.
  - Verification: console notice message in the playbook output; console
    URL through nginx returns 404; `console_incluster_url` answers from a
    pod.
  - Requirement: the organization playbooks must run inside the cluster
    (sub-task 1.5) because node FQDNs only resolve there.
  - Explanation of when to use this scenario (single-cluster bootstrap, GitOps
    lead-org setup, development environment).
- [ ] Add `nginx-no-expose` to the `toctree` in `docs/source/index.rst`.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Scenario A rationale: PRE-ANALYSIS.md §2.4 and §2.5.
- Console notice message implementation: sub-task 1.3 above.
- In-cluster console URL: `console_incluster_url`,
  `https://<console>.<namespace>.svc.<cluster_domain>:3000`.

---

## Acceptance criteria for Step 1

A Step 1 delivery is considered complete when all of the following pass:

1. `ansible-lint` and `yamllint` pass on all modified files.
2. `run-tests.sh` correctly injects all `ingress_type` and `expose_*` variables into `common-vars.yml` (and passes `bash -n` validation).
3. `fvtest.yml` matrix runs three legs: `nginx/expose-all`,
   `nginx/expose-none` (scenario C) and `nginx/expose-none-internal`
   (scenario B); all complete successfully with `fail-fast: false`.
4. The `nginx/expose-all` leg is byte-for-byte equivalent in test coverage to
   the pre-Step-1 single-leg run — no existing test scenario has been removed
   or weakened.
5. Both unexposed legs run the tutorial playbooks inside the KIND
   cluster via a Kubernetes Job (sub-task 1.5) and all six reachability
   assertions pass (sub-task 1.6): the console Ingress is not served by
   nginx; console health endpoint returns HTTP 200 in-cluster; one Service per
   endpoint exists with the expected `443 → targetPort` and ready backends;
   every operations FQDN answers `/healthz` on `:443`; every API, CA, grpcweb
   and admin FQDN accepts TLS on `:443`; each endpoint FQDN resolves to its
   own Service's ClusterIP.
6. In `expose-none` mode the collection creates **one ClusterIP Service per
   endpoint** (CA: `ca`, `operations`; peer: `peer`, `operations`, `grpcweb`;
   orderer: `orderer`, `admin`, `operations`, `grpcweb`), each mapping `443`
   to that endpoint's native port (sub-task 1.3b). In scenario C, **one
   CoreDNS rewrite per endpoint type** (sub-task 1.4b); in scenario B, **no
   CoreDNS change**. The operator's own Services are left unmodified, and
   console registry entries are not mutated. Every node URL returned by the
   console passes V5.
7. Domain handling (sub-tasks 1.1, 1.1b, 1.3a), all covered by the
   `network_domains` tests:
   - No new variable set: `hlf_node_domain = console_domain`, the rendered
     `IBPConsole` equals today's (minus the duplicate `networkinfo:` key),
     nothing is read from the cluster, and a `console_domain` deprecation
     notice is printed.
   - `hlf_network_domain: <cluster_domain>` with CA, peer and orderer
     unexposed: `hlf_network_domain_is_cluster_local` is true, the console
     gets `spec.deployer.domain: <namespace>.svc.<cluster_domain>`, node URLs
     are Service FQDNs, and no CoreDNS rewrite is applied.
   - The same with any of `expose_ca/peer/orderer: true` fails immediately,
     listing the flags (V3). `expose_console: true` is allowed.
   - A sub-zone of the cluster domain (e.g. `default.svc.cluster.local`) as
     `hlf_network_domain` fails, naming `<cluster_domain>` as the value to use
     (V2); an `exposed_domain` inside the cluster domain fails (V1).
   - `exposed_domain` and `console_domain` set to different values fail.
   - The cluster domain is looked up, best effort, in the
     `kube-system/coredns` ConfigMap via `k8s_info` (no `kubectl exec`),
     whenever it matters. When found, it is used if `cluster_domain` is
     empty, and a different user-set `cluster_domain` fails the play naming
     both values. When not found, a user-set `cluster_domain` is trusted with
     a warning, and an empty one fails the play asking the user to set it.
8. `docs/source` builds without warnings (`make -C docs html`).
9. No Gateway API CRD, template, task, or Kubernetes resource is introduced —
   the Gateway API path is entirely absent from the codebase at this stage.
