# Step 1 — Expose Options with NGINX Ingress Controller

**Roadmap reference:** [`MIGRATION-ROADMAP.md`](./MIGRATION-ROADMAP.md) — Step 1  
**Plan reference:** [`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) — W1, W4, partial W5, partial W3, partial W7  
**Status:** `[ ] pending`

---

## Overview

This deliverable introduces all new Ansible variables (`ingress_type`, `expose_*`)
and makes the collection's console wait-logic aware of the `expose_console` flag,
while the **nginx ingress controller remains the only supported and tested ingress
backend**. No Gateway API resources, templates, or CRDs are introduced yet.

The primary goals of this step are:
1. Establish the stable variable schema that Steps 2 and 3 will build on.
2. Prove there is no regression in the current nginx-backed test suite.
3. Validate the extreme opposite scenario: a deployment where nothing is exposed
   through the NGINX ingress controller (`expose_console: false`,
   `expose_ca: false`, `expose_peer: false`, `expose_orderer: false`).

---

## Sub-task 1.1 — Variable abstraction (`fabric_operator_crds` defaults)

**Intent:** Introduce every new variable with safe defaults so all existing
playbooks continue to work without modification. This sub-task also introduces
two new variables — `ingress_domain` and `cluster_domain` — and a derived fact
`ingress_domain_is_cluster_local` that later sub-tasks (1.1b, 1.3b, 1.4b) use
to decide whether CoreDNS rewrites and `api_url` port-patching are needed.

**Expected outcomes:**
- `roles/fabric_operator_crds/defaults/main.yml` contains `ingress_type: nginx`,
  the six `expose_*` flags, the three port variables, `gateway_class_name`,
  `ingress_domain`, and `cluster_domain`.
- A new task file `roles/fabric_operator_crds/tasks/k8s/set_facts.yml` attempts
  to auto-discover the real cluster domain from a running pod; falls back to the
  user-supplied `cluster_domain` value with a warning if discovery fails; errors
  if the discovered value contradicts a user-supplied non-default value.
- `ansible-lint` and `yamllint` pass on all modified files.
- All existing tests pass without setting any new variable.

**New variables:**

`ingress_domain` — the DNS domain suffix used when constructing component
hostnames (e.g. `localho.st`, `example.com`). The operator templates component
FQDNs as `<namespace>-<slug>-<role>.<ingress_domain>`. Default: `localho.st`.

`cluster_domain` — the Kubernetes cluster search domain (e.g. `cluster.local`).
Used by sub-task 1.1b to detect cluster-local deployments and by sub-task 1.4b
as a literal value in CoreDNS rewrite target FQDNs
(`<svc>.<namespace>.svc.<cluster_domain>`). Default: `cluster.local`.

**Auto-discovery of `cluster_domain`:**

The true cluster domain is read at role entry from the `resolv.conf` of the
CoreDNS deployment. Every pod's `/etc/resolv.conf` contains a `search` line:

```
search <namespace>.svc.<domain> svc.<domain> <domain>
```

The fourth `awk` field (`$4`, where `$1` is the literal word `search`) is the
bare cluster domain. A dedicated task file performs the discovery and reconciles
it with the user-supplied default:

```yaml
# roles/fabric_operator_crds/tasks/k8s/set_facts.yml

- name: Attempt to discover cluster domain from CoreDNS pod resolv.conf
  ansible.builtin.command:
    argv:
      - kubectl
      - exec
      - -n
      - kube-system
      - deployment/coredns
      - --
      - awk
      - /^search/{print $4}
      - /etc/resolv.conf
  register: _discovered_domain
  changed_when: false
  failed_when: false   # discovery failure is handled below, not here

- name: Warn and keep user-supplied cluster_domain when discovery fails
  ansible.builtin.debug:
    msg: >-
      WARNING: could not auto-discover the cluster domain
      (kubectl exec failed: {{ _discovered_domain.stderr | default('') }}).
      Using cluster_domain='{{ cluster_domain }}' as supplied.
      If this value is wrong, set cluster_domain explicitly in your vars file.
  when: _discovered_domain.rc != 0 or (_discovered_domain.stdout | trim) == ''

- name: Fail if discovered cluster domain contradicts user-supplied value
  ansible.builtin.fail:
    msg: >-
      The cluster domain auto-discovered from the cluster
      ('{{ _discovered_domain.stdout | trim }}') does not match the
      cluster_domain variable you set ('{{ cluster_domain }}').
      Either remove cluster_domain from your vars file to accept the
      auto-discovered value, or correct it to
      '{{ _discovered_domain.stdout | trim }}'.
  when:
    - _discovered_domain.rc == 0
    - (_discovered_domain.stdout | trim) != ''
    - cluster_domain != 'cluster.local'            # user overrode the default
    - cluster_domain != (_discovered_domain.stdout | trim)

- name: Override cluster_domain with auto-discovered value
  ansible.builtin.set_fact:
    cluster_domain: "{{ _discovered_domain.stdout | trim }}"
  when:
    - _discovered_domain.rc == 0
    - (_discovered_domain.stdout | trim) != ''

- name: Set ingress_domain_is_cluster_local fact
  ansible.builtin.set_fact:
    ingress_domain_is_cluster_local: >-
      {{ ingress_domain == cluster_domain
         or ingress_domain.endswith('.svc.' + cluster_domain)
         or ingress_domain == 'svc.' + cluster_domain }}
```

**Todo list:**
- [ ] Add `ingress_type: nginx` to
  `roles/fabric_operator_crds/defaults/main.yml`.
- [ ] Add `expose_console: true`, `expose_ca: true`, `expose_peer: true`,
  `expose_orderer: true`, `expose_peer_operations: false`,
  `expose_orderer_operations: false`, `expose_grpcweb: false`.
- [ ] Add `gateway_class_name: fabric-envoy-gateway`,
  `ingress_ca_port: 7054`, `ingress_grpc_orderer_port: 7050`,
  `ingress_grpc_peer_port: 7051` (consumed in later steps; inert here).
- [ ] Add the following two new variables with inline comments:
  ```yaml
  # DNS domain suffix used to construct component hostnames.
  # Examples: localho.st (local dev), example.com (production).
  # Set to a cluster-local value (e.g. svc.cluster.local or
  # <namespace>.svc.cluster.local) when all components stay in-cluster and
  # all expose_* are false — CoreDNS rewrites are then unnecessary.
  # Mixing a cluster-local ingress_domain with any expose_*: true is an error
  # (caught at role entry by sub-task 1.1b).
  ingress_domain: localho.st

  # Kubernetes cluster search domain.  The role attempts to auto-discover this
  # at runtime from a CoreDNS pod's /etc/resolv.conf.  If discovery succeeds
  # this default is silently overridden; if it fails this value is used and a
  # warning is printed.  Override explicitly when the auto-discovery cannot run
  # (e.g. no running pods yet) or when your cluster uses a non-standard domain.
  cluster_domain: cluster.local
  ```
- [ ] Create `roles/fabric_operator_crds/tasks/k8s/set_facts.yml` with the five
  tasks shown above (discover, warn-on-failure, conflict-error, override,
  set `ingress_domain_is_cluster_local`).
- [ ] Include `set_facts.yml` at the top of
  `roles/fabric_operator_crds/tasks/k8s/create.yml` and the equivalent
  `create.yml` in `roles/hlfsupport_console`, before any task that branches on
  `expose_*` or `ingress_domain_is_cluster_local`:
  ```yaml
  - ansible.builtin.include_tasks: set_facts.yml
  ```
- [ ] Add inline comments explaining every variable's purpose and when to
  override it, as specified in MIGRATION-PLAN.md §5.1.
- [ ] Run `ansible-lint` and `yamllint` on all modified and new files.

**Relevant context:**
- The defaults file must not contain conditional logic — only `key: value`
  defaults. All conditional logic lives in `set_facts.yml`.
- `awk` field `$4` (not `$3`) is the bare cluster domain because `$1` is the
  literal word `search` and the standard three search entries are
  `<ns>.svc.<domain>`, `svc.<domain>`, `<domain>`.
- The conflict-error guard uses `cluster_domain != 'cluster.local'` to
  distinguish "user explicitly set a value" from "user left the default".
  An alternative is to use a sentinel default (e.g. `cluster_domain: ""`) so
  any non-empty user value is treated as explicit; choose whichever makes the
  Ansible logic cleaner.
- `ingress_domain_is_cluster_local` is consumed by sub-tasks 1.1b, 1.3b, and
  1.4b; `cluster_domain` is consumed as a literal string by sub-task 1.4b's
  CoreDNS rewrite target FQDNs.
- The `kubectl exec` requires a valid kubeconfig on the Ansible control node —
  already a prerequisite for all other collection tasks.

---

## Sub-task 1.1b — Cluster-local domain validation guard

**Intent:** When `ingress_domain` is a cluster-local suffix (detected by
`ingress_domain_is_cluster_local: true` from sub-task 1.1), the operator
generates component FQDNs that are already native Kubernetes Service names.
CoreDNS resolves them without any rewrite rule, and no Ingress object is needed
or meaningful. Two mutually exclusive cases must be enforced at role-entry time:

| `ingress_domain_is_cluster_local` | any `expose_*: true` | Action |
|---|---|---|
| `true` | no (all `false`) | Skip all Ingress/rewrite logic; proceed normally |
| `true` | yes (at least one) | **Fail fast** with an actionable error message |
| `false` | any | Normal path; no change |

**Expected outcomes:**
- When `ingress_domain` is cluster-local and all `expose_*` are `false`, the
  play continues without error and sub-tasks 1.3b and 1.4b are both skipped.
- When `ingress_domain` is cluster-local and any `expose_*` is `true`, the play
  fails immediately with a clear message naming which flags are in conflict.
- The guard is a no-op for all standard (non-cluster-local) `ingress_domain`
  values.

**Concrete task YAML** — add to `set_facts.yml` (or a dedicated guard block
included immediately after `set_facts.yml` in each role's `create.yml`):

```yaml
- name: Collect expose_* flags that are true (for error reporting)
  ansible.builtin.set_fact:
    _expose_flags_enabled: >-
      {{
        (['expose_console'] if expose_console | bool else [])
        + (['expose_ca']      if expose_ca      | bool else [])
        + (['expose_peer']    if expose_peer     | bool else [])
        + (['expose_orderer'] if expose_orderer  | bool else [])
      }}
  when: ingress_domain_is_cluster_local | bool

- name: Fail when cluster-local ingress_domain is combined with expose_* flags
  ansible.builtin.fail:
    msg: >-
      ingress_domain='{{ ingress_domain }}' is a cluster-local domain
      (cluster_domain='{{ cluster_domain }}'), which means no external Ingress
      will be created. The following expose_* flags are set to true, which is
      incompatible with a cluster-local ingress_domain:
        {{ _expose_flags_enabled | join(', ') }}
      Either set all expose_* flags to false, or use an external ingress_domain
      (e.g. localho.st, example.com).
  when:
    - ingress_domain_is_cluster_local | bool
    - _expose_flags_enabled | length > 0
```

**Todo list:**
- [ ] Append the two tasks above to
  `roles/fabric_operator_crds/tasks/k8s/set_facts.yml` (after the
  `ingress_domain_is_cluster_local` fact-setting task from sub-task 1.1).
- [ ] Verify the same guard applies in `roles/hlfsupport_console` — since both
  roles include `set_facts.yml`, no duplicate code is needed.
- [ ] Write a unit test (using `ansible-playbook --check` or `molecule`) that:
  - passes with `ingress_domain: svc.cluster.local` + all `expose_*: false`
  - fails with `ingress_domain: svc.cluster.local` + `expose_console: true`
  - passes with `ingress_domain: localho.st` + any `expose_*` combination
- [ ] Run `ansible-lint` on the updated `set_facts.yml`.

**Relevant context:**
- `_expose_flags_enabled` is a local helper fact used only for the error message;
  it is intentionally not reused elsewhere.
- `expose_peer_operations`, `expose_orderer_operations`, and `expose_grpcweb`
  are omitted from the check because they are sub-flags of `expose_peer` /
  `expose_orderer` — if those parent flags are `false`, the sub-flags are
  irrelevant; if the parent flags are `true`, the parent-flag check fires first.
- Sub-tasks 1.3b and 1.4b each add `when: not ingress_domain_is_cluster_local | bool`
  to their own task blocks; this sub-task only handles the hard-error case.

---

## Sub-task 1.2 — RBAC extension

**Intent:** Add `gateway.networking.k8s.io` resource permissions to both cluster
role templates. This is additive and harmless when Gateway API CRDs are not
installed; applying it now avoids a diff in Step 2.

**Expected outcomes:**
- Both cluster role templates include the `gateway.networking.k8s.io` rule block.
- Existing integration tests still pass (the new rules are never exercised on
  the nginx path).
- `yamllint` passes on both modified files.

**Todo list:**
- [ ] Add the `gateway.networking.k8s.io` rule block to
  `roles/fabric_operator_crds/templates/k8s/rbac/hlf-operator-clusterrole.yaml`
  after the existing `networking.k8s.io` block.
- [ ] Add the same rule block to
  `roles/hlfsupport_console/templates/k8s/cluster_role.yml.j2`.
- [ ] Verify the rule block covers `gateways`, `gatewayclasses`, `httproutes`,
  `tlsroutes`, and `referencegrants` with the verbs listed in
  MIGRATION-PLAN.md §5.4.
- [ ] Run `yamllint` on both modified templates.

**Relevant context:**
- Full rule block content: MIGRATION-PLAN.md §5.4
- Files: `roles/fabric_operator_crds/templates/k8s/rbac/hlf-operator-clusterrole.yaml`
  and `roles/hlfsupport_console/templates/k8s/cluster_role.yml.j2`

---

## Sub-task 1.3 — Console wait-logic for `expose_console` flag

**Intent:** Split the existing monolithic console-wait block into
`expose_console: true` and `expose_console: false` branches. When
`expose_console: false` the collection skips route/ingress discovery, polls the
in-cluster ClusterIP Service URL directly, and prints an informational notice
instead of a public URL.

**Expected outcomes:**
- `roles/hlfsupport_console/tasks/k8s/create.yml` and
  `roles/fabric_console/tasks/k8s/create.yml` handle `expose_console: false`
  correctly on the nginx path.
- When `expose_console: true` (the default) the existing behaviour is preserved.
- When `expose_console: false` the in-cluster URL
  `http://{{ console }}.{{ namespace }}.svc.cluster.local:3000` is used for the
  health-check and a notice is printed.

**Todo list:**
- [ ] In `roles/hlfsupport_console/tasks/k8s/create.yml`, locate the existing
  three tasks: "Wait for console Ingress to exist", "Set console URL", and
  "Wait for console to respond".
- [ ] Replace them with the five-task conditional block from
  MIGRATION-PLAN.md §5.5:
  - Nginx `Wait for console Ingress` guarded by
    `ingress_type == 'nginx' and expose_console | bool`.
  - Nginx `Set console URL from Ingress` with same guard.
  - `Wait for console to respond (in-cluster Service URL)` guarded by
    `not expose_console | bool`.
  - `Wait for console to respond (public URL)` guarded by
    `expose_console | bool`.
  - `Print console URL` guarded by `expose_console | bool`.
  - `Print console exposition notice` guarded by `not expose_console | bool`.
- [ ] Apply the same pattern to
  `roles/fabric_console/tasks/k8s/create.yml` (line 57 area).
- [ ] Do **not** add any Gateway API (`ingress_type == 'gateway-api'`) branches
  yet — those belong in Step 2.
- [ ] Run `ansible-lint` on both modified task files.

**Relevant context:**
- Full task YAML for all five tasks: MIGRATION-PLAN.md §5.5
- Note: the Gateway API `Wait for console HTTPRoute` tasks should be
  **omitted** from this step; add them as `when: false` stubs is unnecessary.
- In-cluster Service URL pattern: `http://{{ console }}.{{ namespace }}.svc.cluster.local:3000`

---

## Sub-task 1.3b — Post-creation `api_url` port patch for the `expose-none` scenario

**Intent:** After the operator provisions components and writes `api_url` values
into the console registry, the URLs contain port `443` (derived from the Ingress
hostname). When `expose_*: false` there is no Ingress in front of the component,
so the port `443` URL is meaningless. This sub-task overwrites `api_url` and
`operations_url` to use each component's **native port** while keeping the same
ingress-domain hostname (preserving TLS SAN validity). The same URL format is
reused in Step 3 where Gateway API TLS passthrough listeners are also bound to
these native ports.

**Cluster-local domain exception:** When `ingress_domain_is_cluster_local` is
`true` (all `expose_*` are already `false` by the guard in sub-task 1.1b), the
operator generates component FQDNs of the form
`<namespace>-<slug>-<role>.<namespace>.svc.<cluster_domain>`. These FQDNs are
already at a port-free namespace-local address — the operator writes the correct
native-port URL directly and no `PUT` patch is needed. The entire port-patch
block is therefore skipped with an outer `when: not ingress_domain_is_cluster_local | bool`.

**Expected outcomes:**
- In the `expose-none` scenario with an external `ingress_domain`, every
  registered component's `api_url` uses the native gRPC/HTTPS port instead of
  `:443`.
- The hostname portion of `api_url` is unchanged (e.g.
  `fabricinfra-org1peer-peer.localho.st`).
- The patch is a no-op when `expose_*: true` (the `when:` guard prevents execution).
- The patch is also a no-op when `ingress_domain_is_cluster_local: true`
  (no port fix needed; the operator-generated URL is already correct).
- Three new `native_*_operations_port` variables are added to
  `roles/fabric_operator_crds/defaults/main.yml`.
- `ansible-lint` passes on all modified task files.

**Native port reference:**

| Component | Native gRPC port variable      | Operations port variable              |
|-----------|-------------------------------|---------------------------------------|
| Peer      | `ingress_grpc_peer_port` (7051) | `native_peer_operations_port` (9443) |
| Orderer   | `ingress_grpc_orderer_port` (7050) | `native_orderer_operations_port` (8443) |
| CA        | `ingress_ca_port` (7054)      | `native_ca_operations_port` (9443)   |

**Todo list:**
- [ ] Add to `roles/fabric_operator_crds/defaults/main.yml` (alongside the port
  variables added in sub-task 1.1):
  ```yaml
  native_peer_operations_port: 9443
  native_orderer_operations_port: 8443
  native_ca_operations_port: 9443
  ```
- [ ] In `roles/fabric_console/tasks/k8s/create.yml`, after the block that calls
  `ordering_organization` and `endorsing_organization` roles (i.e. after component
  `api_url` values have been written to the console registry), add a conditional
  block guarded by `not expose_peer | bool` / `not expose_orderer | bool` /
  `not expose_ca | bool`. The concrete task YAML for the **peer** case is:
  ```yaml
  - name: Patch peer api_url to native port (expose-none)
    uri:
      url: "{{ api_endpoint }}/ak/api/v3/components/fabric-peer/{{ item.id }}"
      method: PUT
      headers:
        Authorization: "Bearer {{ api_key }}"
        Content-Type: "application/json"
      body_format: json
      body:
        api_url: "grpcs://{{ item.api_url | urlsplit('hostname') }}:{{ ingress_grpc_peer_port }}"
        operations_url: "https://{{ item.api_url | urlsplit('hostname') }}:{{ native_peer_operations_port }}"
      status_code: 200
    loop: "{{ registered_peers }}"
    when: not expose_peer | bool
  ```
  Apply the same pattern for orderer (`fabric-orderer`, `ingress_grpc_orderer_port`,
  `native_orderer_operations_port`, `api_url` scheme `grpcs`) and CA
  (`fabric-ca`, `ingress_ca_port`, `native_ca_operations_port`, scheme `https`
  for both `api_url` and `operations_url`).
- [ ] Apply the identical block to
  `roles/hlfsupport_console/tasks/k8s/create.yml` at the equivalent insertion
  point (after its component-registration tasks).
- [ ] Confirm that `registered_peers`, `registered_orderers`, and
  `registered_cas` are the correct loop variable names (or determine the actual
  variable names by reading the existing task files before implementing).
- [ ] Add `when: not ingress_domain_is_cluster_local | bool` as an outer guard
  on the entire port-patch block (wrapping all three component-type tasks) so
  the block is silently skipped in the cluster-local domain mode.
- [ ] Run `ansible-lint` on both modified task files.

**Relevant context:**
- Port variables are declared in sub-task 1.1: `ingress_grpc_peer_port: 7051`,
  `ingress_grpc_orderer_port: 7050`, `ingress_ca_port: 7054`.
- The `urlsplit('hostname')` Jinja2 filter extracts the hostname from the
  existing `api_url` value so the hostname is never hardcoded.
- This block is inserted in both `fabric_console` and `hlfsupport_console` role
  paths; the task structure differs between the two files — inspect each before
  implementing.
- Step 3 (Gateway API TLS passthrough) will use the same native ports; keeping
  them as variables avoids a second change at that point.
- When `ingress_domain_is_cluster_local: true` the operator writes
  `api_url: grpcs://<svc>.<namespace>.svc.<cluster_domain>:<native-port>` natively;
  no patch is needed and the `urlsplit('hostname')` logic would produce a
  cluster-internal hostname anyway.

---

## Sub-task 1.4 — `run-tests.sh` stabilisation

**Intent:** Fix the three known bugs in `.github/scripts/run-tests.sh` so the
test runner is reliable and correctly injects variables into tutorial playbooks.
These fixes are prerequisite for the CI matrix changes in sub-task 1.5.

**Expected outcomes:**
- `run-tests.sh` does not crash with `unbound variable` when called with no
  positional arguments.
- `ingress_type` and all `expose_*` flags are written into `common-vars.yml`
  before playbooks run.
- Component names are stamped with a unique run ID to prevent collision.
- Connection variables (`api_endpoint`, `api_authtype`, `api_key`, `api_secret`,
  `api_timeout`, `k8s_namespace`, `wait_timeout`) are written into the per-org
  vars files.

**Todo list:**
- [ ] Replace `.github/scripts/run-tests.sh` with the new implementation from
  MIGRATION-PLAN.md §5.3.3.
- [ ] Confirm that `INGRESS_TYPE`, `EXPOSE_CA`, `EXPOSE_PEER`, `EXPOSE_ORDERER`,
  `EXPOSE_PEER_OPERATIONS`, `EXPOSE_ORDERER_OPERATIONS`, and `EXPOSE_GRPCWEB`
  all default to safe values when not set by the environment.
- [ ] Confirm `TEST_RUN_ID` / `SHORT_TEST_RUN_ID` generation works on macOS and
  Linux (`shasum` vs `sha1sum` — the plan uses `shasum` which is available on
  both via coreutils or via macOS built-in).
- [ ] Confirm the `cleanup` trap and exit sequence matches the original script's
  intent.
- [ ] Run the script in dry-run mode (`bash -n run-tests.sh`) to check for
  syntax errors.

**Relevant context:**
- Current broken script: `.github/scripts/run-tests.sh`
- Reference implementation: MIGRATION-PLAN.md §5.3.3
- Variable injection rationale (why `common-vars.yml` instead of `-e @file`):
  MIGRATION-PLAN.md §5.3.1 and the note following §5.3.3

---

## Sub-task 1.4b — CoreDNS per-component rewrites for the `expose-none` CI leg

**Intent:** When `expose_*: false` with an external `ingress_domain` (e.g.
`localho.st`), no Ingress objects are created for CA, peer, or orderer. The
existing CoreDNS wildcard rewrite
(`rewrite name regex (.*)\.localho\.st host.ingress.internal`) still resolves
every `*.localho.st` name to the nginx ClusterIP — silently routing traffic
through nginx even when the intent is to bypass it. This sub-task adds
**per-component `rewrite name exact`** rules that map each ingress FQDN directly
to the component's Kubernetes Service FQDN, which CoreDNS's `kubernetes` plugin
resolves natively to the correct ClusterIP.

**Cluster-local domain exception:** When `INGRESS_DOMAIN` ends with the cluster
domain (i.e. it is already a `*.svc.<cluster_domain>` or `svc.<cluster_domain>`
name), the generated component FQDNs are native Kubernetes Service names that
CoreDNS already resolves correctly. **No rewrite rules are needed and
`apply_coredns_component_rewrites` must not be called.** The CI script detects
this case and skips the function entirely (see cluster-local skip guard in the
todo list).

This mechanism preserves the original ingress FQDN as the dialled hostname so
that TLS certificate SANs remain valid and no `csr_hosts` changes or
re-enrollment are needed.

**Design constraint:** The CoreDNS ConfigMap changes are applied by the CI
bootstrap script (`.github/scripts/kind_with_nginx.sh`), **not by any Ansible
role task**, consistent with MIGRATION-PLAN.md §1.1. The script runs the
`apply_coredns_component_rewrites` function **after** the Ansible playbook has
completed (so component names, the namespace, and the cluster domain are known).

**Kubernetes Service name pattern:**
The operator creates a Service per component named after the component slug
within the namespace. The naming convention is:

```
Service name:  <component-slug>          (e.g. org1peer, orderingorg-orderer, org1ca)
Namespace:     <namespace>               (e.g. fabricinfra)
Full FQDN:     <slug>.<namespace>.svc.<CLUSTER_DOMAIN>
```

The `CLUSTER_DOMAIN` value is discovered at CI script runtime (see
**Cluster domain discovery** below). The script author must substitute the
actual slug for each deployed component.

**Cluster domain discovery in the CI script:**

The CI script cannot read Ansible facts, so it discovers the cluster domain
independently using the same `/etc/resolv.conf` technique from sub-task 1.1:

```bash
# Discover the cluster domain from the CoreDNS pod's resolv.conf.
# awk field $4: $1=word "search", $2=<ns>.svc.<domain>, $3=svc.<domain>, $4=<domain>
CLUSTER_DOMAIN=$(kubectl exec -n kube-system deployment/coredns \
  -- awk '/^search/{print $4}' /etc/resolv.conf 2>/dev/null)
if [[ -z "${CLUSTER_DOMAIN}" ]]; then
  CLUSTER_DOMAIN="${CLUSTER_DOMAIN_FALLBACK:-cluster.local}"
  echo "WARNING: could not discover cluster domain; using ${CLUSTER_DOMAIN}"
fi
```

**CoreDNS rewrite rule format (per component):**
```
rewrite name exact <ingress-fqdn> <k8s-svc-fqdn>
```

Example for a peer named `Org1 Peer` in namespace `fabricinfra`, ingress domain
`localho.st`, cluster domain `cluster.local`:
```
rewrite name exact fabricinfra-org1peer-peer.localho.st org1peer.fabricinfra.svc.cluster.local
rewrite name exact fabricinfra-org1peer-operations.localho.st org1peer.fabricinfra.svc.cluster.local
```

**Expected outcomes:**
- When `INGRESS_DOMAIN` is cluster-local, `apply_coredns_component_rewrites` is
  not called; the CoreDNS ConfigMap is left unchanged.
- When `INGRESS_DOMAIN` is external, `kind_with_nginx.sh` calls
  `apply_coredns_component_rewrites` with the discovered `CLUSTER_DOMAIN`,
  generating `rewrite name exact` rules whose targets use the real cluster domain.
- After the function runs, `nslookup fabricinfra-org1peer-peer.localho.st` from
  inside the cluster resolves to the peer Service ClusterIP, **not** the nginx
  ClusterIP.
- The wildcard rewrite for the console FQDN is preserved (or replaced by a
  specific rule if `expose_console: false`).
- CoreDNS is restarted after the ConfigMap is applied.
- The function is the direct prototype for the equivalent function in
  `kind_with_envoy_gateway.sh` introduced in Step 2.

**Todo list:**
- [ ] Add the cluster domain discovery block (shown above) to
  `kind_with_nginx.sh`, executed once before the first potential call to
  `apply_coredns_component_rewrites`.
- [ ] Add the following bash function to `.github/scripts/kind_with_nginx.sh`.
  Note that the Service FQDN suffix uses `${cluster_domain}` (the second
  positional argument), not the hardcoded string `cluster.local`, and that the
  per-component exact rules are placed **before** the wildcard so they take
  precedence (CoreDNS evaluates rewrite rules top-to-bottom):
  ```bash
  # apply_coredns_component_rewrites NAMESPACE CLUSTER_DOMAIN PAIR [PAIR ...]
  # PAIR format: "<ingress-fqdn>:<k8s-service-name>"
  # Prototype for the equivalent function in kind_with_envoy_gateway.sh (Step 2).
  # Generates per-component CoreDNS "rewrite name exact" rules and applies them.
  apply_coredns_component_rewrites() {
    local namespace="$1"
    local cluster_domain="$2"
    shift 2
    local pairs=("$@")

    # Build the rewrite stanza — one exact rule per FQDN:service pair.
    # Rules are placed BEFORE the wildcard so they take precedence.
    local rewrites=""
    for pair in "${pairs[@]}"; do
      local fqdn="${pair%%:*}"
      local svc="${pair##*:}"
      rewrites+="        rewrite name exact ${fqdn} ${svc}.${namespace}.svc.${cluster_domain}\n"
    done

    kubectl apply -f - <<EOF
  apiVersion: v1
  kind: ConfigMap
  metadata:
    name: coredns
    namespace: kube-system
  data:
    Corefile: |
      .:53 {
          errors
          health {
             lameduck 5s
          }
          ready
          kubernetes ${cluster_domain} in-addr.arpa ip6.arpa {
             pods insecure
             fallthrough in-addr.arpa ip6.arpa
             ttl 30
          }
  $(printf '%b' "${rewrites}")
          rewrite name regex (.*)\.${INGRESS_DOMAIN//./\\.} host.ingress.internal
          prometheus :9153
          forward . /etc/resolv.conf {
             max_concurrent 1000
          }
          cache 30
          loop
          reload
          loadbalance
      }
  EOF

    # Restart CoreDNS to pick up the new ConfigMap
    kubectl -n kube-system rollout restart deployment/coredns
    kubectl -n kube-system rollout status deployment/coredns --timeout=60s
  }
  ```
- [ ] Wrap the call site in two nested guards — expose-none outer, cluster-local
  skip inner — so the function is only invoked for a non-cluster-local
  `expose-none` leg:
  ```bash
  if [[ "${EXPOSE_PEER:-true}" == "false" \
     && "${EXPOSE_CA:-true}" == "false" \
     && "${EXPOSE_ORDERER:-true}" == "false" ]]; then
    # Skip when ingress_domain is already cluster-local (FQDNs resolve natively)
    if [[ "${INGRESS_DOMAIN}" != *".svc.${CLUSTER_DOMAIN}" \
       && "${INGRESS_DOMAIN}" != "svc.${CLUSTER_DOMAIN}" \
       && "${INGRESS_DOMAIN}" != "${CLUSTER_DOMAIN}" ]]; then
      apply_coredns_component_rewrites "${NAMESPACE}" "${CLUSTER_DOMAIN}" \
        "fabricinfra-org1peer-peer.${INGRESS_DOMAIN}:org1peer" \
        "fabricinfra-org1peer-operations.${INGRESS_DOMAIN}:org1peer" \
        "fabricinfra-orderingorg-orderer.${INGRESS_DOMAIN}:orderingorg-orderer" \
        "fabricinfra-orderingorg-operations.${INGRESS_DOMAIN}:orderingorg-orderer" \
        "fabricinfra-org1ca-ca.${INGRESS_DOMAIN}:org1ca" \
        "fabricinfra-orderingca-ca.${INGRESS_DOMAIN}:orderingca"
    fi
  fi
  ```
  Verify the actual Service names against `kubectl get svc -n fabricinfra`
  before hardcoding them.
- [ ] Confirm the generated ConfigMap preserves the wildcard `rewrite name regex`
  line for the console when `expose_console: true`; replace it with a specific
  `rewrite name exact` rule for the console Service when `expose_console: false`.
- [ ] Run `bash -n kind_with_nginx.sh` to check for syntax errors.

**Relevant context:**
- The per-component exact rules are placed **before** the wildcard in the
  Corefile so they take precedence (CoreDNS applies rewrite rules in order).
- The `kubernetes` plugin declaration uses the discovered `${cluster_domain}`,
  making the authoritative zone match the actual cluster rather than a hardcoded
  string.
- The `kubernetes` CoreDNS plugin resolves `*.svc.<cluster_domain>` natively;
  no additional plugin configuration is needed.
- Sub-task 1.6 assertion 6 verifies this function's effect end-to-end. When
  `INGRESS_DOMAIN` is cluster-local assertion 6 is skipped (no rewrite to verify).

---

## Sub-task 1.5 — CI workflow: `expose-none` matrix leg with in-cluster Ansible runner

**Intent:** Extend `fvtest.yml` with a second matrix leg (`expose-none`) that
validates the extreme opposite scenario on the nginx path. Because the
`expose-none` leg uses native ports and per-component CoreDNS rewrites (sub-tasks
1.3b and 1.4b), the GitHub Actions runner — which is **outside** the KIND cluster
— cannot resolve ingress FQDNs to in-cluster Service IPs, nor dial native Fabric
ports through the KIND host-port mappings (which only expose `80` and `443`).
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
- **`restartPolicy: Never`** — failures surface as a failed Job rather than
  silent retries.
- **Tutorial files mount**: a `ConfigMap` (`tutorial-files`) created by a
  preceding CI step (`kubectl create configmap tutorial-files --from-file=tutorial/`)
  mounted at `/workspace/tutorial`.
- **`api_endpoint` override**: the in-cluster console Service URL
  `http://<console-svc>.<namespace>.svc.cluster.local:3000`.
- **Environment variables** injected for: `INGRESS_TYPE`, `EXPOSE_CA`,
  `EXPOSE_PEER`, `EXPOSE_ORDERER`, `EXPOSE_CONSOLE`, `WAIT_TIMEOUT`.
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
  `hyperledger.fabric_ansible_collection` layered on top.
- [ ] Add the following CI steps, each guarded by
  `if: matrix.scenario == 'expose-none'`:
  1. **Build and load runner image**: `docker build -t ansible-runner:ci
     .github/docker/ansible-runner/ && kind load docker-image ansible-runner:ci`
  2. **Create tutorial ConfigMap**:
     `kubectl create configmap tutorial-files --from-file=tutorial/`
  3. **Apply Job manifest**:
     `kubectl apply -f .github/k8s/ansible-runner-job.yml`
  4. **Wait for Job completion**:
     `kubectl wait --for=condition=complete --timeout=20m job/ansible-runner`
  5. **Retrieve logs** (unconditional, runs even on failure — use
     `if: always() && matrix.scenario == 'expose-none'`):
     `kubectl logs job/ansible-runner`
  6. **Assert Job succeeded**:
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
  count=$(kubectl get ingress -n fabricinfra -o name \
    | grep -cvE 'console' || true)
  [ "$count" -eq 0 ] \
    || (echo "Unexpected Ingress objects found for non-console components" && exit 1)
  ```
  _Failure indicates_: an `expose_*` flag was not honoured by the operator, or
  the Ansible role created Ingress objects despite `expose_*: false`.

- [ ] **Assertion 2 — Console ClusterIP Service responds** at its in-cluster URL:
  ```bash
  kubectl run curl-console \
    --image=curlimages/curl:latest --restart=Never --rm -i \
    --namespace fabricinfra \
    -- curl -sf \
    http://<console-svc>.fabricinfra.svc.cluster.local:3000/ak/api/v3/health
  ```
  _Failure indicates_: the console pod is not running, the Service selector is
  wrong, or the health endpoint path has changed.

- [ ] **Assertion 3 — Peer gRPC endpoint reachable at native port 7051**
  (TLS handshake succeeds; connection is not refused):
  ```bash
  kubectl run grpc-peer \
    --image=curlimages/curl:latest --restart=Never --rm -i \
    --namespace fabricinfra \
    -- curl -sk --connect-timeout 5 \
    https://fabricinfra-org1peer-peer.localho.st:7051
  # Pass condition: exit code 0 or 35 (TLS handshake error — not exit 7 / ECONNREFUSED)
  exit_code=$?
  [ "$exit_code" -eq 0 ] || [ "$exit_code" -eq 35 ] \
    || (echo "Peer gRPC port 7051 unreachable (exit $exit_code)" && exit 1)
  ```
  _Failure (exit 7)_ indicates: the CoreDNS exact rewrite for the peer FQDN is
  missing or incorrect, or the peer Service port mapping does not include 7051.

- [ ] **Assertion 4 — Orderer gRPC endpoint reachable at native port 7050**:
  Same pattern as Assertion 3 with the orderer FQDN and port 7050.
  ```bash
  kubectl run grpc-orderer \
    --image=curlimages/curl:latest --restart=Never --rm -i \
    --namespace fabricinfra \
    -- curl -sk --connect-timeout 5 \
    https://fabricinfra-orderingorg-orderer.localho.st:7050
  exit_code=$?
  [ "$exit_code" -eq 0 ] || [ "$exit_code" -eq 35 ] \
    || (echo "Orderer gRPC port 7050 unreachable (exit $exit_code)" && exit 1)
  ```
  _Failure (exit 7)_ indicates: CoreDNS exact rewrite for the orderer FQDN is
  missing, or the orderer Service does not expose port 7050.

- [ ] **Assertion 5 — CA HTTPS enrollment endpoint reachable at port 7054**:
  ```bash
  kubectl run ca-check \
    --image=curlimages/curl:latest --restart=Never --rm -i \
    --namespace fabricinfra \
    -- curl -sf -k \
    https://fabricinfra-orderingca-ca.localho.st:7054/cainfo
  # Pass condition: JSON response body containing "caName"
  ```
  _Failure_ indicates: the CoreDNS exact rewrite for the CA FQDN is missing,
  the CA Service does not expose port 7054, or the CA pod is not ready.

- [ ] **Assertion 6 — DNS resolution of ingress FQDNs resolves to Service
  ClusterIP, not nginx ClusterIP** (confirms sub-task 1.4b CoreDNS rewrites):
  ```bash
  nginx_ip=$(kubectl -n ingress-nginx get svc ingress-nginx-controller \
    -o jsonpath='{.spec.clusterIP}')
  resolved_ip=$(kubectl run dns-check \
    --image=busybox:latest --restart=Never --rm -i \
    -- nslookup fabricinfra-org1peer-peer.localho.st \
    | grep 'Address:' | tail -1 | awk '{print $2}')
  [ "$resolved_ip" != "$nginx_ip" ] \
    || (echo "Peer FQDN still resolves to nginx ClusterIP — CoreDNS exact rewrite not active" \
        && exit 1)
  ```
  _Failure_ indicates: `apply_coredns_component_rewrites` was not called, the
  CoreDNS ConfigMap was not applied, or CoreDNS was not restarted after the
  ConfigMap update.

- [ ] Add all six assertions as a single `"Verify expose-none reachability"` step
  in `fvtest.yml`, conditioned on `if: matrix.scenario == 'expose-none'`.
- [ ] Use `set -e` at the top of the step's `run:` block so the first failing
  assertion aborts with a non-zero exit code and the step is marked failed.

**Relevant context:**
- Replace the placeholder FQDN fragments `<console-svc>`, `<namespace>`,
  `<ingress_domain>` with the actual values from the CI environment
  (`fabricinfra`, `localho.st`, and the console Service name) before committing.
- Assertions 3–5 use `curl` for gRPC/TLS because the ephemeral pod approach does
  not require the Fabric `peer` binary; the connection-refused vs TLS-error
  distinction is sufficient to confirm reachability.
- Sub-task 1.4b must be complete before Assertions 3–6 can pass.

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
- In-cluster console URL: `http://{{ console }}.{{ namespace }}.svc.cluster.local:3000`

---

## Acceptance criteria for Step 1

A Step 1 delivery is considered complete when all of the following pass:

1. `ansible-lint` and `yamllint` pass on all modified files.
2. `run-tests.sh` executes without positional arguments and without crashing
   (`bash -n` syntax check passes; CI run exits 0).
3. `fvtest.yml` matrix runs two legs: `nginx/expose-all` and
   `nginx/expose-none`; both complete successfully with `fail-fast: false`.
4. The `nginx/expose-all` leg is byte-for-byte equivalent in test coverage to
   the pre-Step-1 single-leg run — no existing test scenario has been removed
   or weakened.
5. The `nginx/expose-none` leg runs the tutorial playbooks inside the KIND
   cluster via a Kubernetes Job (sub-task 1.5) and all six reachability
   assertions pass (sub-task 1.6): no Ingress objects for CA/peer/orderer;
   console health endpoint returns HTTP 200 in-cluster; peer (7051), orderer
   (7050), and CA (7054) native ports are reachable via ephemeral pods; ingress
   FQDNs resolve to Service ClusterIPs, not the nginx ClusterIP.
6. `api_url` values in the console registry for all `expose-none` components
   use native ports (sub-task 1.3b): `grpcs://<hostname>:7051` for peers,
   `grpcs://<hostname>:7050` for orderers, `https://<hostname>:7054` for CAs.
7. Cluster-local domain handling (sub-tasks 1.1 and 1.1b):
   - Setting `ingress_domain: <anything>.svc.<cluster_domain>` with all
     `expose_*: false` runs without error; no CoreDNS rewrites are applied and
     the `api_url` port-patch block is skipped.
   - Setting `ingress_domain: <anything>.svc.<cluster_domain>` with any
     `expose_*: true` causes the play to fail immediately with a message listing
     the conflicting flags.
   - The cluster domain is auto-discovered from a pod's `/etc/resolv.conf`; a
     fallback warning is printed (not an error) when discovery fails.
8. `docs/source` builds without warnings (`make -C docs html`).
9. No Gateway API CRD, template, task, or Kubernetes resource is introduced —
   the Gateway API path is entirely absent from the codebase at this stage.
