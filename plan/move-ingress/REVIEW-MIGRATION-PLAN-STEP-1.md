# Review of the `move-ingress` plan — Step 1

**Date:** 2026-10-12
**Scope:** [`MIGRATION-STEP-1.md`](./MIGRATION-STEP-1.md), checked against `roles/` (`fabric_console`, `endorsing_organization`, `ordering_organization`, `fabric_operator_crds`), `tutorial/`, and [`PRE-ANALYSIS.md`](./PRE-ANALYSIS.md) §4.4.
**See also:** [overview](./REVIEW-MIGRATION-PLAN.md)
**Status updated:** 2026-10-16. Every finding below carries a **Status**
line pointing to where [`MIGRATION-STEP-1.md`](./MIGRATION-STEP-1.md) covers
it. "Planned" means the plan is fixed; the collection code is not written
yet.

---

## Design blockers 🔴

### B2 — "Nothing exposed through nginx" is impossible as specified

**Status — decided, planned:** decided on 2026-10-16 as a mix of options (a) and (b) below:
the operator's Ingress objects stay. The console Ingress is made unserved
(`spec.ingress.class: none`, MIGRATION-STEP-1.md sub-task 1.5). Node
Ingresses can be neutralized the same way, opt-in
(`neutralize_node_ingresses`, sub-task 1.7, decision D4 of
[`URL-MANAGEMENT-NEW.md`](./URL-MANAGEMENT-NEW.md)). Checked on a CA
(URL-MANAGEMENT-NEW.md §9 checks 2, 3, 7): nginx stops serving it, a console
update keeps it, no pod restart. Sub-task 1.10 assertion 1 now checks "not
served by nginx" instead of "no Ingress object". Remaining: check 3 on a
peer before a `true` default.

**Finding.** The **fabric-operator** creates the `Ingress` objects for CAs,
peers, orderers and the console (see PRE-ANALYSIS §4.4). No Step 1 sub-task
deletes or neutralises them.

