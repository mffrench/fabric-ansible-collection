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
playbooks continue to work without modification.

**Expected outcomes:**
- `roles/fabric_operator_crds/defaults/main.yml` contains `ingress_type: nginx`,
  the six `expose_*` flags, the three port variables, and `gateway_class_name`.
- `ansible-lint` and `yamllint` pass on the modified file.
- All existing tests pass without setting any new variable.

**Todo list:**
- [ ] Add `ingress_type: nginx` to
  `roles/fabric_operator_crds/defaults/main.yml`.
- [ ] Add `expose_console: true`, `expose_ca: true`, `expose_peer: true`,
  `expose_orderer: true`, `expose_peer_operations: false`,
  `expose_orderer_operations: false`, `expose_grpcweb: false`.
- [ ] Add `gateway_class_name: fabric-envoy-gateway`,
  `ingress_ca_port: 7054`, `ingress_grpc_orderer_port: 7050`,
  `ingress_grpc_peer_port: 7051` (consumed in later steps; inert here).
- [ ] Add inline comments explaining every variable's purpose and when to
  override it, as specified in MIGRATION-PLAN.md §5.1.
- [ ] Run `ansible-lint` and `yamllint` on the file.

**Relevant context:**
- Target file: `roles/fabric_operator_crds/defaults/main.yml`
- Full variable definitions with comments: MIGRATION-PLAN.md §5.1
- The file must not contain any conditional logic — only `key: value` defaults.

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

## Sub-task 1.5 — CI workflow: no-expose scenario matrix leg

**Intent:** Extend `fvtest.yml` with a second test leg that validates the
extreme opposite scenario on the nginx path: `expose_console: false`,
`expose_ca: false`, `expose_peer: false`, `expose_orderer: false`. This leg
confirms that a fully in-cluster deployment (Scenario A — all traffic stays
inside the cluster) works with the nginx backend.

**Expected outcomes:**
- `fvtest.yml` runs two legs on every push:
  1. `nginx` — all `expose_*: true` (current Scenario B behaviour, no change).
  2. `nginx-no-expose` — `expose_console: false`, `expose_ca: false`,
     `expose_peer: false`, `expose_orderer: false`.
- Both legs use the same `kind_with_nginx.sh` bootstrap script.
- The `nginx-no-expose` leg succeeds: the test network builds, channels are
  created, chaincode is deployed, and no external ingress routes are required.
- `fail-fast: false` is set so both legs always complete.

**Todo list:**
- [ ] Add a `scenario` matrix dimension to the `fvtest` job in
  `.github/workflows/fvtest.yml` with values `[expose-all, expose-none]`.
- [ ] For `expose-all`: set `EXPOSE_CONSOLE=true`, `EXPOSE_CA=true`,
  `EXPOSE_PEER=true`, `EXPOSE_ORDERER=true` in `$GITHUB_ENV`.
- [ ] For `expose-none`: set all four to `false` in `$GITHUB_ENV`. Also set
  `EXPOSE_PEER_OPERATIONS=false` and `EXPOSE_ORDERER_OPERATIONS=false`.
- [ ] Keep `INGRESS_TYPE=nginx` for both legs (Gateway API is Step 2).
- [ ] Ensure the `run-tests.sh` call reads the new env vars correctly
  (already handled by sub-task 1.4).
- [ ] Set `name: FV test (${{ matrix.ingress_type }} / ${{ matrix.scenario }})`
  on the job.
- [ ] Run `yamllint` on the modified workflow file.

**Relevant context:**
- Current workflow: `.github/workflows/fvtest.yml`
- Reference full matrix design: MIGRATION-PLAN.md §5.3.4 (the gateway-api leg
  is **not** added in this step — add it as a comment stub or leave for Step 2).
- Scenario A vs Scenario B rationale: MIGRATION-PLAN.md §5.3.5 and
  PRE-ANALYSIS.md §2.5

---

## Sub-task 1.6 — New integration test: no-expose scenario validation

**Intent:** Write an explicit integration test assertion that confirms the
no-expose scenario works end-to-end: the console is reachable at its in-cluster
URL, and no ingress/route resources exist in the namespace for CA, peer, or
orderer.

**Expected outcomes:**
- A new test or assertion step in the `nginx-no-expose` CI leg verifies:
  - `kubectl get ingress -n fabricinfra` returns no resources for CA, peer,
    or orderer (only possibly the console if it had one — but in this leg it
    does not).
  - The console health-check via in-cluster URL succeeds (pod is running and
    returns HTTP 200 on its internal port).
  - The tutorial playbooks (`build_network.sh build`, `join_network.sh join`,
    `deploy_smart_contract.sh`) all succeed — confirming that Ansible can reach
    all services via in-cluster ClusterIP without going through the ingress.

**Todo list:**
- [ ] Add a "Verify no-expose scenario" step in `fvtest.yml` conditioned on
  `matrix.scenario == 'expose-none'`.
- [ ] The verification step should:
  - Assert `kubectl get ingress -n fabricinfra` contains no CA, peer, or
    orderer ingress objects.
  - Assert the console pod responds at its in-cluster ClusterIP (use
    `kubectl exec` or a pod-based curl).
- [ ] Confirm that the tutorial sequence still succeeds end-to-end in this leg
  (the test runner already does this; the step just adds explicit ingress-absence
  assertions).

**Relevant context:**
- Scenario A description: PRE-ANALYSIS.md §2.4 and MIGRATION-PLAN.md §5.3.5
- In-cluster reachability: components are always reachable via ClusterIP from
  within the cluster regardless of ingress configuration.

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
   `nginx/expose-none`; both complete successfully.
4. The `nginx/expose-all` leg is byte-for-byte equivalent in test coverage to
   the pre-Step-1 single-leg run — no existing test scenario has been removed
   or weakened.
5. The `nginx/expose-none` leg verifies: no ingress objects for CA/peer/orderer,
   console reachable in-cluster, full tutorial sequence (build/join/deploy)
   succeeds.
6. `docs/source` builds without warnings (`make -C docs html`).
7. No Gateway API CRD, template, task, or Kubernetes resource is introduced —
   the Gateway API path is entirely absent from the codebase at this stage.
