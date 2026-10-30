# Review of the `move-ingress` plan — Step 2

**Date:** 2026-10-12
**Scope:** [`MIGRATION-STEP-2.md`](./MIGRATION-STEP-2.md), checked against `.github/scripts/`, `.github/workflows/`, `tutorial/00-deploy-fabric-console.yml`, and the official Envoy Gateway / Gateway API compatibility matrices.
**See also:** [overview](./REVIEW-MIGRATION-PLAN.md)

---

## Blockers that are easy to fix 🔴

### B5 — The Gateway API CI cannot run as written

**Versions.** The plan confuses Envoy Gateway v1.3.0 with Gateway API v1.3.
Official Envoy Gateway matrix (excerpt):

| Envoy Gateway | Gateway API | Kubernetes | End of life |
|---|---|---|---|
| v1.3 | v1.2.1 | 1.29 – 1.32 | 2025-07-30 |
| v1.5 | v1.3.0 | 1.30 – 1.33 | 2026-02-13 |
| v1.8 | v1.5.1 | 1.32 – 1.35 | 2026-11-08 |
| **v1.9** | **v1.6.1** | **1.33 – 1.36** | 2027-02-14 |

- EG v1.3 is end-of-life, and the KIND node image (`kindest/node:v1.25.3`) is
  too old for any supported version.
- `gateway-helm` installs its own CRDs → conflicts with the
  `standard-install.yaml` applied beforehand (use `--skip-crds` or let Helm
  manage them).

**Exposure.** KIND `extraPortMappings` are not enough: the Envoy Service is of
type `LoadBalancer`, and a NodePort cannot be 443. Nothing makes Envoy listen on
port 443 of the node.

**Fix:** EG v1.9 / Gateway API v1.6 / KIND node ≥ 1.33, plus an `EnvoyProxy`
resource (hostPort / hostNetwork) or `cloud-provider-kind`.

---

## Related design blocker (owned by Step 3) 🔴

### B1 — Native ports also call Step 2's architecture into question

B1 ("native ports 7051 / 7050 / 7054 cannot work without changing the
operator") is primarily a Step 3 issue, but its impact reaches Step 2 too: the
4-listener topology and `BackendTLSPolicy`/wildcard-certificate groundwork laid
in Step 2 would need to be reworked if Step 3 adopts the "single TLS
passthrough listener + one `TLSRoute` per hostname" proposal (parity with
nginx). See the full analysis in
[`REVIEW-MIGRATION-PLAN-STEP-3.md#b1`](./REVIEW-MIGRATION-PLAN-STEP-3.md#b1---native-ports-7051--7050--7054-cannot-work).

**Consequence for Step 2:** if the Step 3 proposal is adopted, Step 2 should
plan for `TLSRoute` from the start (console included) rather than `HTTPRoute`
+ `BackendTLSPolicy`, to avoid rework.

---

## Implementation mistakes (fixable without changing the design) 🟠

- Sub-task 2.1 waits for the `tlsroutes` CRD, which is not in the v1.3 standard
  channel → hangs (goes away with B5 / B1).
- `COREDNS_HOOK` is unnecessary: the `Gateway` is created in
  `00-deploy-fabric-console.yml`, i.e. before `run-tests.sh`. Better still:
  rewrite to the FQDN of an Envoy Service with a fixed name (via `EnvoyProxy`).
- The §5.2 script calls `apply_coredns_override` at bootstrap (contradicts
  sub-task 2.1) and uses `kubectl config view --raw` instead of
  `kind get kubeconfig`.
- Listeners use `*.{{ ingress_domain }}` (`localho.st`) whereas the components
  use `console_domain` (`nip.io` in CI). → Derive `ingress_domain` from
  `console_domain`.
- The `fabric-tls-secret` Secret is never created; a `BackendTLSPolicy` is
  needed for an `HTTPRoute` to a TLS console backend (goes away with B1).

---

## Documentation inconsistencies 🟡

- "v1.3 = the version that promotes HTTPRoute to GA" is wrong: GA since v1.0
  (relevant here since Step 2 is the first `HTTPRoute` usage).

---

## Recommended order of action for this step

| Order | Action | Unblocks |
|---|---|---|
| 3 | Spike (b): Envoy Gateway on KIND with TLS passthrough on 443, console included | B1, B5 |
| 5 | Realign on EG v1.9 / Gateway API v1.6, KIND ≥ 1.33, `EnvoyProxy`, passthrough-443 topology | B1, B5 |

See the [overview](./REVIEW-MIGRATION-PLAN.md#7-recommended-order-of-action) for the full cross-step sequencing.