**Source references** (upstream
[`hyperledger-labs/fabric-operator`](https://github.com/hyperledger-labs/fabric-operator),
`main` branch, checked 2026-10-12). For every component the same three-layer
pattern applies — a generic resource manager performs the actual
`client.Create`, a per-component "override" builds the per-FQDN
`IngressSpec`, and a per-component reconcile function wires the two together
and calls them on every reconcile loop:

| Layer | File | Line(s) |
|---|---|---|
| Generic `Ingress` manager — actual `client.Create()` call | [`pkg/manager/resources/ingress/manager.go`](https://github.com/hyperledger-labs/fabric-operator/blob/main/pkg/manager/resources/ingress/manager.go#L57-L71) | `Reconcile()` L57, `Client.Create(...)` **L71** |
| Factory wiring the override into the generic manager | [`pkg/manager/resources/manager/manager.go`](https://github.com/hyperledger-labs/fabric-operator/blob/main/pkg/manager/resources/manager/manager.go#L158) | `CreateIngressManager()` L158 |
| **Console** — FQDN(s) built | [`pkg/offering/k8s/console/override/ingress.go`](https://github.com/hyperledger-labs/fabric-operator/blob/main/pkg/offering/k8s/console/override/ingress.go#L49-L56) | `CommonIngress()` L49, `consolehost` **L56** |
| **Console** — manager created / reconciled | [`pkg/offering/k8s/console/console.go`](https://github.com/hyperledger-labs/fabric-operator/blob/main/pkg/offering/k8s/console/console.go#L81) | `CreateIngressManager(...)` L81, called from L162, `ReconcileIngressManager()` L175, `IngressManager.Reconcile(...)` L188 |
| **CA** — FQDNs built (`-ca`, `-operations`) | [`pkg/offering/k8s/ca/override/ingress.go`](https://github.com/hyperledger-labs/fabric-operator/blob/main/pkg/offering/k8s/ca/override/ingress.go#L49-L58) | `CommonIngress()` L49, `apihost` **L57**, `operationshost` **L58** |
| **CA** — manager created / reconciled | [`pkg/offering/k8s/ca/ca.go`](https://github.com/hyperledger-labs/fabric-operator/blob/main/pkg/offering/k8s/ca/ca.go#L83) | `CreateIngressManager(...)` L83, called from L194, `ReconcileIngressManager()` L202, `IngressManager.Reconcile(...)` L215/221 |
| **Peer** — FQDNs built (`-peer`, `-operations`, `-grpcweb`) | [`pkg/offering/k8s/peer/override/ingress.go`](https://github.com/hyperledger-labs/fabric-operator/blob/main/pkg/offering/k8s/peer/override/ingress.go#L49-L58) | `CommonIngress()` L49, `apihost` **L56**, `operationshost` **L57**, `grpcwebhost` **L58** |
| **Peer** — manager created / reconciled | [`pkg/offering/k8s/peer/peer.go`](https://github.com/hyperledger-labs/fabric-operator/blob/main/pkg/offering/k8s/peer/peer.go#L89) | `CreateIngressManager(...)` L89, called from L99, `ReconcileIngressManager()` L274, `IngressManager.Reconcile(...)` L287/293 |
| **Orderer** — FQDNs built (`-orderer`, `-operations`, `-grpcweb`, `-admin`) | [`pkg/offering/k8s/orderer/override/ingress.go`](https://github.com/hyperledger-labs/fabric-operator/blob/main/pkg/offering/k8s/orderer/override/ingress.go#L50-L143) | `CommonIngress()` L50, `apihost` **L58**, `operationshost` **L59**, `grpcwebhost` **L60**, `adminhost` **L143** (gated on Fabric ≥ 2.4.1/2.5.1) |
| **Orderer** — manager created / reconciled | [`pkg/offering/k8s/orderer/node.go`](https://github.com/hyperledger-labs/fabric-operator/blob/main/pkg/offering/k8s/orderer/node.go#L74) | `CreateIngressManager(...)` L74, called from L236, `ReconcileIngressManager()` L244, `IngressManager.Reconcile(...)` L257/263 |

Each `*IngressManager.Reconcile()` call is unconditional on this `main` branch
— nothing in the operator's current config lets a caller opt out of `Ingress`
creation, which is exactly why no Step 1 sub-task can "neutralise" these
objects from the Ansible side alone (confirms B2's impact below).

**Impact.** The goal "nothing is exposed through the NGINX ingress controller"
cannot be met, and assertion 1 of sub-task 1.10 ("No external Ingress objects")
will always fail.

**Decision required before coding Step 1:** see [§ Decision required](#decision-required-b2) below.

### B3 — A Service port 443 cannot serve several FQDNs

**Status — planned:** the proposal below was adopted: MIGRATION-STEP-1.md sub-task
1.6 creates one collection-owned ClusterIP Service per endpoint, and never
touches the operator's Services. The "bonus" became decision D1: with
`hlf_network_domain == cluster_domain`, node FQDNs are Service FQDNs and no
CoreDNS rewrite is needed. Checked on a CA on 2026-10-16 (URL-MANAGEMENT-NEW.md
§9 check 1, strict TLS passes). Remaining: the scenario B end-to-end run
(check 5, sub-task 1.9).

**Finding.** Each component exposes several hostnames on `:443`:

| Component | Hostnames | Native ports |
|---|---|---|
| Peer | `-peer`, `-operations`, `-grpcweb` | 7051, 9443, 7443 |
| Orderer | `-orderer`, `-admin`, `-operations`, `-grpcweb` | 7050, 9443, 8443, 7443 |
| CA | `-ca`, `-operations` | 7054, 9443 |

A Service port maps to **a single** `targetPort`. Sub-task 1.8 rewrites
`-operations` to the same Service as `-peer`: `/healthz` lands on gRPC port 7051
and fails. In addition, patching operator-owned Services may be reverted on the
next reconciliation (to be verified in `fabric-operator`).

**Impact.** The "Strategic Merge Patch" approach of sub-task 1.6 cannot work
for the operations / admin / grpcweb endpoints.

**Proposal:** the collection creates **its own ClusterIP Services**, one per
FQDN:

- named after the first label of the FQDN (`<ns>-<slug>-peer`,
  `<ns>-<slug>-operations`, …);
- selector copied from the operator's Service;
- `port: 443 → targetPort: <native port>`;
- not reconciled by the operator.

**Bonus:** with `ingress_domain: <ns>.svc.<cluster_domain>`, the FQDNs generated
by the operator become real Kubernetes Service names → **no CoreDNS rewrite
needed at all** (sub-task 1.8 and most of sub-task 1.1 go away). Constraint: a
DNS label is limited to 63 characters.

---

## Implementation mistakes (fixable without changing the design) 🟠

### Variables and facts

**Status — planned:** all three items are covered by the shared role
`network_domains` (MIGRATION-STEP-1.md sub-task 1.1): Corefile read through
`k8s_info` with cross-check, included with `include_role` by every role,
facts renamed (`hlf_network_domain_is_cluster_local`, `hlf_node_domain`). The
cluster-local item is resolved by decision D1. The prototype
(`.url_management_new_checks/network_domains/`) passes 13/13 test cases on
KIND and `ansible-lint`.

- **`cluster_domain` discovery:** `kubectl exec deployment/coredns -- awk`
  always fails (the CoreDNS image is distroless, without `awk` or a shell;
  CoreDNS pods use `dnsPolicy: Default`, so their `resolv.conf` has no cluster
  `search` line). It also requires `kubectl` and the `pods/exec` permission.
  → Read the Corefile from the `kube-system/coredns` ConfigMap via `k8s_info`,
  or keep `cluster.local` as the default with a documented override; use `""` as
  the sentinel value.
- **Variable scope:** the defaults of `fabric_operator_crds` are not visible
  from `fabric_console`, `endorsing_organization` or `ordering_organization`
  (separate playbooks). `include_tasks: set_facts.yml` called from
  `hlfsupport_console` looks for the file in its own role.
  `ingress_domain_is_cluster_local` is used in the organization roles without
  ever being defined there.
  → Defaults in each role, or a small shared role called via `include_role`.
- **Cluster-local `ingress_domain` (sub-task 1.2):** `<x>.svc.cluster.local` is
  not a Service FQDN (the form is `<svc>.<ns>.svc.<zone>`). It only works with
  the B3 proposal. Optional feature, not blocking.

### Organization roles

**Status — planned:** the guarded Kubernetes dependency and the CR names
are covered by MIGRATION-STEP-1.md sub-task 1.6: Kubernetes tasks only for
unexposed components, names stripped of non-`[a-z0-9]` and checked against
the returned URLs, `<name>node<i>` for ordering nodes. The two Step 3 items
moved to the Step 3 review. Remaining: check multi-peer names on a run.

- Adding `kubernetes.core.k8s` tasks to `endorsing_organization` /
  `ordering_organization` introduces a dependency on a kubeconfig and the
  `kubernetes` library, whereas these roles currently only talk to the console
  REST API (contradicts MIGRATION-PLAN §1.1). → Explicit guard
  (`target == 'k8s'` or opt-in).
- `ca_name | lower | replace(' ', '-')` yields `org1-ca`; the operator produces
  `org1ca`. An ordering service has N nodes, not a single Service.
- *(Moved to the [Step 3 review](./REVIEW-MIGRATION-PLAN-STEP-3.md#organization-roles)
  on 2026-10-16: undefined `peer_api_url` / `ca_api_url` / `orderer_api_url`,
  and the non-existent `certificate_authority` role. Both concern Step 3
  route tasks, not Step 1.)*

### Console

**Status — planned:** MIGRATION-STEP-1.md sub-tasks 1.4 and 1.5. Readiness
through the console Deployment when unexposed, HTTPS on port 3000 (checked),
cluster domain from `network_domains`, `/ak/api/v3/health` with credentials,
and the tutorial playbook that CI runs gets the same changes. Remaining:
align the health path in MIGRATION-STEP-0.md and MIGRATION-PREREQ-LDE.md
(`/health` returns the UI page, not API health).

- `uri http://<console>.<ns>.svc.cluster.local:3000` runs on the Ansible control
  node, which cannot resolve in-cluster names.
  → Check the Deployment readiness via `k8s_info`.
- Hardcoded `cluster.local`; the `http :3000` protocol / port needs checking;
  inconsistent health path (`/health` in Step 0, `/ak/api/v3/health` in
  sub-task 1.10).
- [`roles/fabric_console/tasks/k8s/create.yml`](../../roles/fabric_console/tasks/k8s/create.yml)
  does not wait for any Ingress: there is nothing to "split". CI does not use
  this role (`00-deploy-fabric-console.yml`), so sub-task 1.4 would not be
  tested there.

### Expose-none CI

**Status — planned:** MIGRATION-STEP-1.md sub-tasks 1.8, 1.9 and 1.10.
Assertions find endpoints from labelled Services; rewrites are written at
cluster bootstrap and keep the existing Corefile; checks go through `:443`
with `rc=0; cmd || rc=$?`. The Job takes the tutorial from the runner image,
has its own ServiceAccount and Roles, and runs `run-tests.sh`. Image and
RBAC were tried on KIND. Remaining: the full in-cluster run, blocked on the
Step 0 `run-tests.sh` fix.

- Hardcoded values (`fabricinfra`, `localho.st`, `org1peer`…) whereas CI uses
  `default`, `<ip>.nip.io`, randomised names, and Org2 is missing.
  → Generate the list from the resources actually created.
- The rewrites are applied **after** the playbook, whereas `build_network.sh`
  needs connectivity **during** its execution.
- The proposed Corefile drops the `hosts { … host.ingress.internal }` block and
  the nip.io rewrite → the console no longer resolves.
- Assertions 3 to 5 test `:7051/:7050/:7054`, while real traffic goes through
  `:443`; `exit_code=$?` is never reached under `set -e`.
- In-cluster Job: read-only ConfigMap mount (the playbooks write their JSON
  identity files), flattened directory tree, 1 MiB limit, no ServiceAccount /
  RBAC.

---

## Documentation inconsistencies 🟡

**Status — handled:** RBAC moved to MIGRATION-STEP-2.md sub-task 2.0; the
"five-task block" text is gone (sub-task 1.4 rewritten); the `apiVersion`
item was a real bug: the CRDs serve only `v1beta1`, and a `v1alpha2` read
silently finds nothing (checked on KIND). The fix is in
MIGRATION-STEP-1.md sub-task 1.5.

- RBAC (former sub-task 1.2, now MIGRATION-STEP-2.md sub-task 2.0 / W4): routes are created by Ansible tasks, not by the
  operator → extending the operator's ClusterRole is unnecessary.
- Sub-task 1.4 announces a "five-task block" but lists six tasks.
- `IBPConsole` is queried as `v1alpha2` in the roles but created as `v1beta1`
  in `00-deploy-fabric-console.yml`.

---

## Decision required (B2)

**Decided 2026-10-16:** neither option alone. The operator's Ingress
objects stay, as in (a), but the console's is always unserved when not
exposed, and the nodes' can be, as in (b), without any operator change. See
B2's status above.

On the nginx path, what does `expose_*: false` mean?

| Option | Meaning | Implication |
|---|---|---|
| **(a)** | "The collection does not depend on exposure" | The operator's Ingress objects remain. Simple and honest, but no real isolation. |
| **(b)** | "Nothing is actually exposed" | Delete or neutralise the Ingress objects → verify operator reconciliation, possibly an upstream contribution (flag in `fabric-operator`). |

Note: even with an `ingress_domain` that cannot be resolved from outside, nginx
still routes a client presenting the right SNI. Option (a) therefore offers no
security guarantee.

---

## Recommended order of action for this step

| Order | Action | Unblocks |
|---|---|---|
| 2 | ~~Decide the semantics of `expose_*: false` on nginx~~ (done 2026-10-16, see B2) | B2 |
| 3 | ~~Spike (a): `fabric-operator` reconciliation behaviour~~ (done 2026-10-16 on KIND, URL-MANAGEMENT-NEW.md §9; the Ingress-class route replaced patching Services or deleting Ingresses) | B2, B3 |
| 4 | ~~Rewrite Step 1 around collection-owned Services~~ (done, MIGRATION-STEP-1.md sub-task 1.6) | B3 |
| — | **Next:** implement Step 1; first, the Step 0 `run-tests.sh` fix (still at `run-tests.sh:42`), which blocks the in-cluster scenario B run | check 5 |

See the [overview](./REVIEW-MIGRATION-PLAN.md#7-recommended-order-of-action) for the full cross-step sequencing.
