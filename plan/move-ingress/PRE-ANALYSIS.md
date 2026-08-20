# Pre-Analysis: Migrating away from ingress-nginx

## 1. Context and Driver

The `fabric-ansible-collection` requires [ingress-nginx](https://github.com/kubernetes/ingress-nginx)
(`controller-v1.1.2`) as its sole supported Kubernetes ingress solution.
ingress-nginx is a **cluster-level prerequisite**: it is not provisioned by any
Ansible role in this collection, but by the cluster administrator (or, for local
KIND development, by the CI bootstrap script
[`kind_with_nginx.sh`](../../.github/scripts/kind_with_nginx.sh) — see §1.1).

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

## 1.1 How the ingress-nginx controller is currently installed — prerequisite or role task?

This is a critical design question for any migration plan. The answer is
**the collection does not install ingress-nginx itself**; it is an external
prerequisite, installed by a shell script that lives outside the Ansible role
boundary. The evidence is unambiguous:

### What the `fabric_operator_crds` role does (and does not do)

[`roles/fabric_operator_crds/tasks/k8s/create.yml`](../../roles/fabric_operator_crds/tasks/k8s/create.yml)
contains exactly five tasks:

1. Apply the fabric-operator CRDs from the upstream kustomize ref.
2. Fail if `namespace` is not set.
3. Create the namespace if it does not exist.
4. Create RBAC resources (ClusterRole, ClusterRoleBinding, ServiceAccount).
5. Deploy the fabric-operator Deployment and wait for it to roll out.

**There is no task that installs, configures, or waits for any ingress controller.**
The role documentation explicitly states this:

> *"This role does not install an ingress controller; for the opensource Fabric
> Operations Console and Fabric operator you must configure a suitable ingress
> controller."*
> — [`docs/source/roles/fabric-operator-crds.rst`](../../docs/source/roles/fabric-operator-crds.rst#L26)

The same disclaimer appears verbatim in
[`docs/source/roles/fabric-console.rst`](../../docs/source/roles/fabric-console.rst#L26).

### Where ingress-nginx is installed

The ingress-nginx controller is installed exclusively by the CI shell script
[`.github/scripts/kind_with_nginx.sh`](../../.github/scripts/kind_with_nginx.sh),
specifically in its `start_nginx()` function (line 98):

```bash
kubectl apply -k https://github.com/hyperledger-labs/fabric-operator.git/config/ingress/kind
```

This is the upstream fabric-operator's own kustomize ref for KIND environments.
It installs ingress-nginx with SSL passthrough enabled, pinned to the version
maintained by the fabric-operator project.

The CI workflow [`fvtest.yml`](../../.github/workflows/fvtest.yml) calls
`kind_with_nginx.sh` as an environment bootstrap step **before** any Ansible
playbook is executed. The `run-tests.sh` script that follows only calls
`build_network.sh` (which starts at tutorial step 01) — it assumes nginx is
already present and operational.

### The CoreDNS override also lives in the shell script

The `apply_coredns_override()` function in `kind_with_nginx.sh` (line 115)
patches the CoreDNS `ConfigMap` directly via `kubectl apply`. The Ansible
template at
[`roles/fabric_operator_crds/templates/k8s/coredns/coredns.yaml.j2`](../../roles/fabric_operator_crds/templates/k8s/coredns/coredns.yaml.j2)
exists as a template but there is **no Ansible task in any role that applies it**.
It is only used by the shell script (which contains its own inline copy of the
same CoreDNS stanza).

### Summary of the boundary

| Responsibility | Handled by |
|---------------|------------|
| Install ingress-nginx | `kind_with_nginx.sh` (CI shell script — external to Ansible roles) |
| Apply CoreDNS wildcard override | `kind_with_nginx.sh` (CI shell script — not an Ansible task) |
| Install fabric-operator CRDs + operator | `fabric_operator_crds` Ansible role |
| Deploy console | `fabric_console` / `hlfsupport_console` Ansible role |
| Deploy peers / orderers / CAs | `endorsing_organization` / `ordering_organization` Ansible roles |

The ingress controller is therefore a **cluster-level prerequisite** that the
collection assumes is already present when any playbook runs. For end-users
deploying to a managed Kubernetes service (IKS, EKS, GKE), the documentation
explicitly directs them to configure their cloud provider's ALB/ingress
controller manually before running the collection (see
[`oss-installing.rst` line 40](../../docs/source/tutorials/oss-installing.rst#L40)
and
[`hlfsupport-installing.rst` line 44](../../docs/source/tutorials/hlfsupport-installing.rst#L44)).

### Implication for the migration plan

The migration plan must **preserve this boundary**: the ingress / gateway
controller installation remains outside the Ansible role scope, handled either
by the user for production clusters or by a CI bootstrap script for local KIND
development. What the migration plan *does* need to add is:

1. A new CI bootstrap script for the Gateway API path
   (replacing `kind_with_nginx.sh` with a `kind_with_envoy_gateway.sh`).
2. Updated prerequisites documentation telling users what to install before
   running the collection with `ingress_type: gateway-api`.
3. **No changes to the task entry points** of `fabric_operator_crds`,
   `fabric_console`, `endorsing_organization`, or `ordering_organization` for
   the purposes of installing a gateway controller.

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

### 2.4 Network exposition rationality — which services need an external gateway and when

Not every HLF service needs to be reachable from outside the cluster under every
deployment topology. Creating a gateway route for a service that is only ever
accessed from within the same cluster wastes listener slots and enlarges the attack
surface unnecessarily. This section analyses each service systematically so that
the migration plan can make route creation **conditional** where it is genuinely
optional.

#### 2.4.1 Topology scenarios

Three canonical scenarios cover the vast majority of real deployments:

| Scenario | Ansible control machine | Cluster topology |
|----------|------------------------|-----------------|
| **A — in-cluster** | Running inside the Kubernetes cluster (e.g. a CI pod, a GitOps operator, or a trusted lead-org bootstrap shell) | Single cluster — all participants share it |
| **B — out-of-cluster, single cluster** | Running outside the cluster (developer laptop, remote runner) | Single cluster, all HLF namespaces share one cluster |
| **C — multi-cluster / multi-org** | Running outside one or more clusters | Each organisation (or consortium member) owns a separate cluster; cross-cluster peer/orderer communication over the public internet |

In practice, scenario B is the most common developer/operator experience; scenario C
is the production pattern for organisations that do not trust a shared cluster.

Scenario A arises in three distinct contexts:
1. **CI pipelines** — a runner pod executes the playbook directly inside the cluster.
2. **GitOps flows** — an Argo CD / Flux controller runs the Ansible playbook in-cluster.
3. **Trusted lead-org bootstrap** — at the beginning of a network, one organisation
   is trusted to host components for other participants (peers, CAs, or even an
   initial orderer) within its own cluster. All Ansible automation runs from inside
   that cluster, so there is no external traffic between the control machine and
   the hosted components. This is a common pattern for consortium bootstrapping
   before each member has provisioned their own independent infrastructure.

In all three Scenario A sub-cases, every Fabric service is reachable from the
control machine via `ClusterIP` or in-cluster `Service` DNS — no external gateway
route is required for Ansible automation. External routes are still needed for
browser access to the console and for cross-cluster Fabric traffic once other
organisations join from outside.

#### 2.4.2 How the code determines reachability requirements

From the touch-point audit in §3, the Ansible control machine connects directly
(not through the console broker) to the following endpoints:

| Endpoint | Module / utils | Purpose of direct connection |
|----------|---------------|------------------------------|
| CA `api_url` | [`certificate_authorities.py`](../../plugins/module_utils/certificate_authorities.py) `CertificateAuthorityConnection` | `fabric-sdk-py` enroll / register calls |
| CA `operations_url` | Same file, `wait_for()` | `/healthz` poll to confirm CA startup |
| Peer `api_url` | [`peers.py`](../../plugins/module_utils/peers.py) `_get_environ()` | `CORE_PEER_ADDRESS` env var for `peer` CLI subprocess |
| Peer `operations_url` | Same file, `wait_for()` | `/healthz` poll |
| Orderer `api_url` | [`ordering_services.py`](../../plugins/module_utils/ordering_services.py) `_get_ordering_service()` | `--orderer` flag in `peer channel fetch/update` subprocess |
| Orderer `operations_url` | Same file, `wait_for()` | `/healthz` poll |
| Console `api_endpoint` | [`consoles.py`](../../plugins/module_utils/consoles.py) `Console` | **All** component lifecycle management (the broker) |

The following endpoints are **never** called directly by any Ansible module:

| Endpoint | Why not needed by Ansible |
|----------|--------------------------|
| `grpcwp_url` | Consumed by browser clients via the console UI; Ansible has no gRPC-Web logic |
| Orderer `osnadmin_url` | Optional, defaults to `None`; only used by `external_ordering_service_node` for the channel participation API, and only when the caller explicitly provides it |
| Fabric Operator health (`:8383`) | Internal Kubernetes operator health port; no external API |
| CRD Webhook (`:443` ClusterIP) | API-server admission webhook; always internal |

#### 2.4.3 Per-service exposition analysis

**Console (`api_endpoint`)**

The console is the broker for every component lifecycle operation and is also the
human-facing UI. It must be reachable from the Ansible control machine **and** from
the operator's browser in all three scenarios. There is no scenario in which the
console is optional as an external endpoint.

- Scenario A (in-cluster): the control machine can reach the console via
  `ClusterIP` for Ansible operations, but the browser of any human operator — from
  the lead org or a joining org — still needs an external route.
- Scenarios B and C: the control machine is outside the cluster; an external route
  is mandatory for Ansible as well.

**Conclusion: console external gateway route is always mandatory.**

---

**CA `api_url`** (enroll / register)

The CA `api_url` is called directly from the control machine for cryptographic
enrolment operations (via `fabric-sdk-py`). The CA's `operations_url` is also
polled during startup via `/healthz`.

- Scenario A: the control machine can reach the CA via the in-cluster `Service`
  DNS name. No external gateway route is needed.
- Scenarios B and C: the control machine is outside the cluster. An external
  gateway route on the HTTPS listener (`:443`) is required.

**Conclusion: CA external gateway route is mandatory when the control machine is
outside the cluster (Scenarios B and C); optional in Scenario A. The `expose_ca`
variable should default to `true` and be set to `false` only for fully in-cluster
automation.**

---

**Peer `api_url`** (gRPC channel operations)

The peer `api_url` is used as `CORE_PEER_ADDRESS` for all `peer` CLI subprocesses
(channel fetch, channel update, chaincode install, etc.). The `operations_url` is
also polled during startup.

- Scenario A: the control machine can reach the peer via `ClusterIP`.
- Scenario B: an out-of-cluster control machine requires an external gateway route
  on the TLS passthrough listener (`:7051` under the recommended model).
- Scenario C: peers in different clusters must be reachable by remote control
  machines and by peers / orderers in other clusters — both via the external gateway.

In Scenario A (trusted lead-org), peers hosted for another organisation are accessed
by the lead org's in-cluster control machine without any external route. When that
other organisation later migrates its components to its own cluster (Scenario C),
it will supply its own external gateway. No interim external route is needed for
the hosted phase.

Additional dimension: **peer-to-peer gossip traffic** within a single cluster uses
`ClusterIP`. In a multi-cluster deployment, gossip must traverse the external
gateway, but it uses the same TLS passthrough route as the gRPC API (`externalEndpoint`
in the `IBPPeer` CRD already encodes this).

**Conclusion: peer external gateway route is mandatory for out-of-cluster Ansible
(Scenarios B and C); optional in Scenario A. The `expose_peer` variable should
default to `true`.**

---

**Orderer `api_url`** (channel lifecycle)

Same analysis as the peer. The orderer `api_url` is passed as `--orderer` to the
`peer` CLI for `channel fetch` and `channel update`.

- Scenario A: reachable via `ClusterIP`.
- Scenarios B and C: requires an external gateway route on the orderer TLS passthrough
  listener (`:7050`).

In a multi-cluster consortium, orderer endpoints must be reachable by peers and
Ansible control machines in other clusters. In the trusted lead-org Scenario A
bootstrap, orderers provisioned for a joining org are reached in-cluster by the
lead org's playbook; no external route is needed until the joining org takes
ownership of its own cluster.

**Conclusion: orderer external gateway route is mandatory for Scenarios B and C;
optional in Scenario A. The `expose_orderer` variable should default to `true`.**

---

**Peer `operations_url` and Orderer `operations_url`**

The operations endpoint (`/healthz`) is polled exclusively by the `wait_for()`
helper in `peers.py` and `ordering_services.py` to confirm node startup. It is
never called by any external client or by another Fabric node.

- Scenario A: reachable via `ClusterIP`.
- Scenarios B and C: the control machine is outside the cluster. An HTTPS route on
  the `:443` listener would expose it, but this is not the only option — the startup
  poll can equivalently be replaced by watching the resource's `status.conditions`
  via the Kubernetes API (always accessible to an authenticated `kubeconfig`), which
  requires no gateway route at all.

**Conclusion: operations endpoint external routes are conditionally required
(mandatory for Scenario B/C with the current `wait_for()` implementation; avoidable
by switching to `kubernetes.core.k8s_info` readiness watches). The
`expose_peer_operations` and `expose_orderer_operations` variables should default to
`false` and be enabled only when the `kubeconfig`-based alternative is not
available.**

---

**gRPC-Web proxy (`grpcwp_url`)**

The `grpcwp_url` is stored in the console component registry but is never read by
any Ansible module. It exists solely for browser clients using the Operations
Console UI to submit transactions via gRPC-Web from a browser context.

- In automated / headless deployments (CI, GitOps, lead-org bootstrap) the console
  REST API is used and `grpcwp_url` is never exercised by Ansible.
- Human-facing console deployments need it to enable transaction submission from the
  browser, but this is an optional feature.

**Conclusion: gRPC-Web proxy external route is optional in all scenarios from
Ansible's perspective. The `expose_grpcweb` variable should default to `false`
(CI / automated contexts); human-facing deployments opt in by setting it to `true`.**

---

**Fabric Operator (`:8383` TCP health)**

The operator's health port is an internal Kubernetes liveness/readiness probe
endpoint consumed by the API server, not by external clients or by Ansible. It is
not and should never be gateway-routed.

**Conclusion: no external route required, ever.**

---

**CRD Webhook (hlfsupport variant)**

The admission webhook (`:3000` in the container, ClusterIP `:443`) is consumed by
the Kubernetes API server at admission time. It must be a `ClusterIP` service by
design and cannot be meaningfully exposed through an ingress or gateway.

**Conclusion: no external route required, ever.**

---

#### 2.4.4 Summary matrix

| Service | Scenario A (in-cluster) | Scenario B (out-of-cluster, single) | Scenario C (multi-cluster) | Default `expose_*` | Listener |
|---------|------------------------|------------------------------------|-----------------------------|-------------------|---------|
| Console `api_endpoint` | ✅ mandatory (browser) | ✅ mandatory | ✅ mandatory | always on | HTTPS `:443` |
| CA `api_url` | ❌ optional (ClusterIP) | ✅ mandatory | ✅ mandatory | `expose_ca: true` | HTTPS `:443` |
| Peer `api_url` (gRPC) | ❌ optional | ✅ mandatory | ✅ mandatory | `expose_peer: true` | TLS passthrough `:7051` |
| Orderer `api_url` (gRPC) | ❌ optional | ✅ mandatory | ✅ mandatory | `expose_orderer: true` | TLS passthrough `:7050` |
| Peer `operations_url` | ❌ optional | ⚠️ conditional | ⚠️ conditional | `expose_peer_operations: false` | HTTPS `:443` |
| Orderer `operations_url` | ❌ optional | ⚠️ conditional | ⚠️ conditional | `expose_orderer_operations: false` | HTTPS `:443` |
| gRPC-Web proxy `grpcwp_url` | ❌ not used by Ansible | ❌ not used by Ansible | ❌ not used by Ansible | `expose_grpcweb: false` | HTTPS `:443` |
| Operator health (`:8383`) | ❌ never | ❌ never | ❌ never | — (no variable) | N/A |
| CRD Webhook | ❌ never | ❌ never | ❌ never | — (no variable) | N/A |

The defaults represent a production-safe baseline where every externally-accessed
service is exposed by default (Scenarios B and C). In-cluster deployments (Scenario A
— CI, GitOps, or trusted lead-org bootstrap) gain no performance benefit from
disabling routes in KIND + Envoy Gateway, but setting `expose_peer_operations: false`,
`expose_orderer_operations: false`, and `expose_grpcweb: false` reduces the route
count and simplifies the `HTTPRoute` template. The `expose_grpcweb: false` default
reflects the reality that gRPC-Web routes are never needed for Ansible automation;
they are opt-in for human-facing console deployments.

---

## 3. Current ingress-nginx Integration — Complete Touch-point Audit

The table below covers every file in the collection that encodes ingress-nginx
assumptions — either as CI infrastructure, as dead-letter templates, as RBAC
grants, or as application-level wait logic. None of these files provision the
ingress-nginx controller itself; they either configure or assume it.

| File | What it encodes | What must change |
|------|----------------|-----------------|
| [`.github/scripts/kind_with_nginx.sh`](../../.github/scripts/kind_with_nginx.sh) | CI prerequisite: installs ingress-nginx for KIND via `kubectl apply -k fabric-operator.git/config/ingress/kind`, then applies CoreDNS override | Replace with a new `kind_with_envoy_gateway.sh` for the Gateway API CI path; keep this script for the nginx CI path |
| [`roles/fabric_operator_crds/templates/k8s/ingress/kustomization.yaml`](../../roles/fabric_operator_crds/templates/k8s/ingress/kustomization.yaml) | Dead-letter template: references ingress-nginx v1.1.2 kustomize ref — **not wired to any Ansible task** | Replace with Gateway API equivalent templates (also unwired; installed by CI or admin) |
| [`roles/fabric_operator_crds/templates/k8s/ingress/ingress-nginx-controller.yaml`](../../roles/fabric_operator_crds/templates/k8s/ingress/ingress-nginx-controller.yaml) | Dead-letter template: `--enable-ssl-passthrough` patch — **not wired to any Ansible task** | Replace with Gateway API equivalent or delete |
| [`roles/fabric_operator_crds/templates/k8s/coredns/coredns.yaml.j2`](../../roles/fabric_operator_crds/templates/k8s/coredns/coredns.yaml.j2) | Dead-letter template: CoreDNS rewrite pointing at nginx ClusterIP — **not wired to any Ansible task**; the CI script contains its own inline copy | Update `host.ingress.internal` target; CI script's inline copy must also be updated |
| [`roles/fabric_operator_crds/defaults/main.yml`](../../roles/fabric_operator_crds/defaults/main.yml#L46) | Default variable `ingress_domain: localho.st` used by templates | Probably stays; does not reference nginx by name |
| [`roles/fabric_operator_crds/templates/k8s/rbac/hlf-operator-clusterrole.yaml`](../../roles/fabric_operator_crds/templates/k8s/rbac/hlf-operator-clusterrole.yaml#L182) | Grants the operator `get/create/…` on `networking.k8s.io/ingresses` | Extend to include `gateway.networking.k8s.io` resources |
| [`roles/hlfsupport_console/templates/k8s/cluster_role.yml.j2`](../../roles/hlfsupport_console/templates/k8s/cluster_role.yml.j2#L168) | Same RBAC grant for `hlfsupport` variant | Same extension required |
| [`roles/hlfsupport_console/tasks/k8s/create.yml`](../../roles/hlfsupport_console/tasks/k8s/create.yml#L146) | **Live task**: waits on `networking.k8s.io/v1 Ingress` resource to appear and derives the console URL from it | Make conditional on `ingress_type`; add `HTTPRoute` wait branch |
| [`docs/source/tutorials/oss-installing.rst`](../../docs/source/tutorials/oss-installing.rst#L40) | Prerequisite note: directs IKS users to configure nginx ALB SSL passthrough manually | Update to direct users to install the Gateway API controller instead |
| [`docs/source/tutorials/hlfsupport-installing.rst`](../../docs/source/tutorials/hlfsupport-installing.rst#L44) | Same prerequisite note | Same update |
| [`docs/source/roles/fabric-operator-crds.rst`](../../docs/source/roles/fabric-operator-crds.rst#L23) | States "this role does not install an ingress controller; you must configure a suitable ingress controller" | Update the referenced controller name; the statement itself remains accurate |
| [`docs/source/roles/fabric-console.rst`](../../docs/source/roles/fabric-console.rst#L23) | Same disclaimer | Same update |

Additionally, the CI bootstrap script delegates to the upstream `fabric-operator`
project's own kustomize ref for the nginx + SSL-passthrough configuration:

```
kubectl apply -k https://github.com/hyperledger-labs/fabric-operator.git/config/ingress/kind
```

That kustomize path also lives upstream; a Gateway API / Istio equivalent should
either be contributed there or maintained locally in the CI script.

---

## 4. Option A — Kubernetes Gateway API

### 4.1 What it is

The [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/) (`gateway.networking.k8s.io`)
is the SIG-Network successor to `networking.k8s.io/Ingress`. It reached GA with
v1.0 (December 2023); the current release is **v1.5 (April 2026)**. It separates
concerns across three resource levels: `GatewayClass` (infrastructure), `Gateway`
(instance), `HTTPRoute` / `TLSRoute` / `TCPRoute` (application traffic).

As of v1.5, `TLSRoute` has been **promoted to the Standard channel (GA)** — it is
no longer an experimental or beta resource. See the [Gateway API v1.5 release
blog](https://kubernetes.io/blog/2026/04/21/gateway-api-v1-5/).

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

With `TLSRoute` now GA in v1.5, the implementation landscape has broadened.
See [`GATEWAY-API-IMPLEMENTATIONS.md`](./GATEWAY-API-IMPLEMENTATIONS.md) for a
full comparison. A summary of implementations with confirmed `TLSRoute` passthrough
support:

| Implementation | Footprint | `TLSRoute` GA | mTLS conflict risk | CI/PoC suitability |
|---|---|---|---|---|
| **Envoy Gateway v1.3+** | Minimal (2 pods) | ✅ | None | ✅ Recommended |
| **NGINX Gateway Fabric v2+** | Minimal (2 pods) | ✅ | None | ✅ Viable |
| **Contour v1.28+** | Moderate | ✅ | None | ⚠️ Heavier than needed |
| **Istio v1.22+ (sidecar)** | Heavy (sidecar per pod) | ✅ | ⚠️ High | ❌ Not recommended for CI |
| **Istio v1.22+ (ambient)** | Moderate (ztunnel DaemonSet) | ✅ | Low | ⚠️ If already using Istio |
| **Cilium v1.16+** | CNI-integrated | ⚠️ Partial passthrough | None | ⚠️ CNI-dependent |
| **GKE / AWS ALB / Azure AGFC** | Cloud-managed | ❌ | N/A | ❌ No passthrough |

**Important:** the collection's Ansible templates use **only standard Gateway API
resources** (`GatewayClass`, `Gateway`, `HTTPRoute`, `TLSRoute`). The
implementation-specific element is the `GatewayClass` name only, which is exposed
as a variable (`gateway_class_name`). Users can therefore substitute any conformant
implementation in production without changing any template.

### 4.3 Migration footprint

A Gateway API migration would produce:

1. **A new CI bootstrap script** (`kind_with_envoy_gateway.sh`) that installs
   the `GatewayClass` + Envoy Gateway controller as a cluster prerequisite (Envoy
   Gateway being the recommended CI/PoC implementation — see
   [`GATEWAY-API-IMPLEMENTATIONS.md`](./GATEWAY-API-IMPLEMENTATIONS.md) §4).
   Production cluster administrators install their preferred conformant
   implementation instead.
2. **A `Gateway` manifest** (namespace-scoped, domain-parameterised) applied by
   the `fabric_operator_crds` role with two listeners (`:443 HTTPS` and
   `:7050`/`:7051 TLS Passthrough`). Unlike the controller itself, the `Gateway`
   resource is a per-deployment configuration that belongs inside the Ansible role.
3. **`TLSRoute` resources** for the raw gRPC `api_url` endpoints — generated by a
   post-creation Ansible task (until the `fabric-operator` upstream adds native
   Gateway API support).
4. **`HTTPRoute` resources** for the console, gRPC-Web proxy, CA, and Operations
   endpoints.
5. **Updated CI CoreDNS override** in the bootstrap script, pointing at the Envoy
   Gateway service ClusterIP instead of the nginx service ClusterIP.
6. **Updated RBAC** to grant the operator `gateway.networking.k8s.io` permissions.
7. **`api_url` port change** in tutorial vars and documentation from `:443` / `:32000`
   to `:7050` (orderer) / `:7051` (peer) for gRPC passthrough endpoints (see §8.6).

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

* `TLSRoute` is GA in v1.5 but implementation adoption in cloud-managed controllers
  is still incomplete; self-managed controllers (Envoy Gateway, Contour, NGF) are
  the reliable choice today.
* Requires operator-side changes to replace `Ingress` with `HTTPRoute` / `TLSRoute`.
* No single cloud-managed implementation handles all Fabric protocols today.

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
| **TLS passthrough** | ✅ `TLSRoute` (GA in v1.5) | ✅ `Gateway tls.PASSTHROUGH` (stable) |
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

**Primary recommendation: Kubernetes Gateway API, with Envoy Gateway as the
reference implementation for CI and PoC.**

Rationale:
1. Port-based protocol segregation and `TLSRoute passthrough` (GA in v1.5) cover
   all Fabric routing requirements without introducing a mesh control-plane.
2. The collection uses **only standard Gateway API resources**; the
   implementation-specific element is the `gateway_class_name` variable only.
   This guarantees portability: production users running Istio, Contour, or NGF
   swap in their implementation without changing any Ansible template.
3. Envoy Gateway is the recommended CI/PoC implementation: smallest footprint
   (2 pods), highest conformance score, no mTLS conflict risk, and no extra CRDs.
4. Kubernetes Gateway API is the direction the Kubernetes community has chosen; the
   `fabric-operator` upstream will inevitably move there as `networking.k8s.io/Ingress`
   is eventually deprecated.
5. No risk of double-mTLS conflict between Istio and Fabric TLS chains (unlike the
   Istio sidecar option).
6. No per-pod sidecar overhead on Fabric nodes.
7. The migration surface in this collection is well-contained (see §3).

**For deployments already running Istio:** Istio v1.22+ implements the Kubernetes
Gateway API natively. Users can set `gateway_class_name: istio` and use the
**same `HTTPRoute` and `TLSRoute` templates** without modification. With ambient
mode (Istio v1.22+) the sidecar mTLS conflict risk is also significantly reduced.
See [`GATEWAY-API-IMPLEMENTATIONS.md`](./GATEWAY-API-IMPLEMENTATIONS.md) §2.2 for
the full Istio analysis.

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

### 8.2 Gateway API version pin and implementation selection

`TLSRoute` was promoted to the Standard channel (GA) in Gateway API **v1.5**
(April 2026). The CI bootstrap script must therefore target **Gateway API v1.5 or
later** using the **standard install manifest** (not the experimental channel).
The current script [`kind_with_nginx.sh`](../../.github/scripts/kind_with_nginx.sh)
pins `controller-v1.1.2` of ingress-nginx via a kustomize ref; the new
`kind_with_envoy_gateway.sh` must pin a compatible Envoy Gateway release tag
(Envoy Gateway v1.3+ supports `TLSRoute` as GA). The nginx script itself is
unchanged and continues to serve the legacy CI path.

### 8.3 RBAC extension for the operator

The `ClusterRole` in
[`hlf-operator-clusterrole.yaml`](../../roles/fabric_operator_crds/templates/k8s/rbac/hlf-operator-clusterrole.yaml#L182)
currently grants `networking.k8s.io/ingresses`. It must be extended to include
`gateway.networking.k8s.io` resources:
`gateways`, `httproutes`, `tlsroutes`, `referencegrants`.
The same applies to the `hlfsupport_console` cluster role template.

### 8.4 CoreDNS wildcard override

The CoreDNS `ConfigMap` template
([`coredns.yaml.j2`](../../roles/fabric_operator_crds/templates/k8s/coredns/coredns.yaml.j2))
and its inline copy inside `kind_with_nginx.sh` both rewrite `*.localho.st` to
the ingress-nginx service ClusterIP. This is applied exclusively by the CI shell
script (`apply_coredns_override()`) — there is no Ansible task that applies it.
For the Gateway API path, the same CI-script function must resolve the Envoy
Gateway service ClusterIP instead. There is a timing constraint: the Envoy Gateway
service for a given namespace only appears after the `Gateway` resource is created
by the Ansible role, so the CoreDNS override step must run **after** the playbook,
not before. This is a change in CI workflow sequencing, not a change in any Ansible
role.

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
conditional role behaviour where the collection's own tasks differ between paths —
specifically the `Gateway` resource creation (§W5 in the migration plan), the
console `Ingress` vs `HTTPRoute` wait logic (§W5), and the post-operator route
overlay (§W6). It does **not** control which ingress controller is installed, since
that remains the responsibility of the cluster administrator or CI bootstrap script.
Existing users on nginx must not be broken; the nginx path should remain the
default and be deprecated gracefully.

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
[`kind_with_nginx.sh`](../../.github/scripts/kind_with_nginx.sh) to provision
the cluster prerequisite (ingress-nginx + CoreDNS) before any Ansible playbook
runs. A new parallel script `kind_with_envoy_gateway.sh` must:
1. Create a KIND cluster with host-port mappings for `:443`, `:7050`, and `:7051`.
2. Install the Gateway API CRDs v1.5+ using the **standard channel** (`standard-install.yaml`); `TLSRoute` is GA and no longer requires the experimental channel.
3. Install Envoy Gateway v1.3+ (or chosen implementation) as the `GatewayClass` controller.
4. Apply the `GatewayClass` resource and wait for it to be `Accepted`.
5. **Not** apply the `Gateway` resource or the CoreDNS override — these depend on
   the namespace and domain that are only known when the Ansible playbook runs.
6. After the Ansible playbook has executed, apply the CoreDNS override pointing at
   the Envoy Gateway service ClusterIP.

The existing `kind_with_nginx.sh` is kept unchanged and continues to be used when
`ingress_type == 'nginx'`. The CI workflow matrix runs both scripts in parallel.

### 8.10 Compatibility with OpenShift

OpenShift uses `route.openshift.io/Route` rather than `Ingress`. The OpenShift
path of the collection is currently handled separately; Gateway API on OpenShift
requires OpenShift Service Mesh (Istio-based) or Red Hat's Gateway API
implementation. The migration plan must explicitly state whether OpenShift support
is in scope for the first iteration.
