# Kubernetes Gateway API — Implementation Comparison

> **Scope:** This document compares every major Kubernetes Gateway API
> implementation against Hyperledger Fabric's specific routing requirements
> (TLS passthrough on dedicated ports, HTTPS reverse-proxy, SNI-based routing)
> and concludes with a recommendation for CI / PoC vs production use.
>
> It is a companion to `PRE-ANALYSIS.md` §4 and supersedes the short list of
> implementations that appears there.

---

## 1. Fabric's Hard Requirements from the Gateway API

Any implementation must satisfy **all three** of these to be usable:

| # | Requirement | Gateway API resource | Why it matters |
|---|-------------|----------------------|----------------|
| R1 | TLS passthrough on a dedicated port (`:7050`, `:7051`) | `TLSRoute` with `mode: Passthrough` on a `TLS` protocol listener | Fabric nodes present their own mTLS certificate; no proxy termination is acceptable |
| R2 | SNI-based backend selection within the passthrough listener | `TLSRoute.spec.hostnames` (sniHosts) | Multiple peers / orderers share the same passthrough port |
| R3 | HTTPS reverse-proxy with TLS termination | `HTTPRoute` on an `HTTPS` protocol listener | Console, CA, gRPC-Web proxy |

All three are Standard-channel (GA) resources as of Gateway API v1.5. Any
conformant implementation must support them.

---

## 2. Implementation Landscape

### 2.1 Self-managed (install into any cluster)

#### Envoy Gateway
- **Maintained by:** CNCF project, backed by Tetrate, Ambassador, and others
- **Data plane:** Envoy Proxy
- **Gateway API conformance:** Extended conformance; `TLSRoute` supported since v1.0
- **`TLSRoute` GA (v1):** ✅ v1.3+
- **Installation footprint:** ~2 pods (gateway controller + Envoy proxy pods per `Gateway`)
- **Helm install:** `helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.3.0`
- **KIND-friendly:** ✅ works out of the box with host-port mappings

**Pros**
- Smallest footprint of all Envoy-based solutions
- No additional CRDs beyond the Gateway API standard set
- Straightforward configuration model: one `Gateway` + `HTTPRoute`/`TLSRoute` resources, nothing else
- Active CNCF project with rapid release cadence
- Excellent conformance test results (one of the highest-scoring implementations)

**Cons**
- Relatively young project (v1.0 released 2024); less battle-tested than Istio in large production deployments
- Advanced traffic policies (rate limiting, circuit breaking) require proprietary `EnvoyProxy` / `BackendTrafficPolicy` CRDs — acceptable for Fabric which does not need them

**CI / PoC verdict:** ✅ **Recommended** — lowest footprint, fastest to bootstrap, full `TLSRoute` support, no extra CRDs needed for Fabric's use case.

---

#### NGINX Gateway Fabric (NGF)
- **Maintained by:** F5 / NGINX, Inc.
- **Data plane:** NGINX (open-source)
- **Gateway API conformance:** Core + Extended; `TLSRoute` supported since v1.4
- **`TLSRoute` GA (v1):** ✅ v1.4+
- **Installation footprint:** ~2 pods (controller + nginx proxy)
- **Helm install:** `helm install ngf oci://ghcr.io/nginx/charts/nginx-gateway-fabric --version 2.x`
- **KIND-friendly:** ✅

**Pros**
- NGINX data plane will be familiar to teams already running ingress-nginx
- Purpose-built for Gateway API; clean break from the ingress-nginx legacy
- Good conformance score; `TLSRoute` passthrough confirmed

**Cons**
- Younger than Envoy-based solutions for Gateway API use (ingress-nginx heritage is not reused)
- NGINX's `stream` module handles L4 passthrough — functional but less observable than Envoy's telemetry
- Rate of conformance test passes slightly behind Envoy Gateway

