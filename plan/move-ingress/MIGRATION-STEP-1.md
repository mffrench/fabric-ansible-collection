# Step 1 — Expose Options with NGINX Ingress Controller

**Roadmap reference:** [`MIGRATION-ROADMAP.md`](./MIGRATION-ROADMAP.md) — Step 1
**Plan reference:** [`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) — W1, W4, partial W5, partial W3, partial W7
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

**Domain.** In this plan, *the domain* is `console_domain`: the operator builds
every component hostname as `<namespace>-<cr name>-<endpoint>.<console_domain>`.
`INGRESS_DOMAIN` in the CI scripts is the same value.

---

## Sub-task 1.1 — Variable abstraction (defaults in each role that reads them)

**Intent:** Introduce the new variables with safe defaults so all existing
playbooks keep working unchanged. A role cannot see the defaults of another
role, and the roles are used from separate playbooks, so **each role declares
the variables it reads in its own `defaults/main.yml`**, with identical default
values. Nothing is discovered from the cluster: `cluster_domain` is a
documented default to override, not an auto-discovered fact.

**Expected outcomes:**
- `roles/fabric_console/defaults/main.yml` and
  `roles/hlfsupport_console/defaults/main.yml` declare `ingress_type: nginx`,
  `expose_console`, `expose_ca`, `expose_peer`, `expose_orderer` (all `true`) and
  `cluster_domain: cluster.local`.
- `roles/endorsing_organization` declares `expose_ca`, `expose_peer` and
  `namespace`; `roles/ordering_organization` declares `expose_ca`,
  `expose_orderer` and `namespace` (used by sub-task 1.3b).
- `tests/unit/test_role_defaults_consistency.py` fails when a shared variable has
  different defaults in two roles, or when a role reads a shared variable it does
  not declare.
- `ingress_domain` in `fabric_operator_crds` is read by no task or template: it
  stays declared and is marked deprecated. The component hostnames come from
  `console_domain` (see the Overview).
- All existing tests pass without setting any new variable.

**Variables** (same defaults in every role that declares them):

| Variable | Default | Meaning |
|---|---|---|
| `ingress_type` | `nginx` | Ingress implementation. Only `nginx` is accepted (1.1b). |
| `expose_console`, `expose_ca`, `expose_peer`, `expose_orderer` | `true` | Whether the component is meant to be reachable through the ingress. |
| `cluster_domain` | `cluster.local` | DNS zone served by the cluster DNS. Override it when the cluster uses another zone. |
| `namespace` | `""` | Namespace of the console and its components. Required by the organization roles only when a component is not exposed. |

**Not added in this step:** `expose_peer_operations`, `expose_orderer_operations`,
`expose_grpcweb`, `gateway_class_name`, `ingress_ca_port`,
`ingress_grpc_orderer_port` and `ingress_grpc_peer_port`. No task reads them in
Step 1; the step that reads each one (Steps 2 and 3) declares it in the roles
that use it, and extends the consistency test.

**Todo list:**
- [ ] Declare `ingress_type`, the four `expose_*` and `cluster_domain` in the
  defaults of `fabric_console` and `hlfsupport_console`.
- [ ] Declare `expose_*` and `namespace` in the defaults of
  `endorsing_organization` and `ordering_organization`.
- [ ] Mark `ingress_domain` of `fabric_operator_crds` as deprecated and unused.
- [ ] Add `tests/unit/test_role_defaults_consistency.py` and run `pytest
  tests/unit` in `.github/workflows/main.yml`.
- [ ] Document the variables in `docs/source/roles/` for the four roles.
- [ ] Run `ansible-lint` and `yamllint` on all modified and new files.

**Relevant context:**
- The defaults files contain only `key: value` pairs. The checks that use them
  live in `exposure_checks.yml` (sub-task 1.1b).
- Why `cluster_domain` is not discovered: `kubectl exec … awk` cannot work on
  the CoreDNS image (distroless, `dnsPolicy: Default`, no cluster `search` line)
  and needs `pods/exec`. Almost every cluster uses `cluster.local`, so a
  documented default is enough.
- Why the variables are repeated: separate playbooks cannot share a role's
  defaults. The unit test keeps the copies identical.

---

## Sub-task 1.1b — Domain classification and exposure checks

**Intent:** The operator builds every component hostname as
`<namespace>-<cr name>-<endpoint>.<console_domain>`. Depending on the domain,
those hostnames mean different things, and the console roles must refuse the
configurations that can never work, at role entry:

| `console_domain` | Class | Action |
|---|---|---|
| outside `cluster_domain` (`localho.st`, `example.com`, `<ip>.nip.io`) | `external` | Normal path, no change. |
| exactly `<namespace>.svc.<cluster_domain>` | `internal` | Hostnames have the shape of Service FQDNs (`<svc>.<ns>.svc.<zone>`) and resolve **only if** a Service named `<namespace>-<cr name>-<endpoint>` exists (sub-task 1.3b). Optional feature: rejected for now (see below). |
| any other domain inside `cluster_domain` (`svc.cluster.local`, `other-ns.svc.cluster.local`, `cluster.local`) | `invalid` | Fail: such hostnames match no Service name. |

**Expected outcomes:**
- `plugins/filter/fabric_domain.py` provides the filter
  `fabric_domain_kind(namespace, cluster_domain)` returning `external`,
  `internal` or `invalid` (case and trailing dot ignored), covered by unit tests.
- `roles/fabric_console/tasks/k8s/exposure_checks.yml` and
  `roles/hlfsupport_console/tasks/k8s/exposure_checks.yml` (identical files, one
  per role) run at the top of each role's `tasks/k8s/create.yml`, in this order:
  1. fail if `ingress_type` is not `nginx`;
  2. classify `console_domain`;
  3. warn if the domain looks internal (`<x>.svc.…`) but is outside
     `cluster_domain`, so it is treated as external (the cluster may use another
     zone: set `cluster_domain`);
  4. fail if the class is `invalid`;
  5. fail if the class is `internal` while some `expose_*` is `true`, naming the
     conflicting flags;
  6. fail if the class is `internal` (rule 6, see below).
- `tutorial/00-deploy-fabric-console.yml`, which creates the console inline,
  runs the same checks in a `pre_tasks` through `include_role … tasks_from`.
- The checks are a no-op for external domains.

**Why rule 6 exists.** The review marks the internal domain as optional, not
blocking: `<ns>.svc.<zone>` hostnames only resolve if the collection creates the
matching Services, and sub-task 1.3b creates them for the CA, the peers and the
ordering service nodes only. The console hostname
(`<ns>-<console>-console.<domain>`) has no such Service. Until that is settled,
an internal domain is rejected with an explicit message instead of failing later
with a DNS error.

**Todo list:**
- [ ] Add the filter, its documentation file and its unit tests.
- [ ] Add `exposure_checks.yml` to both console roles and include it from their
  `create.yml`.
- [ ] Run the checks from `tutorial/00-deploy-fabric-console.yml`.
- [ ] Run the six cases against the real role (`svc.cluster.local`,
  `<ns>.svc.cluster.local` with exposed flags, with all flags `false`, another
  zone, an external domain, `ingress_type: gateway-api`).
- [ ] Optional, after 1.3b is verified end to end: lift rule 6 for an internal
  domain with all `expose_*: false`, and decide how the console hostname
  resolves (Service for the console, or the console excluded).

**Relevant context:**
- Sub-task 1.3b creates its Services whenever a component is not exposed, with
  any class of domain. Sub-task 1.4b skips its CoreDNS rewrites for an internal
  domain (the hostnames already are Service FQDNs); that branch is not reachable
  while rule 6 is active.
- `expose_peer_operations`, `expose_orderer_operations` and `expose_grpcweb` are
  not checked: they are not declared in this step (sub-task 1.1).

---

## Sub-task 1.2 — RBAC extension (dropped from Step 1)

**Decision:** removed. The `gateway.networking.k8s.io` rules were meant for the
operator's ClusterRole, but the Gateway API routes are created by Ansible tasks
(W6), with the permissions of the kubeconfig of the user running them, not by the
operator. Extending the operator's ClusterRole is unnecessary, and it would also
break the acceptance criterion that no Gateway API resource appears before
Step 2.

**Todo list:**
- [ ] Remove W4 from the workstreams of Step 1 in `MIGRATION-ROADMAP.md`,
  `MIGRATION-PLAN.md` and `MIGRATION-STEP-2.md` (which says W4 is "already done
  in Step 1"), or move it to the step that needs it, if one does.

---

## Sub-task 1.3 — Console wait logic for the `expose_console` flag

**Intent:** When `expose_console: false`, do not wait for the console Ingress
and do not look for a public URL: the readiness of the console Deployment is the
health check, and a notice is printed instead of the URL. The wait runs through
the Kubernetes API (`k8s_info`), because a `uri` call from the Ansible control
node cannot resolve in-cluster names.

**Where the waits are today:**

| File | Waits for | What to change |
|---|---|---|
| `roles/hlfsupport_console/tasks/k8s/create.yml` | Deployment, then **Ingress** (exists, URL, `uri` 200), then prints the URL | Split the Ingress part on `expose_console`. |
| `roles/fabric_console/tasks/k8s/create.yml` | Deployment only, then prints the URL | Nothing to split: only the final print changes. |
| `tutorial/00-deploy-fabric-console.yml` (the playbook CI runs; it does not use the role) | Deployment only, then prints the URL | Same final print, otherwise this sub-task is not tested in CI. |

**Facts about the console Service** (checked on a `fabric-operator` 1.0.9
cluster): `https://<console Service>.<ns>.svc.<cluster_domain>:3000` answers on
**HTTPS** (HTTP gets no answer); `/` and `/health` return 200 without
authentication; `/ak/api/v3/health` returns 401. The health path is therefore
`/health`, over HTTPS, consistently in every step.

**Expected outcomes:**
- `expose_console: true` (default): existing behaviour, unchanged.
- `expose_console: false`: no Ingress wait, no `uri` call; the role ends once the
  Deployment is ready ("Wait for console deployment to start", already present)
  and prints a notice stating that the console is not exposed and giving its
  in-cluster URL, built from `cluster_domain` (never a literal `cluster.local`).

**Tasks to add** (`hlfsupport_console`: the four Ingress tasks get
`when: expose_console | bool`; `fabric_console` and the tutorial: the print
tasks):
1. *Wait for console ingress to exist* — `when: expose_console | bool`
2. *Set console URL from console ingress* — `when: expose_console | bool`
3. *Wait for console ingress to start* (`uri`, public URL) — `when: expose_console | bool`
4. *Print console URL* — `when: expose_console | bool`
5. *Print console exposition notice* — `when: not expose_console | bool`

No `ingress_type == 'gateway-api'` branch: that belongs to Step 2.

**Todo list:**
- [ ] Apply the five tasks above in `roles/hlfsupport_console/tasks/k8s/create.yml`.
- [ ] Apply tasks 4 and 5 in `roles/fabric_console/tasks/k8s/create.yml`.
- [ ] Apply tasks 4 and 5 in `tutorial/00-deploy-fabric-console.yml`.
- [ ] Check the `apiVersion` of `IBPConsole`: the roles read it as
  `ibp.com/v1alpha2` (`k8s_info`) but the templates create `ibp.com/v1beta1`.
  Use one version served by the CRD in both.
- [ ] Run `ansible-lint` on the modified files.

**Relevant context:**
- The in-cluster console URL is used by things running **inside** the cluster
  (the Job of 1.5, the assertion 2 of 1.6), never by the control node.

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
`<namespace>-<cr_name>-<endpoint>.<console_domain>`. The collection names
each Service after the **first DNS label** of that FQDN:

```
Service name:  <namespace>-<cr_name>-<endpoint>        e.g. default-org1peer-operations
Service FQDN:  <namespace>-<cr_name>-<endpoint>.<namespace>.svc.<cluster_domain>
```

As a result:
- CoreDNS needs **one** regex rewrite per endpoint type
  (`<ns>-*-<endpoint>.<console_domain>` → `<same label>.<ns>.svc.<cluster_domain>`),
  not one rule per node. The rules can be written before any node exists,
  which matters because each create module polls `operations_url/healthz`
  **inside** its own task (see `wait_for()` in
  `plugins/module_utils/ordering_services.py`). The Service and the rewrite
  must therefore exist before the module call returns.
- With `console_domain: <namespace>.svc.<cluster_domain>` (sub-task 1.1b), the
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

**Operator facts** (REVIEW §Recommended order, action 3). Checked on a
`fabric-operator` 1.0.9 cluster (CA `sinecoca`, peers `sinecopeer1..2`, an
ordering service of 3 nodes). They are role defaults, so a different operator
means a default change, not a redesign:

| # | Fact | Status | Default encoding |
|---|---|---|---|
| S1 | The console names the operator CR after the display name, lowercased, every non-`[a-z0-9]` character removed (`Org1 CA` → `org1ca`; `replace(' ', '-')` would give `org1-ca`, which is wrong). | Confirmed | `k8s_endpoint_services_cr_name_regex: "[^a-z0-9]"` |
| S2 | Ordering node CR names are `<ordering service CR name>node<i>`, `i` = 1..N: one set of Services **per node**, not one per ordering service. | Confirmed | `k8s_endpoint_services_orderer_node_suffix: node` |
| S3 | Operator pods carry the label `app: <CR name>`, the selector of the operator's own Services. | Confirmed | `k8s_endpoint_services_selector_key: app` |
| S4 | The FQDNs are `<namespace>-<CR name>-<endpoint>.<domain>`; the container ports are those of the mapping table (orderer operations: 8443). | Confirmed | `k8s_endpoint_services_endpoints` |
| S5 | Node TLS certificates carry every endpoint FQDN as a SAN. | Low risk (nginx is in SSL passthrough today) | — |

### Internal role `k8s_endpoint_services`

New role `roles/k8s_endpoint_services/` (documented in
`docs/source/roles/k8s_endpoint_services.rst`). The organization roles call it
with `include_role` and pass every input explicitly, so it reads no variable
of the calling role.

| Entry point | Inputs | Effect |
|---|---|---|
| `main.yml` | `k8s_endpoint_services_namespace`, `_component` (`ca`, `peer`, `orderer`), `_names` (console display names), `_orderer_nodes` | Derives the CR names (S1, S2) and creates one Service per CR name × endpoint, from `templates/service.yaml.j2`. Fails if a Service name is not a DNS label. |
| `verify.yml` | same, plus `k8s_endpoint_services_urls` | Fails if the first label of a URL reported by the console is not one of the Service names. |
| `delete.yml` | same as `main.yml` | Deletes the Services by name. |

Design notes:
- The CR names are derived **inside** the role (`tasks/names.yml`), from the
  display names the organization roles already use. The S1/S2 rule therefore
  lives in one place instead of being repeated in each organization role.
- The Service is rendered from a YAML template: with an inline `definition`,
  `targetPort: "{{ ... | int }}"` reaches the API as the string `"7054"`, a
  named port, and the API rejects it.

### Calls from the organization roles

Guard (REVIEW, Organization roles): the call runs **only** when
`expose_ca`, `expose_peer` or `expose_orderer` is `false`. With the defaults
(`true`), the organization roles keep talking only to the console REST API
and need neither `kubernetes.core` nor a kubeconfig. Each organization role
declares the variables it reads in its own defaults (`expose_ca`,
`expose_peer` or `expose_orderer`, `namespace`, empty by default and then
required), as the console roles do.

| Role | Before the module call | Module output registered | After the module call |
|---|---|---|---|
| `endorsing_organization` | Services of the CA (`[ca_name]`) | `endorsing_organization_ca` | `verify` with `api_url`, `operations_url` |
| `endorsing_organization` | Services of the peers (`[peer_name]`, or `peer_name` + 1..`peers`) | `endorsing_organization_peer` (one peer), `endorsing_organization_peers` (loop) | `verify` with `api_url`, `operations_url`, `grpcwp_url` of each peer |
| `ordering_organization` | Services of the CA | `ordering_organization_ca` | as above |
| `ordering_organization` | Services of the nodes (`[ordering_service_name]`, `ordering_service_nodes`) | `ordering_organization_ordering_service` (one element per node) | `verify` with `api_url`, `operations_url`, `grpcwp_url`, `osnadmin_url` of each node (`osnadmin_url` is empty before Fabric 2.4.1 and ignored) |

The `delete.yml` of each organization role calls `tasks_from: delete` with the
same inputs and the same guard.

There is no `certificate_authority` role: the CA is created by the
`certificate_authority` **module**, called from both organization roles. CA
tasks (here, and the routes of W6) go next to that call in each role.

**Expected outcomes:**
- With `expose_ca/peer/orderer: false`, the namespace contains one Service per
  row of the mapping table for every node, each listening on `443` only.
- The operator's own Services are byte-for-byte unchanged.
- `curl -k https://<ns>-<peer>-operations.<console_domain>/healthz` from an
  in-cluster pod returns `{"status":"OK"}` (port 9443 reached, not 7051).
- The module health waits pass without nginx in the path.
- The verify step fails loudly (naming the CR name defaults) when the console
  advertises an endpoint without a matching Service.
- `ansible-lint` passes on the new role and all modified task files.

**Todo list:**
- [ ] Create `roles/k8s_endpoint_services/` (`defaults/main.yml`,
  `tasks/main.yml`, `tasks/names.yml`, `tasks/verify.yml`, `tasks/delete.yml`,
  `templates/service.yaml.j2`, `meta/main.yml`).
- [ ] Add the create / verify blocks around the CA and peer module calls in
  `roles/endorsing_organization/tasks/create.yml`, and register the module
  outputs (`endorsing_organization_ca`, `endorsing_organization_peer`,
  `endorsing_organization_peers`).
- [ ] Add the create / verify blocks around the CA and ordering-service
  module calls in `roles/ordering_organization/tasks/create.yml`, and
  register the module outputs.
- [ ] Add the delete calls to both organization roles' `delete.yml`.
- [ ] Declare `expose_*` and `namespace` in the defaults of both organization
  roles; extend `tests/unit/test_role_defaults_consistency.py`.
- [ ] Re-run the operator spike if the operator version changes (S1–S4 were
  confirmed on `fabric-operator` 1.0.9, see above).
- [ ] Document the new role in `docs/source/roles/` and the new parameters of
  both organization roles.
- [ ] Run `ansible-lint` on the new role and all modified task files.
- [ ] End-to-end run of the organization roles with `expose_*: false` from
  inside the cluster (sub-task 1.5). From a workstation, the CA enrollment
  tasks need the CA reachable through the ingress.

**Relevant context:**
- Sub-task 1.3b runs whenever the component is not exposed, **including**
  with an internal `console_domain` (rejected for now by 1.1b). Only the
  CoreDNS rewrites (1.4b) are skipped in that case.
- Partial exposure (e.g. `expose_peer: false`, `expose_ca: true`) works on
  the Service side. The CI per-endpoint-type rewrites of sub-task 1.4b,
  however, assume CA, peer and orderer are **all** unexposed, because the
  `-operations` suffix is shared by all three components. Mixed modes need
  exact per-FQDN rewrites and are out of scope for Step 1 CI.
- The Gateway-API listener ports (`ingress_grpc_peer_port`, …) are declared by
  Step 2, not Step 1. They are **not** the native target ports above.

---

## Sub-task 1.4 — `run-tests.sh` variable injection for Step 1 flags

**Intent:** Extend the stabilized `run-tests.sh` (fixed in Step 0) to inject the
Step 1 variables into `tutorial/common-vars.yml`, and make the organization
playbooks pass the namespace the new roles need.

*(Note: Baseline fixes for positional argument crashes, `TEST_RUN_ID` stamping, and connection variable injection are implemented in [`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md) Sub-task 0.2).*

**Expected outcomes:**
- `run-tests.sh` reads `INGRESS_TYPE` (default `nginx`) and `EXPOSE_CONSOLE`,
  `EXPOSE_CA`, `EXPOSE_PEER`, `EXPOSE_ORDERER` (default `true`) from the
  environment and patches `ingress_type` and the four `expose_*` into
  `common-vars.yml` with `yq`, before any playbook runs. Only variables the
  roles read are injected (sub-task 1.1).
- The playbooks that call the organization roles receive `namespace`.

**Todo list:**
- [ ] Update `.github/scripts/run-tests.sh` with the `yq` patching above.
- [ ] Add `namespace: "{{ k8s_namespace | default('default') }}"` to the plays of
  `tutorial/01-…`, `02-…`, `12-…` (create) and `97-…`, `98-…`, `99-…` (delete),
  which call `endorsing_organization` / `ordering_organization` and do not pass a
  namespace today. Without it, an unexposed component fails with "namespace not
  specified".
- [ ] Verify `bash -n .github/scripts/run-tests.sh` passes syntax validation.

**Relevant context:**
- Baseline script: `.github/scripts/run-tests.sh` (as delivered in Step 0)
- Reference implementation: MIGRATION-PLAN.md §5.3.3
- Variable injection rationale (why `common-vars.yml` instead of `-e @file`):
  MIGRATION-PLAN.md §5.3.1 and the note following §5.3.3

---

## Sub-task 1.4b — CoreDNS per-endpoint-type rewrites for the `expose-none` CI leg

**Intent:** When `expose_*: false` with an external `console_domain` (CI:
`<ip>.nip.io` or `localho.st`), the existing CoreDNS wildcard rewrites
(`rewrite name regex (.*)\.<domain> host.ingress.internal`) send every
component FQDN to the nginx ClusterIP, which silently routes traffic through
nginx when the intent is to bypass it. This sub-task adds **one rewrite rule
per endpoint type** (`ca`, `peer`, `orderer`, `operations`, `grpcweb`,
`admin`). Each rule maps
`<ns>-<cr>-<endpoint>.<console_domain>` to the per-endpoint Service
`<ns>-<cr>-<endpoint>.<ns>.svc.<cluster_domain>` created by sub-task 1.3b.
Every endpoint therefore lands on its own native port: `-operations` reaches
9443/8443, `-grpcweb` reaches 7443 and `-admin` reaches 9443, never the API
port.

The dialled hostname stays the original FQDN, so TLS SANs remain valid and no
`csr_hosts` change or re-enrollment is needed.

**Cluster-local domain exception:** when the domain is
`<namespace>.svc.<cluster_domain>`, the FQDNs are already the per-endpoint
Service FQDNs. No rewrite is applied. (Sub-task 1.1b rejects internal domains
for now, so this branch is dormant until that rule is lifted.)

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

**Job specification** (`.github/k8s/ansible-runner-job.yml`):
- **Image** (`.github/docker/ansible-runner/Dockerfile`): based on
  `hyperledger/fabric-tools:<version>`, with Python 3, Ansible, the collection
  installed from the tarball built in the same CI run, the `peer` binary and
  `configtxlator`. The **`tutorial/` directory is copied into the image**
  (`/workspace/tutorial`), and the image is rebuilt on every run. This replaces
  a ConfigMap mount, which would be read-only (the playbooks write their JSON
  identity files), flattened (`--from-file` does not recurse) and limited to
  1 MiB.
- **Permissions:** a `ServiceAccount` (`ansible-runner`) with a `Role` and a
  `RoleBinding` in the network namespace, referenced by `serviceAccountName`.
  The role needs `get`, `list`, `create`, `update`, `patch` and `delete` on
  `services` (created and deleted by `k8s_endpoint_services`), and `get` / `list`
  on `deployments` for the console readiness. `kubernetes.core` uses the in-cluster
  configuration, so no kubeconfig is mounted. Start from this minimal set and
  widen it only on a `Forbidden` error.
- **Console endpoint:** `https://<console-svc>.<namespace>.svc.<cluster_domain>:3000`
  (HTTPS, see sub-task 1.3). The Job script patches `api_endpoint` in
  `common-vars.yml` with `yq`, as `run-tests.sh` does.
- **Environment variables:** `INGRESS_TYPE`, `EXPOSE_CONSOLE`, `EXPOSE_CA`,
  `EXPOSE_PEER`, `EXPOSE_ORDERER`, `WAIT_TIMEOUT`, `K8S_NAMESPACE`.
- **`restartPolicy: Never`** and `backoffLimit: 0`: a failure surfaces as a
  failed Job, not as silent retries.
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
- [ ] Create `.github/docker/ansible-runner/Dockerfile` as described above.
- [ ] Create `.github/k8s/ansible-runner-job.yml` with the `ServiceAccount`,
  `Role`, `RoleBinding` and `Job`.
- [ ] Add the following CI steps, each guarded by
  `if: matrix.scenario == 'expose-none'`:
  1. **Build and load runner image**: build the collection tarball, then
     `docker build -t ansible-runner:ci` with the repository as context, and
     `kind load docker-image ansible-runner:ci`
  2. **Apply the manifests**:
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
- [ ] Commit the manifest and the Dockerfile as part of this sub-task.

**Relevant context:**
- The `expose-all` leg is entirely unaffected by this sub-task — the `if:`
  conditions ensure the Job steps are skipped when `matrix.scenario == 'expose-all'`.
- The Job image must be available inside the KIND cluster (`kind load
  docker-image`).
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
  (runner-side, no ephemeral pod needed). **Depends on the decision B2:** with
  option (a) the operator's Ingress objects still exist and this assertion is
  dropped; with option (b) (an operator flag) it must pass. When it applies:
  ```bash
  NS="${K8S_NAMESPACE:-default}"
  count=$(kubectl get ingress -n "$NS" -o name | grep -cvE 'console' || true)
  [ "$count" -eq 0 ] \
    || { echo "Unexpected Ingress objects found for non-console components"; exit 1; }
  ```
  _Failure indicates_: an `expose_*` flag was not honoured by the operator.

- [ ] **Assertion 2 — Console ClusterIP Service responds** at its in-cluster URL,
  over HTTPS, on the unauthenticated `/health` path (`/ak/api/v3/health` answers
  401). The console Service is named after the console (`hlf-console` by default):
  ```bash
  NS="${K8S_NAMESPACE:-default}"
  CONSOLE="${CONSOLE_NAME:-hlf-console}"
  kubectl run curl-console --image=curlimages/curl:8.10.1 \
    --restart=Never --rm -i --namespace "$NS" -- \
    curl -skf "https://${CONSOLE}.${NS}.svc.${CLUSTER_DOMAIN:-cluster.local}:3000/health"
  ```
  _Failure indicates_: the console pod is not running, the Service selector is
  wrong, or the protocol or path changed.

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
  come from the CI environment. Assertions 3–6 take the list of endpoints from
  the Services the collection created (labels), so every organization (Org1,
  Org2, …) and every node is covered, whatever the randomised names.
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
- In-cluster console URL: `http://{{ console }}.{{ namespace }}.svc.cluster.local:3000`

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
   assertions pass (sub-task 1.6): no Ingress objects for CA/peer/orderer (only
   if B2 option (b) is chosen);
   console `/health` returns HTTP 200 in-cluster over HTTPS; one Service per
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
7. Domain handling (sub-tasks 1.1 and 1.1b), checked at role entry, for an
   external domain nothing changes:
   - `ingress_type` other than `nginx` fails.
   - `console_domain: <namespace>.svc.<cluster_domain>` with any `expose_*: true`
     fails immediately, listing the conflicting flags.
   - `console_domain: <namespace>.svc.<cluster_domain>` with all `expose_*: false`
     fails with a message stating that the internal domain is not supported yet
     (optional feature, B3).
   - Any other domain inside `cluster_domain` (e.g. `svc.cluster.local`) fails
     immediately, naming the only supported form.
   - `cluster_domain` is never discovered from the cluster: it defaults to
     `cluster.local` and is overridden by the user.
   - Every role declares the variables it reads in its own defaults, and the
     unit test checking them passes.
8. `docs/source` builds without warnings (`make -C docs html`).
9. No Gateway API CRD, template, task, or Kubernetes resource is introduced —
   the Gateway API path is entirely absent from the codebase at this stage.
