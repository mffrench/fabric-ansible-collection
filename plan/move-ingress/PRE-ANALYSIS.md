# Pre-Analysis: Migrating away from ingress-nginx

## 1. Context and Driver

The `fabric-ansible-collection` currently provisions [ingress-nginx](https://github.com/kubernetes/ingress-nginx)
(`controller-v1.1.2`) as the sole Kubernetes ingress solution.
The ingress-nginx project [announced end-of-maintenance effective March 2026](https://github.com/kubernetes/ingress-nginx/issues/12272),
making migration mandatory for any deployment that will remain on a supported path.

The two realistic replacement directions are:

| Direction | Canonical reference |
|-----------|---------------------|
| **Kubernetes Gateway API** | <https://gateway-api.sigs.k8s.io/> |
| **Istio service mesh** | <https://istio.io/latest/docs/> |

The sections below examine each option against the concrete protocol requirements
of Hyperledger Fabric, audit every touch-point in this repository, and close with
a recommendation and the major concerns to address in the migration plan.

---

## 2. Hyperledger Fabric's Multi-Protocol Networking Requirements

Understanding the protocol landscape is the prerequisite for any gateway choice.
Every deployed Fabric node exposes **three distinct endpoint kinds**, each with its
own TLS and protocol characteristics.

### 2.1 Per-node endpoint types

| Endpoint | Transport | TLS model | Ingress requirement |
|----------|-----------|-----------|---------------------|
| **gRPC API** (peer / orderer) | HTTP/2 gRPC over mTLS | TLS originating inside the pod; the pod presents its own Fabric-issued TLS certificate | **TLS passthrough** — the proxy must not terminate TLS; port routing or SNI-based routing are both viable (see §2.2) |
| **gRPC-Web proxy** (`grpcweb` sidecar) | HTTP/1.1 + WebSocket upgrade | TLS terminated at the proxy | Standard HTTPS reverse-proxy (HTTP/2 not required) |
| **Operations / Health** | HTTPS REST | Pod-originated TLS | HTTPS reverse-proxy or TLS passthrough |
| **Console (Fabric Operations Console)** | HTTPS | TLS terminated at the ingress or at the pod | Standard HTTPS reverse-proxy |
| **CA (Fabric CA)** | HTTPS REST | Pod-originated TLS | Standard HTTPS reverse-proxy or TLS passthrough |

### 2.2 TLS passthrough: port routing vs SNI routing

Fabric peers and orderers use **mutual TLS (mTLS)** with certificates issued by the
organisation's own CA. The TLS handshake carries the node's identity; if a proxy
terminates and re-originates TLS it would present a different certificate, breaking
all peer-to-peer and client-to-peer mTLS chains. Every Fabric SDK (including
[`fabric-sdk-py`](../../fabric-sdk-py)) validates the TLS certificate against the
MSP's `tls_cert` field. This is non-negotiable: **the gRPC API endpoint must reach
the pod's own TLS stack intact**.

Two mechanisms can achieve this at the proxy layer:

**Port routing** — each protocol class (or even each node) is assigned a distinct
TCP port on the gateway. The proxy routes by port number alone, without inspecting
the TLS payload. No SNI inspection is required. This is entirely viable in both
Gateway API (via multiple `Gateway` listeners) and Istio (via dedicated gateway
ports). The practical constraint is that clients must encode the port in the
`api_url`; the current collection already does this (all `api_url` samples use
`:32000` or `:443`), so adopting e.g. `:7051` for all gRPC passthrough traffic is
a straightforward URL change.

**SNI routing** — all nodes share the same TCP port (typically 443). The proxy
inspects the SNI hostname in the TLS `ClientHello` (which is transmitted in the
clear before the handshake completes) to select the backend, then forwards the
raw TLS stream without terminating it. This is what ingress-nginx implements today
via `--enable-ssl-passthrough` + virtual-host matching.

The two mechanisms are **complementary rather than exclusive**:

| Scenario | Routing mechanism needed |
|----------|--------------------------|
| One port per node (e.g. peer1 :7051, peer2 :7052) | Port only — no SNI needed |
| One shared port per protocol class (e.g. all gRPC on :7051, all HTTPS on :443), multiple nodes per class | Port selects the passthrough listener; SNI distinguishes nodes within that listener |
| All nodes on the same port :443 (current topology) | SNI alone, as ingress-nginx does today |

The migration plan should choose the **shared-port-per-protocol-class** model
(port 443 for HTTPS, port 7051 for gRPC passthrough). This separates protocols
cleanly, keeps the number of exposed ports bounded regardless of node count, and
still uses SNI only within the passthrough listener to distinguish individual nodes
— which both Gateway API `TLSRoute` and Istio `VirtualService` support natively.

### 2.3 The `grpcwp_url` / gRPC-Web distinction

The Ansible modules track two separate URLs per peer and per orderer node:

* `api_url` — raw gRPC (TLS passthrough path), e.g. `grpcs://org1peer-api.example.org:32000`
* `grpcwp_url` — gRPC-Web proxy (normal HTTPS path), e.g. `https://org1peer-grpcwebproxy.example.org:32000`

See [`plugins/module_utils/peers.py`](../../plugins/module_utils/peers.py#L30) and
[`plugins/module_utils/ordering_services.py`](../../plugins/module_utils/ordering_services.py#L27).

The gRPC-Web sidecar image is `ghcr.io/hyperledger-labs/grpc-web` and is embedded
in the `IBPPeer` / `IBPOrderer` CRD spec via the `console_versions` map
([`fabric_console/defaults/main.yml`](../../roles/fabric_console/defaults/main.yml#L68)).
The ingress for the gRPC-Web proxy **can** be a normal HTTP/2-capable reverse-proxy
on the HTTPS listener.

---

## 3. Current ingress-nginx Integration — Complete Touch-point Audit

| File | Role | What must change |
|------|------|-----------------|
| [`roles/fabric_operator_crds/templates/k8s/ingress/kustomization.yaml`](../../roles/fabric_operator_crds/templates/k8s/ingress/kustomization.yaml) | Installs ingress-nginx v1.1.2 from upstream kustomize ref | Replace entirely |
| [`roles/fabric_operator_crds/templates/k8s/ingress/ingress-nginx-controller.yaml`](../../roles/fabric_operator_crds/templates/k8s/ingress/ingress-nginx-controller.yaml) | Adds `--enable-ssl-passthrough` patch | Replace entirely |
| [`roles/fabric_operator_crds/templates/k8s/coredns/coredns.yaml.j2`](../../roles/fabric_operator_crds/templates/k8s/coredns/coredns.yaml.j2) | Rewrites `*.localho.st` → `host.ingress.internal` pointing at the nginx ClusterIP | The target ClusterIP / Service reference must change |
| [`roles/fabric_operator_crds/defaults/main.yml`](../../roles/fabric_operator_crds/defaults/main.yml#L46) | `ingress_domain: localho.st` default | Probably stays; depends on replacement controller's LoadBalancer IP shape |
| [`roles/fabric_operator_crds/templates/k8s/rbac/hlf-operator-clusterrole.yaml`](../../roles/fabric_operator_crds/templates/k8s/rbac/hlf-operator-clusterrole.yaml#L182) | Grants the operator `get/create/…` on `networking.k8s.io/ingresses` | Must be extended to include Gateway API resource groups (`gateway.networking.k8s.io`) or Istio CRDs |
| [`roles/hlfsupport_console/templates/k8s/cluster_role.yml.j2`](../../roles/hlfsupport_console/templates/k8s/cluster_role.yml.j2#L168) | Same RBAC gap for `hlfsupport` variant | Same extension required |
| [`roles/hlfsupport_console/tasks/k8s/create.yml`](../../roles/hlfsupport_console/tasks/k8s/create.yml#L146) | Waits on `networking.k8s.io/v1 Ingress` resources to appear | Must be adapted for `HTTPRoute` / Istio `VirtualService` depending on choice |
| [`.github/scripts/kind_with_nginx.sh`](../../.github/scripts/kind_with_nginx.sh) | CI: provisions KIND + nginx from `fabric-operator.git/config/ingress/kind` + CoreDNS override | Must be replaced with equivalent CI bootstrap script |
| [`docs/source/tutorials/oss-installing.rst`](../../docs/source/tutorials/oss-installing.rst#L40) | Advises configuring nginx ALB SSL passthrough on IKS | Documentation must reflect new gateway |
| [`docs/source/tutorials/hlfsupport-installing.rst`](../../docs/source/tutorials/hlfsupport-installing.rst#L44) | Same IKS/nginx advisory | Same documentation update |
| [`docs/source/roles/fabric-operator-crds.rst`](../../docs/source/roles/fabric-operator-crds.rst#L23) | States "this role does not install an ingress controller" | Update to mention Gateway API / Istio |
| [`docs/source/roles/fabric-console.rst`](../../docs/source/roles/fabric-console.rst#L23) | Same statement | Same update |

Additionally, the `fabric-operator` upstream project is referenced at install time:

```
kubectl apply -k https://github.com/hyperledger-labs/fabric-operator.git/config/ingress/kind
```

That kustomize path also lives upstream; any replacement strategy must either wait
for or contribute a Gateway API / Istio equivalent in that repository.

---

## 4. Option A — Kubernetes Gateway API

### 4.1 What it is

The [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/) (`gateway.networking.k8s.io`)
is the SIG-Network successor to `networking.k8s.io/Ingress`. It is GA as of v1.0
(December 2023) and is built into Kubernetes 1.28+. It separates concerns across
three resource levels: `GatewayClass` (infrastructure), `Gateway` (instance),
`HTTPRoute` / `TLSRoute` / `TCPRoute` (application traffic).

A `Gateway` resource carries **multiple independent listeners**, each with its own
port, protocol mode, and TLS configuration. This makes port-based protocol
segregation a first-class concept in the API itself — not an implementation detail
of any particular controller.

### 4.2 Fit for Fabric

| Requirement | Gateway API support | Notes |
|-------------|--------------------|----|
| TLS passthrough (gRPC mTLS) | ✅ `TLSRoute` with `mode: Passthrough` on a dedicated listener | Requires a conformant implementation that supports `TLSRoute`; not all do |
| Port-based protocol segregation | ✅ Multiple listeners on the same `Gateway` | e.g. `:443 HTTPS` + `:7051 TLS Passthrough` on one `Gateway` object |
| HTTP/2 gRPC-Web proxy | ✅ `HTTPRoute` with an HTTP/2-capable implementation | Straightforward |
| HTTPS console | ✅ `HTTPRoute` | Straightforward |
| SNI-based hostname routing within a passthrough listener | ✅ Native in `TLSRoute` via `sniHosts` | Core feature of the API |
| Multi-org multi-namespace isolation | ✅ `ReferenceGrant` | Allows cross-namespace routing |
| Wildcard hostname matching | ✅ (GA in v1.1) | Works for `*.localho.st`-style development domains |

A representative `Gateway` configuration for Fabric would look like:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: fabric-gateway
spec:
  gatewayClassName: eg   # e.g. Envoy Gateway
  listeners:
    - name: https          # Console, CA, gRPC-Web — TLS terminated here
      port: 443
      protocol: HTTPS
      tls:
        mode: Terminate
        certificateRefs:
          - name: fabric-tls-secret
    - name: grpc-passthrough   # Peer/orderer gRPC API — TLS NOT touched
      port: 7051
      protocol: TLS
      tls:
        mode: Passthrough
```

`HTTPRoute` resources bind to the `https` listener; `TLSRoute` resources bind to
the `grpc-passthrough` listener and use `sniHosts` to select individual node
backends. This is structurally identical to the Istio approach described in §5.

**Key constraint:** `TLSRoute` is still a **beta** resource in Gateway API v1.1,
and only some implementations support it today.
Implementations with confirmed passthrough support include:

* **Envoy Gateway** (v1.0+, CNCF project)
* **Contour** (v1.28+)
* **NGINX Gateway Fabric** — a new Gateway API–native NGINX project (distinct from ingress-nginx)

Cloud-managed controllers (AWS ALB, GKE Gateway, Azure AG) do **not** yet support
`TLSRoute passthrough` mode.

### 4.3 Migration footprint

A Gateway API migration would produce:

1. **A `GatewayClass` + `Gateway`** manifest with two listeners (`:443 HTTPS` and
   `:7051 TLS Passthrough`), replacing `kustomization.yaml` +
   `ingress-nginx-controller.yaml`, parameterised with `ingress_domain`.
2. **`TLSRoute` resources** for the raw gRPC `api_url` endpoints — generated or
   applied by the `fabric-operator` when it creates `IBPPeer` / `IBPOrderer`
   objects. This requires either an upstream change to the operator or a
   post-creation Ansible task that creates these routes.
3. **`HTTPRoute` resources** for the console, gRPC-Web proxy, CA, and Operations
   endpoints.
4. **Updated CoreDNS** `ConfigMap` pointing at the new Gateway's ClusterIP.
5. **Updated RBAC** to grant the operator `gateway.networking.k8s.io` permissions.
6. **`api_url` port change** in tutorial vars and documentation from `:443` / `:32000`
   to `:7051` for gRPC passthrough endpoints (see §8.6).

### 4.4 Dependency on fabric-operator

The `fabric-operator` currently creates `networking.k8s.io/v1 Ingress` objects
internally when it reconciles `IBPPeer`, `IBPOrderer`, `IBPCA`, and `IBPConsole`
resources. Switching to Gateway API requires the operator to create `HTTPRoute` and
`TLSRoute` objects instead. This is **not yet implemented upstream**. Two
strategies exist:

* **Wait / contribute upstream:** propose a PR to `fabric-operator` adding
  Gateway API support behind a feature flag.
* **Post-reconciliation overlay:** after the operator creates its legacy `Ingress`
  objects, an Ansible post-task translates them into Gateway API routes and annotates
  the `Ingress` to be ignored. This is fragile but avoids blocking on the operator.

### 4.5 Pros

* Kubernetes-native, no additional runtime dependencies beyond the chosen implementation.
* Port-based protocol segregation and `TLSRoute passthrough` are both first-class
  concepts in the API — no asymmetry with Istio on this dimension.
* `TLSRoute passthrough` is semantically explicit and purpose-built for this scenario.
* Broad community adoption; likely to become the universal standard.
* Multi-tenancy model (ReferenceGrant) fits multi-org Fabric topologies cleanly.
* Low runtime footprint: gateway pods only, no per-pod sidecars.

### 4.6 Cons

* `TLSRoute` is still beta; limited implementation choice.
* Requires operator-side changes to replace `Ingress` with `HTTPRoute` / `TLSRoute`.
* No single "cloud-neutral" implementation handles all Fabric protocols today.

---

## 5. Option B — Istio Service Mesh

### 5.1 What it is

[Istio](https://istio.io/) is a CNCF-graduated service mesh that provides traffic
management, mTLS between pods, and observability. Its ingress gateway
(`istio-ingressgateway`) is a hardened Envoy proxy that supports port-level
routing, SNI-based passthrough, and HTTP/2 natively.

### 5.2 Fit for Fabric

| Requirement | Istio support | Notes |
|-------------|--------------|-------|
| TLS passthrough (gRPC mTLS) | ✅ `Gateway` + `VirtualService` with `tls.mode: PASSTHROUGH` | First-class; battle-tested in production Fabric deployments |
| Port-based protocol segregation | ✅ Dedicated ports on the Istio `Gateway` resource | Same model as Gateway API §4.2 — `:443 HTTPS` + `:7051 TLS` |
| HTTP/2 gRPC-Web proxy | ✅ `VirtualService` with `match.uri.prefix` | Istio natively understands gRPC traffic |
| HTTPS console | ✅ `VirtualService` with TLS termination at the gateway | |
| SNI-based hostname routing within a passthrough listener | ✅ Built-in; `tls.match.sniHosts` | |
| Mesh-wide mTLS between pods | ✅ `PeerAuthentication` policy | Bonus: secures pod-to-pod traffic automatically |
| Observability (tracing, metrics) | ✅ Envoy telemetry built in | Useful for Fabric ops |
| Multi-namespace multi-org | ✅ `Sidecar` + `AuthorizationPolicy` | Fine-grained; maps well to Fabric MSP isolation |

### 5.3 Migration footprint

1. **Istio installation** (`istioctl install` or the Istio Operator CRD) — a
   significant new dependency (~300 MB of control-plane containers).
2. **Namespace labelling** `istio-injection=enabled` on the HLF namespace.
3. **`Gateway` resource** (Istio kind, not Gateway API kind) with dedicated ports:
   - port 443 / `HTTPS` for console and CA (TLS termination)
   - port 7051 / `TLS PASSTHROUGH` for gRPC API
4. **`VirtualService` resources** per component:
   - `sniHosts` match for gRPC API passthrough on the `:7051` listener
   - `route` with rewrite/header manipulation for console and gRPC-Web on `:443`
5. **Sidecar injection** in the HLF operator namespace — Envoy sidecars are injected
   into every pod, which can interfere with Fabric's own TLS if `STRICT` mTLS mode
   is set without exemptions.
6. **Updated RBAC** for `networking.istio.io` API groups.
7. **Updated CoreDNS** pointing at `istio-ingressgateway`'s ClusterIP.

### 5.4 Key pitfall: Istio mTLS vs Fabric mTLS

Istio's data-plane enforces its own mTLS between pods via Envoy sidecars. Fabric
also enforces mTLS between its components using certificates issued by Fabric CA.
These are independent trust chains. Running both simultaneously without careful
`PeerAuthentication` policy (`mode: PERMISSIVE` or explicit `DISABLE` for Fabric
ports) causes connection failures that are difficult to diagnose. This is the
**single most important operational concern** with the Istio path.

### 5.5 Pros

* Port-level routing elegantly separates gRPC mTLS passthrough from HTTPS
  reverse-proxy traffic — the same model available in Gateway API, but more mature.
* Istio `VirtualService` is stable and widely deployed in production Fabric
  environments (e.g. AAIS, Walmart's Fabric deployments).
* Built-in mutual authentication, traffic policy, and circuit breaking.
* Aligns with the long-term direction of Kubernetes: Istio now supports the
  Kubernetes Gateway API as its configuration front-end (ambient mode / waypoint proxies).

### 5.6 Cons

* **Heavy dependency**: Istio adds a significant control-plane footprint.
* **Complexity**: sidecar injection + Fabric TLS requires careful exemption policy.
* Not Kubernetes-native API (vendor-specific CRDs, though CNCF-graduated).
* Ambient mode (Istio's sidecarless future) is still beta; today's architecture
  uses sidecars that add latency and memory pressure on busy Fabric nodes.

---

## 6. Comparative Summary

| Criterion | Gateway API (Envoy Gateway / NGF) | Istio |
|-----------|----------------------------------|-------|
| **TLS passthrough** | ✅ `TLSRoute` (beta resource) | ✅ `Gateway tls.PASSTHROUGH` (stable) |
| **Port-based protocol segregation** | ✅ Multiple listeners on one `Gateway` | ✅ Dedicated ports on Istio `Gateway` |
| **Protocol awareness** | Limited (port / SNI only at gateway) | High (L7 gRPC + L4 TLS awareness) |
| **Operator-side changes needed** | Yes — operator must emit `HTTPRoute`/`TLSRoute` | Yes — operator must emit `VirtualService`/`DestinationRule` |
| **Kubernetes-native API** | ✅ | ❌ (proprietary CRDs, CNCF-standard) |
| **Runtime weight** | Low (gateway pods only, no sidecars) | High (control-plane + sidecar per pod) |
| **Production Fabric deployments** | Limited examples today | Several well-documented |
| **SNI within passthrough listener** | ✅ `TLSRoute sniHosts` | ✅ `VirtualService tls.match.sniHosts` |
| **mTLS complexity** | None (no mesh mTLS) | ⚠ Must be tuned to avoid conflict with Fabric mTLS |
| **Long-term trajectory** | Standard, operator will adopt eventually | Istio now implements Gateway API; convergence expected |
| **CI/CD bootstrap simplicity** | Moderate | Complex |

Both options provide **identical routing capability** for Fabric's protocol
requirements (port segregation + SNI passthrough). The differentiating factors are
runtime weight, mTLS conflict risk, and API standardisation.

---

## 7. Recommendation

**Primary recommendation: Kubernetes Gateway API with Envoy Gateway as the implementation.**

Rationale:
1. Port-based protocol segregation and `TLSRoute passthrough` cover all Fabric
   routing requirements without introducing a mesh control-plane.
2. Envoy Gateway is a CNCF project with Gateway API–conformant `TLSRoute` support,
   a small footprint, and an active community.
3. Kubernetes Gateway API is the direction the Kubernetes community has chosen; the
   `fabric-operator` upstream will inevitably move there as `networking.k8s.io/Ingress`
   is eventually deprecated.
4. No risk of double-mTLS conflict between Istio and Fabric TLS chains.
5. No per-pod sidecar overhead on Fabric nodes.
6. The migration surface in this collection is well-contained (see §3).

**Secondary / longer-term option: Istio** — appropriate if the deployment already
runs an Istio mesh for other workloads, or if the full observability and
fine-grained traffic-policy features of a service mesh are desired.
Istio's Gateway API compatibility layer means the two paths converge over time.

---

## 8. Major Concerns to Address in the Migration Plan

### 8.1 Upstream fabric-operator Gateway API support (blocking)

The `fabric-operator` reconciler creates `networking.k8s.io/v1 Ingress` objects
when it provisions `IBPPeer`, `IBPOrderer`, `IBPCA`, and `IBPConsole`. Without an
upstream change, `HTTPRoute` and `TLSRoute` objects will not be created
automatically. **The plan must either:**
- Track / contribute an upstream PR to `fabric-operator` adding Gateway API support
  (a feature flag `INGRESS_CLASS=gateway` environment variable, analogous to the
  existing `CLUSTERTYPE` env var), **or**
- Implement an Ansible post-task that reads the operator-created `Ingress` objects
  and synthesises equivalent `HTTPRoute` / `TLSRoute` resources (a transitional
  approach that accumulates technical debt).

### 8.2 TLSRoute stability and implementation selection

`TLSRoute` is a beta resource in Gateway API v1.1. The collection must **pin a
specific Gateway API version** and a specific implementation (e.g. Envoy Gateway
v1.x) to ensure `TLSRoute` is available. The kustomize install reference
(currently pinned to `controller-v1.1.2` of ingress-nginx) must be updated to a
stable Envoy Gateway release tag. The CI script
[`kind_with_nginx.sh`](../../.github/scripts/kind_with_nginx.sh) must be
completely rewritten as `kind_with_envoy_gateway.sh` (or equivalent).

### 8.3 RBAC extension for the operator

The `ClusterRole` in
[`hlf-operator-clusterrole.yaml`](../../roles/fabric_operator_crds/templates/k8s/rbac/hlf-operator-clusterrole.yaml#L182)
currently grants `networking.k8s.io/ingresses`. It must be extended to include
`gateway.networking.k8s.io` resources:
`gateways`, `httproutes`, `tlsroutes`, `referencegrants`.
The same applies to the `hlfsupport_console` cluster role template.

### 8.4 CoreDNS wildcard override

The CoreDNS `ConfigMap`
([`coredns.yaml.j2`](../../roles/fabric_operator_crds/templates/k8s/coredns/coredns.yaml.j2))
rewrites `*.localho.st` to the ingress-nginx `ClusterIP`. This ClusterIP is
obtained at runtime from `kubectl -n ingress-nginx get svc ingress-nginx-controller`.
For the replacement, the equivalent Service reference will be in a different
namespace and have a different name (e.g. `envoy-gateway-system` namespace,
`envoy-gateway` service). The Jinja2 template and the Ansible task that populates
`clusterip` must be updated.

### 8.5 `IBPConsole` Ingress wait logic

[`hlfsupport_console/tasks/k8s/create.yml`](../../roles/hlfsupport_console/tasks/k8s/create.yml#L146)
waits for a `networking.k8s.io/v1 Ingress` resource to appear and reads the
console URL from its `spec.rules[0].host`. Under Gateway API the console URL will
be found on an `HTTPRoute` object. The wait task and URL extraction logic must be
rewritten (or made conditional on `ingress_type`).

### 8.6 Port topology decision and `api_url` format

This is an **architectural decision** that ripples through every URL in the collection.

The recommended model (§2.2) exposes two listeners on one `Gateway`:

| Listener | Port | Protocol | Serves |
|----------|------|----------|--------|
| `https` | 443 | `HTTPS` (TLS terminate) | Console, CA, gRPC-Web proxy, Operations |
| `grpc-passthrough` | 7051 | `TLS` (Passthrough) | All peer and orderer gRPC API endpoints |

Under this model, all `api_url` values change from their current port (`:443` or
`:32000` in samples) to `:7051`. The `grpcwp_url` and `operations_url` values
remain on `:443`. This affects:

- Tutorial vars files (`ordering-org-vars.yml`, `org1-vars.yml`, `org2-vars.yml`)
- Integration test fixtures (`one_node_ordering_service.json.j2`)
- All module documentation samples in `plugins/modules/*.py`
- The `channel_consenters.py` and `channel_config.py` modules which parse the port
  directly from `api_url` (see [`channel_consenters.py`](../../plugins/modules/channel_consenters.py#L168))

An alternative is to keep all endpoints on `:443` and rely purely on SNI within a
single passthrough listener — preserving the current URL format at the cost of
losing the clean protocol separation. The plan must make this choice explicit.

### 8.7 Ansible variable abstraction (`ingress_type`)

Today, `ingress_domain` is the only ingress-related variable. A new variable
(e.g. `ingress_type: nginx | gateway-api | istio`) should be introduced to allow
conditional role paths and to preserve backwards compatibility during the
transition. Existing users on nginx must not be broken immediately; the nginx
path should be deprecated gracefully.

### 8.8 Documentation and tutorial refresh

Every occurrence of "ingress controller", "nginx", "SSL passthrough", and
`kubectl get ingress` in the documentation must be reviewed:
- [`docs/source/tutorials/oss-installing.rst`](../../docs/source/tutorials/oss-installing.rst)
- [`docs/source/tutorials/hlfsupport-installing.rst`](../../docs/source/tutorials/hlfsupport-installing.rst)
- [`docs/source/roles/fabric-operator-crds.rst`](../../docs/source/roles/fabric-operator-crds.rst)
- [`docs/source/roles/fabric-console.rst`](../../docs/source/roles/fabric-console.rst)

New sections explaining Gateway API concepts (`GatewayClass`, `TLSRoute`) and the
local development setup with `localho.st` must be written.

### 8.9 CI pipeline parity

The GitHub Actions workflow relies on
[`kind_with_nginx.sh`](../../.github/scripts/kind_with_nginx.sh).
A replacement CI bootstrap must:
1. Install KIND with port mappings for `:443` and `:7051`.
2. Install Envoy Gateway (or chosen implementation).
3. Apply `GatewayClass` + `Gateway` manifests with both listeners.
4. Apply the CoreDNS override pointing at the new gateway's ClusterIP.
5. Validate that `TLSRoute` passthrough is functional before running integration tests.

### 8.10 Compatibility with OpenShift

OpenShift uses `route.openshift.io/Route` rather than `Ingress`. The OpenShift
path of the collection is currently handled separately; Gateway API on OpenShift
requires OpenShift Service Mesh (Istio-based) or Red Hat's Gateway API
implementation. The migration plan must explicitly state whether OpenShift support
is in scope for the first iteration.