**CI / PoC verdict:** ✅ Viable — familiar data plane for NGINX users, very similar footprint to Envoy Gateway. Second choice if the team prefers NGINX.

---

#### Contour
- **Maintained by:** VMware / Broadcom, CNCF project
- **Data plane:** Envoy Proxy (like Envoy Gateway, but with a different control-plane model)
- **Gateway API conformance:** Core + Extended; `TLSRoute` supported since v1.28 (Contour release, not k8s version)
- **`TLSRoute` GA (v1):** ✅ v1.28+
- **Installation footprint:** ~2 pods (contour controller + envoy daemonset or deployment)
- **KIND-friendly:** ✅

**Pros**
- Mature project with a large production user base
- Same Envoy data plane as Envoy Gateway — comparable observability and performance
- Supports both `networking.k8s.io/Ingress` and Gateway API simultaneously (useful during a transition)

**Cons**
- Larger install surface than Envoy Gateway (contour-specific CRDs like `HTTPProxy` in addition to Gateway API)
- The dual-API support adds cognitive overhead; Gateway API configuration is a secondary concern for many Contour operators
- Control-plane model differs from Envoy Gateway; requires more configuration to achieve the same result

**CI / PoC verdict:** ⚠️ Acceptable but heavier than necessary for Fabric's use case. The extra Contour CRDs add noise.

---

#### HAProxy Ingress
- **Maintained by:** HAProxy Technologies
- **Data plane:** HAProxy
- **Gateway API conformance:** Core only; `TLSRoute` support is partial/experimental
- **`TLSRoute` GA (v1):** ❌ Not yet confirmed as of April 2026
- **KIND-friendly:** ✅

**Cons for Fabric:** Does not reliably support `TLSRoute` passthrough (R1). **Not recommended.**

---

### 2.2 Istio — Gateway API implementation

This is the key addition to the analysis. Istio now implements the Kubernetes
Gateway API in **two distinct modes**; both must be understood.

#### Mode A: Istio with Gateway API as configuration front-end (sidecar mode)

Since Istio v1.16, Istio can be configured using Kubernetes Gateway API resources
(`gateway.networking.k8s.io/Gateway`, `HTTPRoute`, `TLSRoute`) **instead of**
its own `networking.istio.io/VirtualService` + `networking.istio.io/Gateway` CRDs.
The data plane remains Envoy sidecars injected into every pod.

- **`TLSRoute` GA (v1):** ✅ Istio v1.21+
- **Installation footprint:** Istiod control plane (~1 pod) + Envoy sidecar in **every Fabric pod** + ingress gateway pods
- **KIND-friendly:** ✅ but heavy

**Pros**
- Standard Gateway API surface: `GatewayClass`, `Gateway`, `HTTPRoute`, `TLSRoute` — the Ansible templates written for Envoy Gateway will work unchanged with Istio
- Full service mesh capabilities (mTLS between pods, observability, circuit breaking) come for free
- Production-proven at scale

**Cons for Fabric**
- **Sidecar injection conflict with Fabric mTLS** (documented in `PRE-ANALYSIS.md` §5.4): Istio injects Envoy sidecars that intercept pod-level traffic. Fabric's own mTLS runs inside the pod. Without careful `PeerAuthentication` policy exemptions, the two TLS stacks conflict silently
- **Heaviest footprint** of all options: istiod + one sidecar per Fabric pod (peer, orderer, CA, console, grpcweb) — typically 6–10 extra containers in a minimal network
- `GATEWAY_API_VERSION` and `ISTIO_VERSION` must be kept in sync; the Gateway API support in Istio sometimes lags behind the spec's GA promotion by one minor version

**CI / PoC verdict:** ❌ **Not recommended for CI/PoC** — the sidecar footprint and mTLS conflict risk make it the highest-cost option to bootstrap and debug.

---

#### Mode B: Istio Ambient mode with Waypoint proxies

