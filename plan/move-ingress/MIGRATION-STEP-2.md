# Step 2 — First Kubernetes Gateway API Implementation: Console HTTPRoute

**Roadmap reference:** [`MIGRATION-ROADMAP.md`](./MIGRATION-ROADMAP.md) — Step 2  
**Plan reference:** [`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) — W2, partial W3, W4 (already done in Step 1), W5 (Gateway resource), §5.6.1 of W6, partial W7  
**Prerequisite:** [`MIGRATION-STEP-1.md`](./MIGRATION-STEP-1.md) fully completed  
**Gateway API version target:** Kubernetes Gateway API **v1.3** (minimum; `HTTPRoute` is GA, `Gateway` `Programmed` condition is stable)  
**Status:** `[ ] pending`

---

## Overview

This deliverable introduces the Kubernetes Gateway API path
(`ingress_type: gateway-api`) into the collection for the first time. Scope is
deliberately limited to the console `HTTPRoute` only — all other `expose_*` flags
(`expose_ca`, `expose_peer`, `expose_orderer`, `expose_peer_operations`,
`expose_orderer_operations`, `expose_grpcweb`) remain `false` under the gateway-api
path in this step.

The NGINX ingress controller path is unchanged and continues to pass all tests
from Step 1. The two paths are validated in parallel in the CI matrix.

---

## Sub-task 2.1 — CI bootstrap script for Envoy Gateway

**Intent:** Create the `.github/scripts/kind_with_envoy_gateway.sh` bootstrap
script that provisions a KIND cluster with Envoy Gateway as the Gateway API
implementation reference. This mirrors `kind_with_nginx.sh` in structure and
is used exclusively by the CI `gateway-api` matrix leg.

**Expected outcomes:**
- New file `.github/scripts/kind_with_envoy_gateway.sh` is executable and
  passes `bash -n` syntax check.
- The script creates a KIND cluster with `hostPort` mappings for ports 443,
  7054, 7050, and 7051 (all four are wired now even though only 443 is used in
  this step — avoids a cluster rebuild in Step 3).
- Envoy Gateway v1.3.0 is installed from the Helm chart.
- Gateway API CRDs are installed from the standard channel
  (`standard-install.yaml` for the appropriate Gateway API version).
- A `GatewayClass` named `fabric-envoy-gateway` is created and confirmed
  `Accepted`.
- The script does **not** apply the CoreDNS override (timing constraint: the
  `Gateway` resource does not exist yet — it is created by the Ansible playbook
  in sub-task 2.3).
- A local Docker registry is launched (identical to `kind_with_nginx.sh`).

**Todo list:**
- [ ] Create `.github/scripts/kind_with_envoy_gateway.sh` from the template in
  MIGRATION-PLAN.md §5.2.
- [ ] Set `ENVOY_GATEWAY_VERSION=v1.3.0` and
  `GATEWAY_API_VERSION` to the Gateway API release that corresponds to v1.3
  conformance (verify the correct CRD release tag from the
  `kubernetes-sigs/gateway-api` releases page).
- [ ] Confirm the `install_gateway_api_crds` function waits for
  `gateways`, `httproutes`, and `tlsroutes` CRDs to be established.
- [ ] Confirm the `apply_gatewayclass` function waits for `Accepted` condition.
- [ ] Confirm the `launch_docker_registry` function is identical to the one in
  `kind_with_nginx.sh`.
- [ ] Make the script executable (`chmod +x`).
- [ ] Run `bash -n .github/scripts/kind_with_envoy_gateway.sh` for syntax check.

**Relevant context:**
- Full script content: MIGRATION-PLAN.md §5.2
- CoreDNS timing constraint explanation: MIGRATION-PLAN.md §5.2 note and §5.3.2
- The `apply_coredns_override()` function is present in the script but is
  **called from the CI workflow via `COREDNS_HOOK`**, not from within the script
  at bootstrap time (see sub-task 2.2).

---

## Sub-task 2.2 — CI workflow: `gateway-api` matrix leg

**Intent:** Add the `gateway-api` matrix leg to `fvtest.yml`. This leg uses
`kind_with_envoy_gateway.sh`, sets `INGRESS_TYPE=gateway-api`,
`EXPOSE_CONSOLE=true`, and all other `EXPOSE_*=false`. The `COREDNS_HOOK`
mechanism is wired to apply the CoreDNS override between `build_network.sh build`
and `join_network.sh join`.

**Expected outcomes:**
- `fvtest.yml` matrix now has three legs:
  1. `nginx / expose-all` (from Step 1).
  2. `nginx / expose-none` (from Step 1).
  3. `gateway-api / console-only` (new in this step).
- The `gateway-api` leg bootstraps with `kind_with_envoy_gateway.sh`, sets
  `INGRESS_TYPE=gateway-api`, `EXPOSE_CONSOLE=true`,
  `EXPOSE_CA=false`, `EXPOSE_PEER=false`, `EXPOSE_ORDERER=false`,
  `EXPOSE_PEER_OPERATIONS=false`, `EXPOSE_ORDERER_OPERATIONS=false`.
- The `COREDNS_HOOK` env var is set to `apply_gateway_coredns_override` for
  the `gateway-api` leg; the function body is exported so `run-tests.sh`'s
  sub-shell can call it.
- A post-run verification step confirms the CoreDNS override was applied
  (checks for `host.ingress.internal` in the CoreDNS ConfigMap).
- `fail-fast: false` remains set.
- `yamllint` passes on the modified workflow file.

**Todo list:**
- [ ] Extend the matrix in `fvtest.yml` to include `ingress_type: gateway-api`
  with `scenario: console-only`.
- [ ] Add the `Bootstrap cluster (gateway-api)` step from
  MIGRATION-PLAN.md §5.3.4 for this leg.
- [ ] Set `EXPOSE_CONSOLE=true` and all other `EXPOSE_*=false` in `$GITHUB_ENV`
  for this leg.
- [ ] Export the `apply_gateway_coredns_override` shell function and set
  `COREDNS_HOOK=apply_gateway_coredns_override` for the `gateway-api` leg
  (see MIGRATION-PLAN.md §5.3.4 note on `COREDNS_HOOK`).
- [ ] Add the "Verify CoreDNS override was applied (gateway-api)" post-step from
  MIGRATION-PLAN.md §5.3.4.
- [ ] Run `yamllint` on the modified file.

**Relevant context:**
- `COREDNS_HOOK` mechanism: MIGRATION-PLAN.md §5.3.3 (step 5) and §5.3.4 note
- Full `fvtest.yml` reference: MIGRATION-PLAN.md §5.3.4
- CoreDNS timing: the CoreDNS override must be applied **after**
  `build_network.sh build` has created the `fabric-gateway` Gateway resource,
  because the Envoy Gateway service ClusterIP does not exist before that.

---

## Sub-task 2.3 — Gateway resource creation in `fabric_operator_crds`

**Intent:** When `ingress_type: gateway-api`, the `fabric_operator_crds` role
creates the namespace-scoped `Gateway` resource with the `https` listener (port
443, HTTPS terminated). The three TLS passthrough listeners (CA, orderer, peer)
are also included in the template now so they are present for Step 3 without
requiring a Gateway resource update.

**Expected outcomes:**
- New template
  `roles/fabric_operator_crds/templates/k8s/gateway/fabric-gateway.yaml.j2`
  with all four listeners as specified in MIGRATION-PLAN.md §5.5.
- Two new tasks in `roles/fabric_operator_crds/tasks/k8s/create.yml`:
  "Create fabric Gateway resource" and "Wait for fabric Gateway to be
  programmed", both guarded by `when: ingress_type == 'gateway-api'`.
- When `ingress_type: nginx`, `create.yml` is **byte-for-byte identical** to
  the pre-Step-2 state (the new tasks are guarded and never executed).
- The Gateway `Programmed` condition is checked before proceeding.
- `ansible-lint` and `yamllint` pass on all modified files.

**Todo list:**
- [ ] Create the directory
  `roles/fabric_operator_crds/templates/k8s/gateway/`.
- [ ] Create
  `roles/fabric_operator_crds/templates/k8s/gateway/fabric-gateway.yaml.j2`
  from MIGRATION-PLAN.md §5.5, ensuring all four listeners are present
  (`https`, `ca-passthrough`, `orderer-passthrough`, `peer-passthrough`).
- [ ] Verify template uses `{{ ingress_ca_port }}`, `{{ ingress_grpc_orderer_port }}`,
  `{{ ingress_grpc_peer_port }}` for the passthrough listener ports (not
  hardcoded integers).
- [ ] Add the "Create fabric Gateway resource" task to
  `roles/fabric_operator_crds/tasks/k8s/create.yml` with
  `when: ingress_type == 'gateway-api'`.
- [ ] Add the "Wait for fabric Gateway to be programmed" task using the
  `Programmed=True` condition check from MIGRATION-PLAN.md §5.5.
- [ ] Confirm the `when` guard uses `==` string comparison (not `is`).
- [ ] Run `ansible-lint` on `roles/fabric_operator_crds/tasks/k8s/create.yml`.

**Relevant context:**
- Full template and task YAML: MIGRATION-PLAN.md §5.5
- `Programmed` condition is stable in Gateway API v1.0+; available in v1.3.
- `ingress_tls_secret` defaults to `fabric-tls-secret` in the template
  (`| default('fabric-tls-secret')`).

---

## Sub-task 2.4 — Console `HTTPRoute` template and task

**Intent:** Add the `HTTPRoute` template and the corresponding post-task for the
console, guarded by `ingress_type == 'gateway-api' and expose_console | bool`.
In this step this is the only new route resource created under the gateway-api
path.

**Expected outcomes:**
- New template
  `roles/fabric_console/templates/k8s/gateway/httproute-console.yaml.j2`.
- New task in `roles/fabric_console/tasks/k8s/create.yml` (after the console
  creation tasks) that creates the `HTTPRoute` resource when the gateway-api
  path is active and `expose_console: true`.
- Same template and task added to `roles/hlfsupport_console` if it has a
  parallel task file.
- `ansible-lint` and `yamllint` pass on all modified files.

**Todo list:**
- [ ] Create directory `roles/fabric_console/templates/k8s/gateway/`.
- [ ] Create
  `roles/fabric_console/templates/k8s/gateway/httproute-console.yaml.j2`
  from MIGRATION-PLAN.md §5.6.1.
- [ ] Verify `backendRefs[].port` is an integer (not a string) per the
  Kubernetes Gateway API specification.
- [ ] Add the HTTPRoute creation task to
  `roles/fabric_console/tasks/k8s/create.yml` with guard
  `when: ingress_type == 'gateway-api' and expose_console | bool`.
- [ ] Identify whether `roles/hlfsupport_console` has a parallel task file
  requiring the same treatment; if yes, replicate.
- [ ] Run `ansible-lint` on the modified task files.

**Relevant context:**
- Full template: MIGRATION-PLAN.md §5.6.1
- `backendRefs[].port` must be an integer (Gateway API API spec — see
  PROMPTS.md note on BackendRef port type).
- `component_service_port` must be set to the correct integer port for the
  console Service (confirm from the `IBPConsole` operator output).

---

## Sub-task 2.5 — Console wait-logic: Gateway API branch

**Intent:** Add the Gateway API-specific branch to the console wait-logic so
that when `ingress_type: gateway-api` and `expose_console: true` the collection
waits for the `HTTPRoute` resource (not the `Ingress`) and derives `console_url`
from the route's `hostnames` field.

**Expected outcomes:**
- `roles/hlfsupport_console/tasks/k8s/create.yml` and
  `roles/fabric_console/tasks/k8s/create.yml` contain:
  - An `[NGINX]` wait-for-ingress block (guarded by
    `ingress_type == 'nginx' and expose_console | bool`).
  - A `[GW]` wait-for-HTTPRoute block (guarded by
    `ingress_type == 'gateway-api' and expose_console | bool`).
  - The `expose_console: false` in-cluster branch (unchanged from Step 1).
- The `console_url` fact is correctly set from the `HTTPRoute`'s
  `spec.hostnames[0]` on the gateway-api path.

**Todo list:**
- [ ] In the console task files, add the "Wait for console HTTPRoute to exist"
  and "Set console URL from HTTPRoute" tasks from MIGRATION-PLAN.md §5.5,
  guarded by `ingress_type == 'gateway-api' and expose_console | bool`.
- [ ] Confirm the `kubernetes.core.k8s_info` call uses
  `api_version: gateway.networking.k8s.io/v1` and `kind: HTTPRoute`.
- [ ] Confirm the `console_url` is derived from
  `console_httproute.resources[0].spec.hostnames[0]`.
- [ ] Run `ansible-lint` on the modified files.

**Relevant context:**
- Full task YAML: MIGRATION-PLAN.md §5.5 (the complete five-task block)
- Step 1 already added the `expose_console: false` in-cluster branch; this
  sub-task only adds the `gateway-api` conditional branches for the `true` case.

---

## Sub-task 2.6 — Integration test: gateway-api console-only scenario

**Intent:** Define the explicit integration test assertions for the
`gateway-api / console-only` CI leg. These confirm that the `HTTPRoute` is
created, the Gateway is programmed, the console is reachable at its public URL,
and no TLSRoute resources exist (because all other `expose_*` are false).

**Expected outcomes:**
- A "Verify gateway-api console-only" step in `fvtest.yml` conditioned on
  `matrix.ingress_type == 'gateway-api'`.
- The step asserts:
  - `kubectl get gateway fabric-gateway -n fabricinfra` shows `Programmed=True`.
  - `kubectl get httproute -n fabricinfra` shows exactly one HTTPRoute (for the
    console).
  - `kubectl get tlsroute -n fabricinfra` returns no resources.
  - A `curl` (or `kubectl exec`) call to the console public URL returns HTTP 200.
- The full tutorial sequence (`build_network.sh build`, `join_network.sh join`,
  `deploy_smart_contract.sh`) succeeds end-to-end on this leg.

**Todo list:**
- [ ] Add a "Verify gateway-api console-only scenario" step to `fvtest.yml`
  conditioned on `matrix.ingress_type == 'gateway-api'`.
- [ ] Assert `Gateway/fabric-gateway` has `Programmed=True` using
  `kubectl wait --for=condition=Programmed`.
- [ ] Assert exactly one `HTTPRoute` exists in the namespace (the console route).
- [ ] Assert zero `TLSRoute` resources exist in the namespace.
- [ ] Verify the tutorial sequence completes without errors (already covered
  by the `run-tests.sh` execution; this step adds the resource-level checks).

**Relevant context:**
- Parity table: MIGRATION-PLAN.md §5.3.5
- Gateway API `kubectl wait` syntax:
  `kubectl wait gateway/fabric-gateway -n fabricinfra --for=condition=Programmed`

---

## Sub-task 2.7 — Tutorial: `gateway-api-install.rst`

**Intent:** Create the shared prerequisite tutorial that documents how to install
a conformant Gateway API controller (using Envoy Gateway as the reference), create
the `GatewayClass`, and prepare the TLS Secret before running any collection
playbook. This tutorial is linked from all subsequent Gateway API role tutorials.

**Expected outcomes:**
- New file `docs/source/tutorials/gateway-api-install.rst`.
- Covers the six content items listed in MIGRATION-PLAN.md §5.7 key-content section:
  1. The four-listener Gateway model and port choices.
  2. GatewayClass and Envoy Gateway as cluster prerequisites.
  3. `api_url` port changes for peers (7051) and orderers (7050).
  4. CA TLS passthrough on port 7054; gRPC-Web and operations on 443.
  5. `kubectl get gateway` verification command.
  6. The `localho.st` wildcard DNS trick and CoreDNS override timing.
- Added to `toctree` in `docs/source/index.rst`.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Create `docs/source/tutorials/gateway-api-install.rst` with the content
  specified in MIGRATION-PLAN.md §5.7 (key content section).
- [ ] Include a prerequisite table referencing Envoy Gateway installation
  commands (Helm install) and Gateway API CRD installation.
- [ ] Include the shared variables table from MIGRATION-PLAN.md §5.7
  (shared Gateway API variables section).
- [ ] Include a step to create the TLS Secret
  (`kubectl create secret tls fabric-tls-secret ...`) in the target namespace.
- [ ] Add `gateway-api-install` to the tutorials `toctree` in
  `docs/source/index.rst`.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Key content items: MIGRATION-PLAN.md §5.7 "Key content for gateway-api-install.rst"
- Shared variables table: MIGRATION-PLAN.md §5.7 "Shared Gateway API variables"
- Note: this tutorial covers controller installation (a user prerequisite), not
  collection role tasks — the collection does not install the controller.

---

## Sub-task 2.8 — Tutorial: `gateway-api-console.rst`

**Intent:** Create the console-specific Gateway API tutorial demonstrating how to
deploy the Fabric Operations Console with an `HTTPRoute` using either
`fabric_console` or `hlfsupport_console`. This is the first end-to-end
Gateway API user-facing tutorial.

**Expected outcomes:**
- New file `docs/source/tutorials/gateway-api-console.rst`.
- Covers both `fabric_console` and `hlfsupport_console` with separate examples.
- Documents `ingress_type: gateway-api`, `expose_console: true`,
  `expose_ca: false`, `expose_peer: false`, `expose_orderer: false` (the
  Step 2 configuration).
- Shows how to provide the TLS Secret and `ingress_domain` variables.
- Shows how to verify the `HTTPRoute` with
  `kubectl get httproute -n <namespace>`.
- Documents the `expose_console: false` variant and explains when to use it.
- Added to `toctree` in `docs/source/index.rst`.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Create `docs/source/tutorials/gateway-api-console.rst` with:
  - Reference to `gateway-api-install.rst` as the prerequisite.
  - Example vars file showing `ingress_type: gateway-api`, `expose_console: true`,
    `gateway_class_name: fabric-envoy-gateway`, `ingress_domain: example.com`,
    `ingress_tls_secret: fabric-tls-secret`.
  - Step-by-step execution of the console playbook.
  - Verification: `kubectl get httproute`, `kubectl get gateway`.
  - `expose_console: false` section explaining in-cluster usage and the notice
    message printed by the collection.
- [ ] Link the tutorial from `docs/source/roles/fabric-console.rst` and
  `docs/source/roles/hlfsupport_console.rst`.
- [ ] Add `gateway-api-console` to the tutorials `toctree` in
  `docs/source/index.rst`.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Tutorial content requirements: MIGRATION-PLAN.md §5.7, item 2
  (`fabric_console` and `hlfsupport_console` section).
- New variables table for console roles: MIGRATION-PLAN.md §5.7, console
  variables subsection.

---

## Acceptance criteria for Step 2

A Step 2 delivery is considered complete when all of the following pass:

1. `ansible-lint` and `yamllint` pass on all modified files.
2. All Step 1 acceptance criteria still pass (no regression on nginx legs).
3. A KIND cluster bootstrapped with `kind_with_envoy_gateway.sh` successfully
   installs Envoy Gateway and creates the `fabric-envoy-gateway` GatewayClass
   (`kubectl get gatewayclass fabric-envoy-gateway` shows `Accepted=True`).
4. `fvtest.yml` runs three legs: `nginx/expose-all`, `nginx/expose-none`, and
   `gateway-api/console-only`; all three complete successfully with
   `fail-fast: false`.
5. On the `gateway-api/console-only` leg:
   - `Gateway/fabric-gateway` shows `Programmed=True`.
   - Exactly one `HTTPRoute` exists in the namespace (console route).
   - Zero `TLSRoute` resources exist in the namespace.
   - The full tutorial sequence (`build_network.sh build` → `join_network.sh join`
     → `deploy_smart_contract.sh`) completes end-to-end.
6. CoreDNS override is applied via `COREDNS_HOOK` after the `Gateway` resource
   is created (confirmed by `grep host.ingress.internal` in the CoreDNS
   ConfigMap).
7. `make -C docs html` builds without warnings.
8. `ingress_type: nginx` path is unchanged from Step 1 —
   `roles/fabric_operator_crds/tasks/k8s/create.yml` produces no Gateway API
   API calls when `ingress_type == 'nginx'`.
9. Kubernetes Gateway API version targeted is **v1.3** minimum (CRDs installed
   from the standard channel; `HTTPRoute` is a standard/GA resource in v1.0+).
   `TLSRoute` is **not** introduced in this step — it becomes standard/GA in
   v1.5 and is addressed in Step 3. No TLSRoute CRDs are required for Step 2.
