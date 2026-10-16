# Step 3 — Full Kubernetes Gateway API Implementation: All `expose_*` Variables

**Roadmap reference:** [`MIGRATION-ROADMAP.md`](./MIGRATION-ROADMAP.md) — Step 3  
**Plan reference:** [`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) — §5.6.2–§5.6.9 of W6, §6, remaining W3, remaining W7, §5.6.10  
**Prerequisite:** [`MIGRATION-STEP-2.md`](./MIGRATION-STEP-2.md) fully completed  
**Gateway API version target:** v1.3 minimum for HTTPRoute-only clusters; v1.5+ required for TLSRoute (Standard/GA). See §Version compatibility below.  
**Status:** `[ ] pending`

---

## Overview

This deliverable completes the Kubernetes Gateway API path by implementing the
`TLSRoute` resources for peers, orderers, and CAs, along with the optional
operations `HTTPRoute`s and the gRPC-Web `HTTPRoute`. The full four-listener
`Gateway` topology — HTTPS `:443`, CA passthrough `:7054`, orderer passthrough
`:7050`, peer passthrough `:7051` — becomes operational.

The CI test matrix is extended to the full Scenario B configuration (all services
exposed externally). The NGINX ingress controller path remains unchanged and all
prior tests continue to pass. Port changes in plugin modules and `url_utils.py`
are applied to ensure `api_url` values are correct under the gateway-api path.

---

## Version compatibility analysis

### Sources

| Document | URL |
|----------|-----|
| Gateway API versioning policy | https://gateway-api.sigs.k8s.io/concepts/versioning/ |
| Gateway API v1.3 API spec | https://gateway-api.sigs.k8s.io/reference/api-spec/1.3/ |
| Gateway API v1.6 API spec | https://gateway-api.sigs.k8s.io/reference/api-spec/1.6/spec/ |
| Gateway API releases | https://github.com/kubernetes-sigs/gateway-api/releases |
| Kubernetes blog — Gateway API v1.5 / TLSRoute promotion | https://kubernetes.io/blog/2026/04/21/gateway-api-v1-5/ |

### Resource maturity table

| Resource | Standard/GA since | Still standard in v1.6 | Breaking changes v1.3→v1.6 |
|----------|-------------------|------------------------|---------------------------|
| `HTTPRoute` | **v1.0** | ✅ | None identified |
| `Gateway` | **v1.0** | ✅ | None identified |
| `GatewayClass` | **v1.0** | ✅ | None identified |
| `TLSRoute` | **v1.5** (Experimental in v1.0–v1.4) | ✅ | N/A — not standard before v1.5 |

### Key finding: no breaking changes between v1.3 and v1.6

All resources used by Steps 2 and 3 of this migration use the `v1` API version.
The stable `v1` API surface for `HTTPRoute`, `Gateway`, and `GatewayClass` is
additive only across v1.3 → v1.6: fields are added or graduated, never removed
or renamed in a breaking way. A manifest written for v1.3 is **valid as-is on a
v1.6 cluster**.

The only operational difference is the CRD installation channel:

| Feature | v1.3 cluster | v1.5+ cluster |
|---------|-------------|---------------|
| `HTTPRoute` | `standard-install.yaml` | `standard-install.yaml` |
| `TLSRoute` | `experimental-install.yaml` only | `standard-install.yaml` |

### Smooth migration path: v1.3 → v1.6

The collection handles this by making the CRD channel selection a CI script
variable and documenting the minimum version per feature:

1. **Step 2 (HTTPRoute only):** requires Gateway API v1.3 minimum. CRDs
   installed with `standard-install.yaml`. No TLSRoute CRD needed.

2. **Step 3 (TLSRoute added):** requires Gateway API **v1.5 minimum** because
   `TLSRoute` enters the standard channel only in v1.5. The CI script variable
   `GATEWAY_API_VERSION` is bumped from the v1.3 tag to a v1.5+ tag. No manifest
   changes are required — the `TLSRoute` YAML shape is compatible with both the
   experimental channel (v1.3) and the standard channel (v1.5+).

3. **User guidance:** the `gateway-api-install.rst` tutorial documents the
   minimum version per use-case:
   - Console-only (`expose_console: true`, all others `false`): v1.3+.
   - Full exposure including `TLSRoute`: v1.5+.

This means a user who is constrained to a v1.3 cluster can still use Step 2
(console HTTPRoute) without upgrading. Upgrading the cluster to v1.5+ unlocks
Step 3.

---

## Sub-task 3.1 — Bump CI `GATEWAY_API_VERSION` to v1.5+

**Intent:** Update `kind_with_envoy_gateway.sh` to install Gateway API CRDs from
a v1.5+ release so that `TLSRoute` is available in the standard channel.
The script variable `GATEWAY_API_VERSION` controls this. The `standard-install.yaml`
bundle is used — no experimental channel is needed from v1.5 onwards.

**Expected outcomes:**
- `GATEWAY_API_VERSION` in `kind_with_envoy_gateway.sh` is set to a v1.5+
  release tag (e.g. `v1.5.0` or later).
- `install_gateway_api_crds()` continues to wait for `tlsroutes` CRD to be
  established (already present in the function from Step 2).
- `bash -n` syntax check still passes.
- No other changes to the script are required.

**Todo list:**
- [ ] Determine the most recent stable Gateway API release ≥ v1.5 from
  https://github.com/kubernetes-sigs/gateway-api/releases.
- [ ] Update `GATEWAY_API_VERSION` in `.github/scripts/kind_with_envoy_gateway.sh`
  to that release tag.
- [ ] Confirm `standard-install.yaml` for that release includes the
  `tlsroutes.gateway.networking.k8s.io` CRD.
- [ ] Run `bash -n .github/scripts/kind_with_envoy_gateway.sh`.

**Relevant context:**
- Current value: `GATEWAY_API_VERSION=${GATEWAY_API_VERSION:-v1.6.0}` (from
  MIGRATION-PLAN.md §5.2 — this already targets v1.6; confirm it is still
  the latest stable or update accordingly).
- TLSRoute channel history: standard since v1.5 (see version compatibility
  table above).

---

## Sub-task 3.2 — `TLSRoute` template and post-task for CA (`expose_ca`)

**Intent:** Add the `TLSRoute` template and post-task for the Fabric CA. The CA
must use TLS passthrough (not terminated) because CA enrollment validates the
CA's own TLS certificate. The route is guarded by
`ingress_type == 'gateway-api' and expose_ca | bool`.

**Expected outcomes:**
- New template
  `roles/certificate_authority/templates/k8s/gateway/tlsroute-ca.yaml.j2`.
- New task in the CA role's creation task file that creates the `TLSRoute` when
  the conditions are met.
- `api_url` and `operations_url` for the CA resolve to the CA Service on port
  7054 via TLS passthrough.
- `ansible-lint` and `yamllint` pass on all modified files.

**Todo list:**
- [ ] Confirm the exact role and task file path: inspect the project for the
  `certificate_authority` role and its creation task (e.g.
  `roles/certificate_authority/tasks/create.yml`).
- [ ] Create directory `roles/certificate_authority/templates/k8s/gateway/`.
- [ ] Create `tlsroute-ca.yaml.j2` from MIGRATION-PLAN.md §5.6.2.
- [ ] Verify `backendRefs[].port` is the integer `7054` (not a string).
- [ ] Verify `sectionName: ca-passthrough` (matches the listener name in the
  `fabric-gateway` Gateway resource created in Step 2).
- [ ] Verify `parentRefs[].name: fabric-gateway`.
- [ ] Add the TLSRoute creation task from MIGRATION-PLAN.md §5.6.9 with guard:
  `when: ingress_type == 'gateway-api' and expose_ca | bool`.
- [ ] Set `ca_api_hostname: "{{ ca_api_url | urlsplit('hostname') }}"` in the
  task `vars:` block.
- [ ] Run `ansible-lint` on the modified task file.

**Relevant context:**
- Template: MIGRATION-PLAN.md §5.6.2
- Post-task: MIGRATION-PLAN.md §5.6.9
- CA must remain passthrough: PROMPTS.md entry "Fix Fabric CA exposition from
  the ingress" and MIGRATION-PLAN.md §5.6.2 first paragraph.

---

## Sub-task 3.3 — `TLSRoute` template and post-task for peer gRPC API (`expose_peer`)

**Intent:** Add the `TLSRoute` template and post-task for peer gRPC API access.
Peers use TLS passthrough on port 7051 so that mutual TLS (mTLS) is
end-to-end between Fabric clients and the peer pod.

**Expected outcomes:**
- New template
  `roles/endorsing_organization/templates/k8s/gateway/tlsroute-peer.yaml.j2`.
- New task in `roles/endorsing_organization/tasks/create.yml` guarded by
  `ingress_type == 'gateway-api' and expose_peer | bool`.
- `ansible-lint` and `yamllint` pass.

**Todo list:**
- [ ] Create directory
  `roles/endorsing_organization/templates/k8s/gateway/` if not already present
  from Step 2.
- [ ] Create `tlsroute-peer.yaml.j2` from MIGRATION-PLAN.md §5.6.5.
- [ ] Verify `backendRefs[].port` is the integer `7051`.
- [ ] Verify `sectionName: peer-passthrough`.
- [ ] Add the TLSRoute creation task from MIGRATION-PLAN.md §5.6.7 (first block)
  to `roles/endorsing_organization/tasks/create.yml`.
- [ ] Confirm `peer_api_hostname` derives from
  `peer_api_url | urlsplit('hostname')`.
- [ ] Run `ansible-lint` on the modified task file.

**Relevant context:**
- Template: MIGRATION-PLAN.md §5.6.5
- Post-task: MIGRATION-PLAN.md §5.6.7 (first task block)

---

## Sub-task 3.4 — `HTTPRoute` template and post-task for peer operations (`expose_peer_operations`)

**Intent:** Add the optional operations `HTTPRoute` for the peer's `/healthz`
endpoint. Default is `false`. The recommended in-cluster alternative is
`kubernetes.core.k8s_info` watching `status.conditions` on the `IBPPeer`
resource.

**Expected outcomes:**
- New template
  `roles/endorsing_organization/templates/k8s/gateway/httproute-operations.yaml.j2`
  (parameterized; reused for orderer operations in sub-task 3.6).
- New task in `roles/endorsing_organization/tasks/create.yml` guarded by
  `ingress_type == 'gateway-api' and expose_peer_operations | bool`.
- `ansible-lint` and `yamllint` pass.

**Todo list:**
- [ ] Create `httproute-operations.yaml.j2` from MIGRATION-PLAN.md §5.6.3.
- [ ] Verify `backendRefs[].port` is the integer `9443`.
- [ ] Verify `sectionName: https`.
- [ ] Add the peer operations HTTPRoute creation task from
  MIGRATION-PLAN.md §5.6.7 (second task block).
- [ ] Confirm `component_operations_port` is the integer `9443` in the `vars:`
  block.
- [ ] Run `ansible-lint` on the modified task file.

**Relevant context:**
- Template: MIGRATION-PLAN.md §5.6.3
- Post-task: MIGRATION-PLAN.md §5.6.7 (second block)
- Default `expose_peer_operations: false` set in Step 1 sub-task 1.1.

---

## Sub-task 3.5 — `HTTPRoute` template and post-task for peer gRPC-Web proxy (`expose_grpcweb`)

**Intent:** Add the optional gRPC-Web `HTTPRoute` for the peer's gRPC-Web
sidecar. Default is `false`. Browser-facing; consumed by the Fabric Operations
Console UI.

**Expected outcomes:**
- New template
  `roles/endorsing_organization/templates/k8s/gateway/httproute-grpcweb.yaml.j2`.
- New task in `roles/endorsing_organization/tasks/create.yml` guarded by
  `ingress_type == 'gateway-api' and expose_grpcweb | bool`.
- `ansible-lint` and `yamllint` pass.

**Todo list:**
- [ ] Create `httproute-grpcweb.yaml.j2` from MIGRATION-PLAN.md §5.6.4.
- [ ] Verify `backendRefs[].port` is the integer `443` (gRPC-Web sidecar port).
- [ ] Verify `sectionName: https`.
- [ ] Add the gRPC-Web HTTPRoute creation task from MIGRATION-PLAN.md §5.6.7
  (third task block).
- [ ] Confirm `peer_grpcweb_service` derives the sidecar Service name as
  `peer_name | lower | replace(' ', '-') + '-grpcwebproxy'` and verify this
  matches the actual Service name produced by `fabric-operator`.
- [ ] Run `ansible-lint` on the modified task file.

**Relevant context:**
- Template: MIGRATION-PLAN.md §5.6.4
- Post-task: MIGRATION-PLAN.md §5.6.7 (third block)

---

## Sub-task 3.6 — `TLSRoute` template and post-task for orderer gRPC API (`expose_orderer`)

**Intent:** Add the `TLSRoute` template and post-task for orderer gRPC API access.
Orderers use TLS passthrough on port 7050 so that mTLS is end-to-end.

**Expected outcomes:**
- New template
  `roles/ordering_organization/templates/k8s/gateway/tlsroute-orderer.yaml.j2`.
- New task in `roles/ordering_organization/tasks/create.yml` guarded by
  `ingress_type == 'gateway-api' and expose_orderer | bool`.
- `ansible-lint` and `yamllint` pass.

**Todo list:**
- [ ] Create directory
  `roles/ordering_organization/templates/k8s/gateway/`.
- [ ] Create `tlsroute-orderer.yaml.j2` from MIGRATION-PLAN.md §5.6.6.
- [ ] Verify `backendRefs[].port` is the integer `7050`.
- [ ] Verify `sectionName: orderer-passthrough`.
- [ ] Add the orderer TLSRoute creation task from MIGRATION-PLAN.md §5.6.8
  (first task block).
- [ ] Confirm `orderer_api_hostname` derives from
  `orderer_api_url | urlsplit('hostname')`.
- [ ] Run `ansible-lint` on the modified task file.

**Relevant context:**
- Template: MIGRATION-PLAN.md §5.6.6
- Post-task: MIGRATION-PLAN.md §5.6.8 (first block)

---

## Sub-task 3.7 — `HTTPRoute` post-task for orderer operations (`expose_orderer_operations`)

**Intent:** Add the optional operations `HTTPRoute` for the orderer's `/healthz`
endpoint, reusing the `httproute-operations.yaml.j2` template from sub-task 3.4.
Default is `false`.

**Expected outcomes:**
- The shared `httproute-operations.yaml.j2` template (created in sub-task 3.4)
  is reused unchanged.
- New task in `roles/ordering_organization/tasks/create.yml` guarded by
  `ingress_type == 'gateway-api' and expose_orderer_operations | bool`.
- `ansible-lint` and `yamllint` pass.

**Todo list:**
- [ ] Add the orderer operations HTTPRoute creation task from
  MIGRATION-PLAN.md §5.6.8 (second task block) to
  `roles/ordering_organization/tasks/create.yml`.
- [ ] Confirm the template path reference points to the correct location of
  the shared `httproute-operations.yaml.j2`.
- [ ] Confirm `component_operations_port` is the integer `9443`.
- [ ] Run `ansible-lint` on the modified task file.

**Relevant context:**
- Post-task: MIGRATION-PLAN.md §5.6.8 (second block)
- Template shared with peer operations: sub-task 3.4 above.

---

## Sub-task 3.8 — Port change impact: `url_utils.py` and plugin modules

**Intent:** Update `plugins/module_utils/url_utils.py` and the affected plugin
modules so that `api_url` values for peers and orderers use the correct canonical
ports (7051 and 7050 respectively) when `ingress_type: gateway-api`. The nginx
path is unchanged.

**Expected outcomes:**
- `translate_url_to_os_format()` in `url_utils.py` accepts an optional
  `canonical_port` argument (defaults to `'443'` for backwards compatibility).
- Plugin modules that construct `api_url` samples pass the appropriate port
  on the gateway-api path.
- Existing unit tests pass without modification.
- New unit tests cover the `canonical_port` argument.

**Todo list:**
- [ ] Read the current implementation of
  [`plugins/module_utils/url_utils.py`](../../plugins/module_utils/url_utils.py).
- [ ] Add optional `canonical_port: str = '443'` parameter to
  `translate_url_to_os_format()`.
- [ ] Update callers in `peer_metadata.py` and
  `ordering_service_node_metadata.py` to pass `canonical_port='7051'` and
  `canonical_port='7050'` respectively when `ingress_type == 'gateway-api'`.
- [ ] Update the sample port comments (`:32000` → `:7051` / `:7050`) in the
  documentation strings of the following plugin modules (see MIGRATION-PLAN.md §6):
  - `plugins/modules/peer.py` (line 533 area)
  - `plugins/modules/peer_info.py` (line 97 area)
  - `plugins/modules/ordering_service_node.py` (line 422 area)
  - `plugins/modules/ordering_service_node_info.py` (line 94 area)
  - `plugins/modules/ordering_service.py` (line 339 area)
  - `plugins/modules/ordering_service_info.py` (line 95 area)
  - `plugins/modules/external_ordering_service_node.py` (line 179 area)
  - `plugins/modules/external_peer.py` (line 161 area)
- [ ] Update `tests/integration/.../one_node_ordering_service.json.j2` line 3
  to use `:7050` on the gateway-api path.
- [ ] Run existing unit tests (`pytest` or equivalent) to confirm no regression.
- [ ] Add unit tests for `translate_url_to_os_format(canonical_port='7051')` and
  `translate_url_to_os_format(canonical_port='7050')`.

**Relevant context:**
- Full port change impact table: MIGRATION-PLAN.md §6
- `translate_url_to_os_format`: MIGRATION-PLAN.md §6 last paragraph
- Only documentation-string samples and the `canonical_port` argument change;
  no functional path changes for nginx are permitted.

---

## Sub-task 3.9 — CI workflow: Scenario B full-exposure `gateway-api` matrix leg

**Intent:** Extend `fvtest.yml` with a Scenario B leg: all `expose_*` flags
`true`. This is the full CI validation of the complete Gateway API path. The
`nginx` legs from Steps 1 and 2 are unchanged.

**Expected outcomes:**
- `fvtest.yml` matrix adds a `gateway-api / expose-all` leg (Scenario B).
- The leg sets: `EXPOSE_CONSOLE=true`, `EXPOSE_CA=true`, `EXPOSE_PEER=true`,
  `EXPOSE_ORDERER=true`, `EXPOSE_PEER_OPERATIONS=true`,
  `EXPOSE_ORDERER_OPERATIONS=true`, `EXPOSE_GRPCWEB=false`.
  (`EXPOSE_GRPCWEB=false` — gRPC-Web is browser-facing and not exercised by
  the Ansible test runner.)
- `fail-fast: false` remains set.
- `yamllint` passes on the modified workflow file.

**Todo list:**
- [ ] Add the `gateway-api / expose-all` leg to the `fvtest.yml` matrix.
- [ ] Set all `EXPOSE_*` environment variables as listed above in `$GITHUB_ENV`.
- [ ] Confirm `COREDNS_HOOK` is set for this leg (same mechanism as Step 2
  sub-task 2.2).
- [ ] Decide whether to retain the Step 2 `gateway-api / console-only` leg or
  replace it with the new `expose-all` leg; document the decision.
- [ ] Run `yamllint` on the modified file.

**Relevant context:**
- Scenario B rationale: MIGRATION-PLAN.md §5.3.5 parity table; PRE-ANALYSIS §2.5.3
- Why `expose_peer_operations=true` in CI: the CI runner is outside the cluster
  and polls `/healthz` via the gateway. `kubernetes.core.k8s_info` readiness
  watch is a future improvement (MIGRATION-PLAN.md §8 criterion 12).

---

## Sub-task 3.10 — Integration tests: Scenario B full-exposure validation

**Intent:** Add explicit assertions for the `gateway-api / expose-all` CI leg
confirming the full four-listener topology is working.

**Expected outcomes:**
- A "Verify gateway-api full-exposure" step in `fvtest.yml` asserts:
  - `Gateway/fabric-gateway` is `Programmed=True`.
  - `HTTPRoute` for the console exists.
  - `TLSRoute` resources exist for each CA, peer, and orderer in the namespace.
  - TLS passthrough is confirmed for peer (`:7051`), orderer (`:7050`), and
    CA (`:7054`) by comparing the serving certificate at the gateway address
    against the component's `tls_cert` stored in the console.
  - Console HTTPS endpoint is TLS-terminated at the gateway (certificate CN
    differs from the CA cert / the console returns HTTP 200).
  - Full tutorial sequence completes end-to-end.

**Todo list:**
- [ ] Add a "Verify gateway-api full-exposure scenario" step to `fvtest.yml`
  conditioned on the new leg.
- [ ] Assert `kubectl wait --for=condition=Programmed gateway/fabric-gateway
  -n fabricinfra`.
- [ ] Assert `TLSRoute` resources exist for CA, peer, and orderer:
  `kubectl get tlsroute -n fabricinfra`.
- [ ] Verify peer TLS passthrough: the certificate presented at
  `<peer-host>:7051` matches the peer's `tls_cert` in the console
  (`openssl s_client -connect <host>:7051 -servername <sni>` and check
  certificate serial or subject).
- [ ] Verify orderer TLS passthrough similarly at `<orderer-host>:7050`.
- [ ] Verify CA TLS passthrough at `<ca-host>:7054`.
- [ ] Verify console HTTPS endpoint returns HTTP 200 via `curl` or
  `kubectl exec`.
- [ ] Confirm `deploy_smart_contract.sh` executes a channel join and peer query
  successfully over the gateway path (covers MIGRATION-PLAN.md §8 criterion 10).

**Relevant context:**
- Acceptance criteria 8 and 9 of MIGRATION-PLAN.md §8 define the TLS
  passthrough verification requirements.

---

## Sub-task 3.11 — Update `gateway-api-install.rst` for TLSRoute minimum version

**Intent:** Update the shared prerequisite tutorial (created in Step 2) to
document the minimum Gateway API version required when `TLSRoute` resources are
used, and explain the smooth migration path from v1.3 to v1.5+.

**Expected outcomes:**
- `docs/source/tutorials/gateway-api-install.rst` contains a new
  "Version requirements" section with the information from the version
  compatibility analysis above.
- The section clearly states:
  - Console-only (`expose_console: true`, others `false`): Gateway API v1.3+.
  - Full exposure with TLSRoute: Gateway API v1.5+ required.
  - No manifest changes are needed when upgrading from v1.3 to v1.5+ — only
    the CRD installation command changes.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Add a "Version requirements" section to
  `docs/source/tutorials/gateway-api-install.rst` citing the sources listed
  in this document's version compatibility table.
- [ ] Add the CRD installation command for v1.5+ (standard channel):
  `kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/standard-install.yaml`
  and note this replaces the experimental-channel requirement for TLSRoute.
- [ ] Add a note: users on v1.3 clusters can still use Step 2 (console HTTPRoute)
  and defer full TLSRoute support until the cluster is upgraded to v1.5+.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Version compatibility sources: listed in the §Version compatibility section
  above.
- TLSRoute promotion: standard/GA since Gateway API v1.5.

---

## Sub-task 3.12 — Tutorial: `gateway-api-endorsing-organization.rst`

**Intent:** Create the tutorial for the `endorsing_organization` role with the
full Gateway API configuration — peer gRPC `TLSRoute`, optional operations
`HTTPRoute`, optional gRPC-Web `HTTPRoute`, and CA `TLSRoute`.

**Expected outcomes:**
- New file `docs/source/tutorials/gateway-api-endorsing-organization.rst`.
- Documents all variables from MIGRATION-PLAN.md §5.7, item 3.
- Shows port usage: `:7051` for `peer_api_url`, `:7054` for `ca_api_url`,
  `:443` for operations and gRPC-Web.
- Shows the `expose_peer: false` variant for in-cluster-only peer access.
- Shows the `expose_ca: false` variant for in-cluster CA enrollment.
- States that Gateway API v1.5+ is required when `TLSRoute` resources are used.
- Verifies routes with `kubectl get tlsroute` and `kubectl get httproute`.
- Added to `toctree` in `docs/source/index.rst`.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Create `docs/source/tutorials/gateway-api-endorsing-organization.rst`.
- [ ] Reference `gateway-api-install.rst` as prerequisite, including its version
  requirements section.
- [ ] Include the exhaustive new route variables table from
  MIGRATION-PLAN.md §5.7, item 3.
- [ ] Provide example vars files for:
  - Full external exposure (`expose_peer: true`, `expose_ca: true`,
    `expose_peer_operations: false` default).
  - In-cluster only (`expose_peer: false`, `expose_ca: false`).
- [ ] Confirm the exact Service names generated by `fabric-operator` for the
  peer, gRPC-Web sidecar, and CA (verify from W6 post-task `vars:` blocks in
  MIGRATION-PLAN.md §5.6.7).
- [ ] Add to `toctree` in `docs/source/index.rst`.
- [ ] Link from `docs/source/roles/endorsing-organization.rst`.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Variable table: MIGRATION-PLAN.md §5.7, endorsing_organization section.

---

## Sub-task 3.13 — Tutorial: `gateway-api-ordering-organization.rst`

**Intent:** Create the tutorial for the `ordering_organization` role with the
full Gateway API configuration — orderer gRPC `TLSRoute`, optional operations
`HTTPRoute`, and CA `TLSRoute`.

**Expected outcomes:**
- New file `docs/source/tutorials/gateway-api-ordering-organization.rst`.
- Documents all variables from MIGRATION-PLAN.md §5.7, item 4.
- Shows port usage: `:7050` for `orderer_api_url`, `:7054` for `ca_api_url`,
  `:443` for operations.
- Shows the `expose_orderer: false` and `expose_ca: false` variants.
- States that Gateway API v1.5+ is required when `TLSRoute` resources are used.
- Verifies routes with `kubectl get tlsroute` and `kubectl get httproute`.
- Added to `toctree` in `docs/source/index.rst`.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Create `docs/source/tutorials/gateway-api-ordering-organization.rst`.
- [ ] Reference `gateway-api-install.rst` as prerequisite.
- [ ] Include the exhaustive new route variables table from
  MIGRATION-PLAN.md §5.7, item 4.
- [ ] Provide example vars files for full external and in-cluster variants.
- [ ] Confirm the exact Service names generated by `fabric-operator` for the
  orderer and CA.
- [ ] Add to `toctree` in `docs/source/index.rst`.
- [ ] Link from `docs/source/roles/ordering-organization.rst`.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Variable table: MIGRATION-PLAN.md §5.7, ordering_organization section.

---

## Sub-task 3.14 — Tutorial: `migrate-nginx-to-gateway.rst`

**Intent:** Create the migration guide for users upgrading from the nginx ingress
controller to the Kubernetes Gateway API. Covers the upgrade path, port changes,
version requirements, deprecation timeline, and rollback steps.

**Expected outcomes:**
- New file `docs/source/tutorials/migrate-nginx-to-gateway.rst`.
- Covers the deprecation timeline from MIGRATION-PLAN.md §7.
- Documents the port changes (`:32000` or `:443` → `:7051` / `:7050`; CA
  on `:7054`).
- Clearly states the minimum Gateway API version per use-case (v1.3 for
  HTTPRoute-only; v1.5+ for TLSRoute).
- Provides a step-by-step upgrade procedure for existing nginx deployments.
- Explains backwards-compatible defaults (`ingress_type: nginx` remains default
  until v2.2).
- Added to `toctree` in `docs/source/index.rst`.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Create `docs/source/tutorials/migrate-nginx-to-gateway.rst` covering:
  - Rationale for the migration (nginx deprecation; canonical port topology).
  - Version requirements table (v1.3 for console-only; v1.5+ for TLSRoute).
  - Pre-migration checklist: Gateway API controller installed, CRDs from
    standard channel (v1.5+), GatewayClass created, TLS Secret in namespace.
  - Port change table: peer `:7051`, orderer `:7050`, CA `:7054`.
  - Step-by-step: change `ingress_type` to `gateway-api`, update `api_url`
    values in vars files, run playbooks.
  - Verification steps: `kubectl get gateway`, `kubectl get httproute`,
    `kubectl get tlsroute`.
  - Rollback: revert `ingress_type` to `nginx`, restore old `api_url` values.
  - Deprecation timeline table from MIGRATION-PLAN.md §7.
- [ ] Add to `toctree` in `docs/source/index.rst`.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Deprecation timeline: MIGRATION-PLAN.md §7.
- Port change table: MIGRATION-PLAN.md §6.

---

## Sub-task 3.15 — Upstream contribution: `fabric-operator` Gateway API support

**Intent:** File a PR against `hyperledger-labs/fabric-operator` proposing native
Gateway API support so the W6 Ansible post-task overlay can eventually be replaced
by operator-native route creation. This is a tracking sub-task.

**Expected outcomes:**
- A GitHub issue or PR is filed against `hyperledger-labs/fabric-operator`.
- The PR description references this plan and the W6 overlay as the transitional
  mechanism.
- The upstream PR/issue URL is recorded below.

**Todo list:**
- [ ] Draft the proposal from MIGRATION-PLAN.md §5.6.10: `INGRESS_CLASS` env
  var, native `HTTPRoute` + `TLSRoute` emission, RBAC extension.
- [ ] File the issue or PR against `hyperledger-labs/fabric-operator`.
- [ ] Record the upstream PR/issue URL here: *(TBD after filing)*

**Relevant context:**
- Contribution scope: MIGRATION-PLAN.md §5.6.10.
- The W6 overlay in sub-tasks 3.2–3.7 remains the supported path until the
  upstream PR is merged.

---

## Acceptance criteria for Step 3

A Step 3 delivery is considered complete when all of the following pass:

1. `ansible-lint` and `yamllint` pass on all modified files.
2. All Step 1 and Step 2 acceptance criteria still pass (no regression on nginx
   legs or on the `gateway-api / console-only` leg if retained).
3. `kind_with_envoy_gateway.sh` installs Gateway API CRDs from a v1.5+ standard
   channel release; `tlsroutes.gateway.networking.k8s.io` CRD is established.
4. `fvtest.yml` includes a `gateway-api / expose-all` (Scenario B) leg that
   completes successfully end-to-end with `fail-fast: false`.
5. On the `gateway-api / expose-all` leg:
   - `Gateway/fabric-gateway` is `Programmed=True`.
   - `TLSRoute` resources exist for each CA, peer, and orderer in the namespace.
   - Peer `api_url` resolves to port 7051 with TLS passthrough confirmed.
   - Orderer `api_url` resolves to port 7050 with TLS passthrough confirmed.
   - CA `api_url` resolves to port 7054 with TLS passthrough confirmed.
   - Console HTTPS endpoint is TLS-terminated at the gateway.
   - `deploy_smart_contract.sh` executes a channel join and peer query
     successfully end-to-end (MIGRATION-PLAN.md §8 criterion 10).
6. `plugins/module_utils/url_utils.py:translate_url_to_os_format()` accepts
   `canonical_port`; existing unit tests pass; new unit tests for `:7051`
   and `:7050` pass.
7. `gateway-api-install.rst` contains a "Version requirements" section that
   correctly states v1.3 minimum for HTTPRoute-only and v1.5+ for TLSRoute,
   citing https://kubernetes.io/blog/2026/04/21/gateway-api-v1-5/ and
   https://github.com/kubernetes-sigs/gateway-api/releases.
8. All five tutorial pages exist and `make -C docs html` builds without warnings:
   - `docs/source/tutorials/gateway-api-install.rst` (updated with version section)
   - `docs/source/tutorials/gateway-api-console.rst` (from Step 2)
   - `docs/source/tutorials/gateway-api-endorsing-organization.rst`
   - `docs/source/tutorials/gateway-api-ordering-organization.rst`
   - `docs/source/tutorials/migrate-nginx-to-gateway.rst`
9. The upstream `fabric-operator` contribution issue/PR is filed and its URL
   is recorded in sub-task 3.15 above.
10. `ingress_type: nginx` path is unchanged — all nginx tests from Steps 1 and 2
    continue to pass without modification.