Istio's ambient mode (stable in Istio v1.22+) removes per-pod sidecars entirely.
Traffic interception is handled at the node level (ztunnel DaemonSet) with
optional per-workload Waypoint proxies for L7 policy. It also implements the
Kubernetes Gateway API.

- **`TLSRoute` support:** ✅ via Waypoint proxies
- **Installation footprint:** ztunnel DaemonSet (1 pod per node) + Waypoint proxy pods (1 per namespace or workload) — significantly lighter than sidecar mode
- **KIND-friendly:** ✅ since Istio v1.22

**Pros over sidecar mode**
- No per-pod sidecar injection → no conflict with Fabric's pod-level TLS
- Lower memory and CPU overhead per Fabric node
- Same standard Gateway API surface

**Cons**
- Ambient mode is still relatively new (stable since ~2025); community maturity is behind sidecar mode
- ztunnel's L4 traffic interception can still interfere with Fabric's raw TLS connections in edge cases; testing required
- Installation complexity is higher than Envoy Gateway

**CI / PoC verdict:** ⚠️ Interesting longer-term option if the deployment already uses Istio ambient mode; not the simplest path for a standalone Fabric CI environment.

---

### 2.3 Cloud-managed implementations

| Provider | Implementation | `TLSRoute` passthrough | Notes |
|---|---|---|---|
| **GKE** | GKE Gateway (Google Cloud Load Balancer) | ❌ Not supported | GLB cannot forward raw TLS without termination |
| **AWS** | AWS Gateway API Controller (ALB) | ❌ Not supported | ALB terminates TLS |
| **Azure** | Azure Application Gateway for Containers | ❌ Not supported as of April 2026 | Preview feature; no passthrough |
| **Cilium** | Cilium Gateway API (eBPF) | ⚠️ Partial — `TLSRoute` supported in Cilium v1.16+ but passthrough is limited to same-node scenarios in some configurations | Suitable for clusters already running Cilium CNI |

Cloud-managed implementations are not suitable for Fabric's gRPC passthrough
requirement at this time. The standard approach for Fabric on cloud Kubernetes is
to use a self-managed controller (Envoy Gateway or NGF) running alongside the
cloud provider's load balancer (which only handles external routing to the cluster).

---

## 3. Conformance Matrix

The Gateway API project maintains official conformance test results at
<https://gateway-api.sigs.k8s.io/implementations/>. The table below summarises
the relevant scores against Gateway API v1.5:

| Implementation | Core | Extended | `TLSRoute` | `TLSRoute` passthrough | Suitable for Fabric |
|---|---|---|---|---|---|
| **Envoy Gateway v1.3** | ✅ | ✅ | ✅ GA | ✅ | ✅ |
| **NGINX Gateway Fabric v2.x** | ✅ | ✅ | ✅ GA | ✅ | ✅ |
| **Contour v1.28** | ✅ | ✅ | ✅ GA | ✅ | ✅ |
| **Istio v1.22 (sidecar)** | ✅ | ✅ | ✅ GA | ✅ | ⚠️ mTLS conflict risk |
| **Istio v1.22 (ambient)** | ✅ | ✅ | ✅ GA | ✅ | ⚠️ newer, less tested |
| **Cilium v1.16** | ✅ | Partial | ⚠️ limited passthrough | ⚠️ | ⚠️ CNI-dependent |
| **GKE Gateway** | ✅ | Partial | ❌ | ❌ | ❌ |
| **AWS ALB Controller** | ✅ | Partial | ❌ | ❌ | ❌ |
| **Azure AGFC** | ✅ | Partial | ❌ | ❌ | ❌ |

---

## 4. CI / PoC Recommendation

### 4.1 Decision

**Use Envoy Gateway for CI and PoC.**

Rationale:

