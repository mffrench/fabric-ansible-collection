# Review of the `move-ingress` plan — Step 3

**Date:** 2026-10-12
**Scope:** [`MIGRATION-STEP-3.md`](./MIGRATION-STEP-3.md), checked against [`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) §2.1, `plugins/module_utils/url_utils.py`, and [`MIGRATION-ROADMAP.md`](./MIGRATION-ROADMAP.md).
**See also:** [overview](./REVIEW-MIGRATION-PLAN.md)

---

## Design blockers 🔴

### B1 — Native ports 7051 / 7050 / 7054 cannot work

**Finding.** The operator itself generates `api_url`, the gossip external
endpoint and the connection profiles with `:443` (which is precisely why Step 1
was reworked). The collection has no way to switch them to 7051 / 7050 / 7054
without changing the operator. Clients will therefore dial `:443` → the `https`
listener **terminates** TLS → Fabric mTLS is broken.

Sub-task 3.8 (changing `url_utils.py`) does not solve this and is based on a
misreading of the code:
[`translate_url_to_os_format`](../../plugins/module_utils/url_utils.py) is only
used by the `*_metadata` modules, and when the port is not 443 it **renames the
hostname** (`-<type>` suffix). Passing `7051` would produce wrong URLs. The
modules are also unaware of `ingress_type`.

**Impact.** Calls into question the architecture of Steps 2 and 3 (4-listener
topology, hostPorts, wildcard certificate, sub-task 3.8, port-change tutorials)
— see also [`REVIEW-MIGRATION-PLAN-STEP-2.md`](./REVIEW-MIGRATION-PLAN-STEP-2.md#related-design-blocker-owned-by-step-3) for the Step 2 consequences.

**Proposal — parity with nginx:**

- **A single `TLS` listener in `Passthrough` mode on 443** (`*.<domain>`).
- **One `TLSRoute` per hostname**: console, peer, operations, grpcweb, ca,
  orderer, admin — exactly what nginx ssl-passthrough does today.

| Removed | Cost |
|---|---|
| Port changes and sub-task 3.8 | `TLSRoute` required from Step 2 |
| 3 extra listeners + hostPorts | → Gateway API ≥ 1.5 (fine with EG v1.9) |
| Wildcard certificate + `fabric-tls-secret` Secret | |
| `BackendTLSPolicy` for the console | |
| Port-change tutorials | |

The "one port per protocol class" topology can remain a later option, once
natively supported by `fabric-operator` (sub-task 3.15).

---

## Implementation mistakes (fixable without changing the design) 🟠

### Organization roles

*Moved from the [Step 1 review](./REVIEW-MIGRATION-PLAN-STEP-1.md#organization-roles)
on 2026-10-16: both findings concern the Step 3 route tasks, not Step 1.*

- **`peer_api_url`, `ca_api_url`, `orderer_api_url` are never defined.**
  `MIGRATION-STEP-3.md` (sub-tasks 3.2–3.4, tutorials) and
  `MIGRATION-PLAN.md` §5.6 derive the route hostnames from them
  (`… | urlsplit('hostname')`), but no role or module sets them.
  → Derive them from the registered module results. Step 1 adds those
  registers (`MIGRATION-STEP-1.md` sub-task 1.3b):
  `endorsing_organization_ca.certificate_authority.api_url`, the
  `endorsing_organization_peer` / `endorsing_organization_peers` results, and
  the ordering-service result, which is a **list** (one entry per node: one
  route per node, not one per ordering service).
- **The `certificate_authority` role does not exist** (sub-task 3.2,
  `MIGRATION-PLAN.md` §5.6.9): the CA is created inside
  `endorsing_organization` and `ordering_organization`.
  → Put the CA route tasks in both organization roles, after the CA module
  call.

---

## Documentation inconsistencies 🟡

- Gateway API versions: the roadmap states **1.6** minimum from Step 3, but
  `MIGRATION-STEP-3.md` says "v1.5+" everywhere (title, sub-tasks 3.1 and 3.11,
  criterion 7).
- "No manifest changes" is wrong for `TLSRoute`: `apiVersion`
  `v1alpha2`/`v1alpha3` → `v1`.
- `MIGRATION-PLAN.md` §2.1: CA operations port is 9443 (not 7054); orderer:
  operations 8443, admin 9443.

---

## Recommended order of action for this step

| Order | Action | Unblocks |
|---|---|---|
| 3 | Spike (b): Envoy Gateway on KIND with TLS passthrough on 443, console included (see [Step 2](./REVIEW-MIGRATION-PLAN-STEP-2.md)) | B1, B5 |
| 5 | Realign on EG v1.9 / Gateway API v1.6, KIND ≥ 1.33, `EnvoyProxy`, passthrough-443 topology | B1, B5 |

See the [overview](./REVIEW-MIGRATION-PLAN.md#7-recommended-order-of-action) for the full cross-step sequencing.
