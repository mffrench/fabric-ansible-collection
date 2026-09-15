# Migration Roadmap: ingress-nginx → Kubernetes Gateway API

This roadmap splits the full migration described in
[`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) into three independently shippable
deliverable steps. Each step is production-safe before the next one begins: the
nginx ingress controller path is never broken, and every step either adds new
capability or extends an existing one behind a feature flag.

---

## Step 1 — Expose options with NGINX ingress controller

**Goal:** Introduce all `expose_*` boolean variables and the `ingress_type`
variable into the collection while keeping the nginx path as the only supported
ingress backend. Demonstrate no-regression across all current test scenarios and
provide explicit tutorials for the extreme opposite scenario where nothing is
exposed through the NGINX ingress controller (`expose_console: false`,
`expose_ca: false`, `expose_peer: false`, `expose_orderer: false`).

**Workstreams from MIGRATION-PLAN.md:** W1 (variable abstraction), W4 (RBAC
extension), partial W5 (console wait logic for `expose_console` flag), partial
W3 (CI test matrix stabilisation and `run-tests.sh` bug-fixes), partial W7
(documentation for new variables and no-expose tutorials).

**Key outcomes:**
- All `expose_*` and `ingress_type` defaults live in
  `roles/fabric_operator_crds/defaults/main.yml`.
- Console wait logic in `hlfsupport_console` and `fabric_console` respects
  `expose_console: false` (in-cluster URL health-check + notice message).
- Both `nginx` expose-all and `nginx` expose-none scenarios are validated by
  the CI matrix and documented in tutorials.
- `run-tests.sh` bugs (positional-arg crash, missing var injection, missing run
  IDs) are fixed so the test runner is reliable for both expose scenarios.

**See:** [`MIGRATION-STEP-1.md`](./MIGRATION-STEP-1.md)

---

## Step 2 — First Kubernetes Gateway API implementation: `expose_console=true`

**Goal:** Introduce the Kubernetes Gateway API path (`ingress_type: gateway-api`)
with support for the console `HTTPRoute` only (`expose_console: true`). All other
`expose_*` flags remain `false` for this step. The NGINX ingress controller remains
a fully supported option in parallel. The implementation is compliant with
Kubernetes Gateway API **v1.3** (the minimum version that promotes `HTTPRoute` to
GA and supports the `Programmed` condition on `Gateway`).

**Workstreams from MIGRATION-PLAN.md:** W2 (CI bootstrap script for Envoy
Gateway), partial W3 (CI matrix with `gateway-api` leg for console only), W4
(RBAC extension for gateway resources — additive and harmless on the nginx leg),
W5 (Gateway resource creation in `fabric_operator_crds`, full console wait logic),
§5.6.1 of W6 (console `HTTPRoute` template and task), partial W7 (console Gateway
API tutorial and shared gateway install tutorial).

**Key outcomes:**
- `kind_with_envoy_gateway.sh` provisions a KIND cluster with Envoy Gateway.
- `fabric_operator_crds` creates the `Gateway` resource with the `https` listener
  when `ingress_type: gateway-api`.
- `fabric_console` / `hlfsupport_console` creates an `HTTPRoute` for the console
  when `ingress_type: gateway-api` and `expose_console: true`.
- CI matrix runs both `nginx` and `gateway-api` legs; the `gateway-api` leg
  validates only the console route in this step.
- New tutorials: `gateway-api-install.rst` and `gateway-api-console.rst`.

**See:** [`MIGRATION-STEP-2.md`](./MIGRATION-STEP-2.md)

---

## Step 3 — Full Kubernetes Gateway API implementation: all `expose_*` variables

**Goal:** Complete the Gateway API path by implementing `TLSRoute` resources for
peers (`expose_peer`), orderers (`expose_orderer`), and CAs (`expose_ca`), plus
the optional operations `HTTPRoute`s (`expose_peer_operations`,
`expose_orderer_operations`) and the gRPC-Web `HTTPRoute` (`expose_grpcweb`). The
four-listener `Gateway` topology (HTTPS `:443`, CA passthrough `:7054`, orderer
passthrough `:7050`, peer passthrough `:7051`) is fully operational. The NGINX
ingress controller path remains supported and all prior tests continue to pass.

**Workstreams from MIGRATION-PLAN.md:** Remaining §5.6.2–§5.6.9 of W6 (all
route templates and post-tasks), §6 (port change impact on plugin modules and
`url_utils.py`), remaining W3 (CI matrix Scenario B with all `expose_*: true` for
the `gateway-api` leg), remaining W7 (organization tutorials and migration guide),
§5.6.10 upstream contribution.

**Key outcomes:**
- All `TLSRoute` and optional `HTTPRoute` templates and post-tasks are
  implemented in `certificate_authority`, `endorsing_organization`, and
  `ordering_organization` roles.
- `api_url` for peers resolves to `:7051`; for orderers to `:7050`; CA uses
  TLS passthrough on `:7054`.
- CI Scenario B (all services externally exposed) passes on the `gateway-api` leg
  of `fvtest.yml`.
- New tutorials: `gateway-api-endorsing-organization.rst`,
  `gateway-api-ordering-organization.rst`, and `migrate-nginx-to-gateway.rst`.
- `url_utils.py` and affected plugin modules handle the new canonical ports.

**See:** [`MIGRATION-STEP-3.md`](./MIGRATION-STEP-3.md)

---

## Deliverable dependency graph

```
Step 1 ──► Step 2 ──► Step 3
  │           │           │
  │      console      all routes
  │      HTTPRoute    TLSRoutes
  │      (GW API      + port changes
  │       v1.3+)      + full CI
  │
expose_* vars
nginx no-expose
scenario
```

## Deprecation timeline (unchanged from MIGRATION-PLAN.md §7)

| Milestone | Action |
|-----------|--------|
| **v2.1 — Step 1+2** | `ingress_type: nginx` default; `gateway-api` preview. Deprecation notice on nginx docs. |
| **v2.2 — Step 3** | `ingress_type: gateway-api` promoted to stable default. nginx still supported, produces `warn`. |
| **v2.3** | nginx path removed. `ingress_type` default changed to `gateway-api`. |