1. **Smallest footprint** — 2 pods total (controller + proxy); adds ~50 MB RAM to the KIND cluster. Compared to Istio's minimum of istiod + ztunnel DaemonSet + Waypoints, this is an order of magnitude lighter.
2. **No CRDs beyond the Gateway API standard** — `GatewayClass`, `Gateway`, `HTTPRoute`, `TLSRoute` are the only resources needed. There are no Envoy-specific CRDs required for Fabric's use case. This means the Ansible templates are **100% portable** to any other conformant implementation.
3. **Zero mTLS conflict risk** — Envoy Gateway does not inject sidecars; Fabric pods are untouched.
4. **Gateway API portability guarantee** — because the collection uses only standard Gateway API resources, users deploying to production with Istio, Contour, or NGF can substitute their preferred implementation simply by changing the `GatewayClass` name. No template changes are needed.
5. **Fastest bootstrap** — single Helm command; no DaemonSets, no namespace labelling, no admission webhooks.
6. **Highest conformance score** — Envoy Gateway consistently achieves the highest pass rate in the official Gateway API conformance test suite.

### 4.2 Production portability

The key principle is: **the collection's Ansible templates use only standard Gateway API resources**. The `GatewayClass` name is the only implementation-specific element, and it is a variable:

```yaml
# roles/fabric_operator_crds/defaults/main.yml
gateway_class_name: fabric-envoy-gateway   # override for Istio: istio, for NGF: nginx
```

A user running Istio in production sets `gateway_class_name: istio` and gets
identical routing behaviour. The `TLSRoute` and `HTTPRoute` manifests are byte-for-byte the same regardless of which conformant implementation is underneath.

### 4.3 Recommendation table

| Context | Recommended implementation | `GatewayClass` name |
|---|---|---|
| **CI / KIND / PoC** | Envoy Gateway v1.3 | `fabric-envoy-gateway` |
| **Production (no existing mesh)** | Envoy Gateway or NGINX Gateway Fabric | `fabric-envoy-gateway` / `nginx` |
| **Production (Istio sidecar mesh already present)** | Istio v1.22+ Gateway API mode | `istio` |
| **Production (Istio ambient mesh already present)** | Istio v1.22+ ambient Gateway API mode | `istio` |
| **Production (Cilium CNI already present)** | Cilium Gateway API (verify `TLSRoute` passthrough for your version) | `cilium` |
| **GKE / EKS / AKS** | Self-managed Envoy Gateway or NGF deployed alongside the cloud LB | `fabric-envoy-gateway` / `nginx` |

### 4.4 Impact on `kind_with_envoy_gateway.sh`

The bootstrap script is correct as written in `MIGRATION-PLAN.md` §5.2. One
variable should be added to make the `GatewayClass` name configurable so that
the same CI workflow can test against an alternative implementation by setting
an environment variable:

```bash
GATEWAY_CLASS_NAME=${GATEWAY_CLASS_NAME:-fabric-envoy-gateway}
```

And in `apply_gatewayclass()`:

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: ${GATEWAY_CLASS_NAME}
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
EOF
```

This allows a future CI job to run `GATEWAY_CLASS_NAME=nginx` with NGINX Gateway
Fabric without changing any Ansible template.

---

## 5. Impact on `PRE-ANALYSIS.md` and `MIGRATION-PLAN.md`

The following amendments are needed in the two planning documents as a result of
this analysis:

| Document | Section | Amendment |
|---|---|---|
| `PRE-ANALYSIS.md` | §4.2 implementation list | Add Istio Gateway API mode and ambient mode; add Cilium; note cloud-managed limitations |
| `PRE-ANALYSIS.md` | §4.3 migration footprint item 1 | Add note that `GatewayClass` name is a variable enabling portability |
| `PRE-ANALYSIS.md` | §7 Recommendation | Strengthen rationale: portability guarantee is because only standard resources are used |
| `MIGRATION-PLAN.md` | §5.2 W2 bootstrap script | Add `GATEWAY_CLASS_NAME` variable |
| `MIGRATION-PLAN.md` | §5.1 W1 defaults | Add `gateway_class_name` variable |
