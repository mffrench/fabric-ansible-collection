# Migration Plan: ingress-nginx → Kubernetes Gateway API

## 0. Document conventions

- **[NGINX]** — tasks that apply only to the legacy nginx path.
- **[GW]** — tasks that apply only to the new Gateway API path.
- **[BOTH]** — tasks that apply to both paths and must be kept in sync.
- All file paths are relative to the repository root.

---

## 1. Goals

1. Allow users to choose between the **deprecated ingress-nginx controller** (legacy
   path, kept for backwards compatibility during a transition window) and the new
   **Kubernetes Gateway API** implementation (Envoy Gateway as the reference
   implementation).
2. The Gateway API path uses a **shared-port-per-protocol-class** topology that
   maps every HLF component to its canonical default port, eliminating the
   current single-port-on-443 compromise.
3. No existing playbook should break without an explicit opt-in to the new path.
4. OpenShift is explicitly **out of scope** for the first iteration; the OpenShift
   `Route`-based path is unchanged.

---

## 2. Port topology

### 2.1 HLF component default ports

The following are the canonical Hyperledger Fabric default ports, confirmed from
`core.yaml` embedded in [`plugins/module_utils/fabric_utils.py`](../../plugins/module_utils/fabric_utils.py:36)
and the upstream Fabric documentation:

| Component | Protocol | Default pod port | Role in ingress |
|-----------|----------|-----------------|-----------------|
| Fabric Orderer — gRPC API | gRPC over mTLS | **7050** | TLS passthrough |
| Fabric Orderer — OSN Admin | HTTPS REST | **9443** | HTTPS reverse-proxy |
| Fabric Peer — gRPC API | gRPC over mTLS | **7051** | TLS passthrough |
| Fabric Peer — Operations | HTTPS REST | **9443** | HTTPS reverse-proxy |
| Fabric CA — API + Operations | HTTPS REST | **7054** | HTTPS reverse-proxy |
| Fabric Operations Console | HTTPS | **443** (via `IBPConsole`) | HTTPS reverse-proxy |
| Fabric Operator | Internal health only (`:8383` TCP) | — | **Not ingress-routed** |
| CRD Webhook (hlfsupport) | HTTPS (`:3000` container → `:443` ClusterIP) | — | **Not ingress-routed** (ClusterIP only) |
| gRPC-Web proxy (`grpc-web` sidecar) | HTTP/1.1 + WebSocket | **443** (sidecar) | HTTPS reverse-proxy |

### 2.2 Gateway listener topology

Under the Gateway API path, a single `Gateway` resource carries **three listeners**,
each covering one protocol class. SNI within each passthrough listener distinguishes
individual nodes.

| Listener name | External port | Protocol mode | Serves |
|---------------|--------------|---------------|--------|
| `https` | **443** | `HTTPS` — TLS terminated at gateway | Console, CA, gRPC-Web proxy, Orderer OSN Admin, Peer Operations |
| `orderer-passthrough` | **7050** | `TLS` — Passthrough | All orderer gRPC API endpoints |
| `peer-passthrough` | **7051** | `TLS` — Passthrough | All peer gRPC API endpoints |

This means:
- `api_url` for orderers changes from `grpcs://<host>:443` (or `:32000`) to `grpcs://<host>:7050`.
- `api_url` for peers changes to `grpcs://<host>:7051`.
- `grpcwp_url`, `operations_url`, CA `api_url`, and console URLs remain on `:443`.

### 2.3 Legacy nginx listener topology (unchanged)

ingress-nginx continues to use a single `:443` listener with `--enable-ssl-passthrough`
and SNI-based routing for all endpoints (current behaviour). No port changes.

---

## 3. New Ansible variable

A single new variable governs the entire routing path:

```yaml
# Accepted values:
#   nginx        — legacy ingress-nginx (default; existing behaviour)
#   gateway-api  — Kubernetes Gateway API via Envoy Gateway
ingress_type: nginx
```

This variable is introduced in `roles/fabric_operator_crds/defaults/main.yml`
with the default `nginx` so that **all existing playbooks continue to work without
modification**.

---

## 4. Workstream breakdown

The migration is split into six independent workstreams that can proceed in parallel
once the variable abstraction (§5.1) is in place.

| # | Workstream | Scope | Blocking dependency |
|---|-----------|-------|---------------------|
| W1 | Variable abstraction + defaults | `fabric_operator_crds` role | None |
| W2 | Gateway installation task | `fabric_operator_crds` role, new templates | W1 |
| W3 | CoreDNS override | `fabric_operator_crds` role | W2 |
| W4 | RBAC extension | All cluster role templates | W1 |
| W5 | Console wait logic | `hlfsupport_console` role | W1 |
| W6 | CI bootstrap | `.github/scripts/` | W2, W3 |
| W7 | Route resources (post-operator overlay) | New Ansible tasks | W2, upstream |
| W8 | Documentation | `docs/` | All |

---

## 5. Detailed task specifications

### 5.1 W1 — Variable abstraction

**File:** `roles/fabric_operator_crds/defaults/main.yml`

Add `ingress_type: nginx` as a new default. Also add `ingress_grpc_orderer_port`
and `ingress_grpc_peer_port` to allow overrides:

```yaml
# Ingress controller type: nginx | gateway-api
ingress_type: nginx

# Gateway API path only: external ports for TLS passthrough listeners.
# These must match the Gateway listener ports and the hostPort mappings
# in the KIND node configuration for local development.
ingress_grpc_orderer_port: 7050
ingress_grpc_peer_port: 7051
```

**File:** `roles/fabric_operator_crds/tasks/k8s/create.yml`

Wrap the existing nginx installation block in a condition, and add a new block
for Gateway API installation:

```yaml
# [NGINX] Install ingress-nginx (deprecated path)
- name: Install ingress-nginx controller
  kubernetes.core.k8s:
    definition: "{{ lookup('kubernetes.core.kustomize',
      dir=ingress_nginx_kustomize_ref) }}"
  when: ingress_type == 'nginx'

# [GW] Install Envoy Gateway
- name: Install Envoy Gateway
  kubernetes.core.k8s:
    definition: "{{ lookup('kubernetes.core.kustomize',
      dir=envoy_gateway_kustomize_ref) }}"
  when: ingress_type == 'gateway-api'

# [GW] Apply GatewayClass and Gateway
- name: Apply fabric GatewayClass and Gateway
  kubernetes.core.k8s:
    state: present
    namespace: "{{ namespace }}"
    resource_definition: "{{ lookup('template',
      'templates/k8s/gateway/fabric-gateway.yaml.j2') }}"
  when: ingress_type == 'gateway-api'
```

Add the following versioned references to `defaults/main.yml`:

```yaml
ingress_nginx_kustomize_ref: >-
  https://github.com/kubernetes/ingress-nginx.git/deploy/static/provider/cloud?ref=controller-v1.1.2
envoy_gateway_kustomize_ref: >-
  https://github.com/envoyproxy/gateway.git/charts/gateway-helm?ref=v1.2.0
```

---

### 5.2 W2 — Gateway installation templates

#### 5.2.1 New file: `roles/fabric_operator_crds/templates/k8s/gateway/`

Create the directory and the following templates.

**`roles/fabric_operator_crds/templates/k8s/gateway/fabric-gatewayclass.yaml`**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: fabric-envoy-gateway
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
```

**`roles/fabric_operator_crds/templates/k8s/gateway/fabric-gateway.yaml.j2`**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: fabric-gateway
  namespace: "{{ namespace }}"
spec:
  gatewayClassName: fabric-envoy-gateway
  listeners:
    # ── HTTPS: console, CA, gRPC-Web proxy, operations endpoints ──────────
    - name: https
      port: 443
      protocol: HTTPS
      hostname: "*.{{ ingress_domain }}"
      tls:
        mode: Terminate
        certificateRefs:
          - name: "{{ ingress_tls_secret | default('fabric-tls-secret') }}"
      allowedRoutes:
        namespaces:
          from: Same

    # ── TLS passthrough: orderer gRPC API (port 7050) ──────────────────────
    - name: orderer-passthrough
      port: "{{ ingress_grpc_orderer_port }}"
      protocol: TLS
      hostname: "*.{{ ingress_domain }}"
      tls:
        mode: Passthrough
      allowedRoutes:
        namespaces:
          from: Same

    # ── TLS passthrough: peer gRPC API (port 7051) ─────────────────────────
    - name: peer-passthrough
      port: "{{ ingress_grpc_peer_port }}"
      protocol: TLS
      hostname: "*.{{ ingress_domain }}"
      tls:
        mode: Passthrough
      allowedRoutes:
        namespaces:
          from: Same
```

> **Note on `hostname` in `TLSRoute`:** SNI matching in a passthrough listener
> uses the `sniHosts` field on the `TLSRoute` resource (see W7), not the Gateway
> `hostname` field. The `hostname` wildcard on the listener is a pre-filter; the
> precise backend selection happens in the route.

#### 5.2.2 Wait for Gateway to be programmed

Add to `roles/fabric_operator_crds/tasks/k8s/create.yml`:

```yaml
- name: Wait for fabric Gateway to be programmed
  kubernetes.core.k8s_info:
    api_version: gateway.networking.k8s.io/v1
    kind: Gateway
    name: fabric-gateway
    namespace: "{{ namespace }}"
  register: gw_info
  until: >
    gw_info.resources | length > 0 and
    (gw_info.resources[0].status.conditions |
     selectattr('type','equalto','Programmed') |
     selectattr('status','equalto','True') | list | length) > 0
  retries: 60
  delay: 5
  when: ingress_type == 'gateway-api'
```

---

### 5.3 W3 — CoreDNS override

**File:** `roles/fabric_operator_crds/templates/k8s/coredns/coredns.yaml.j2`

No structural change required. The template already uses `{{ clusterip }}` as the
single variable. What changes is the Ansible task that populates it.

**File:** `roles/fabric_operator_crds/tasks/k8s/create.yml`

Replace the single ClusterIP lookup task with a conditional:

```yaml
# [NGINX] Resolve nginx controller ClusterIP
- name: Get ingress-nginx controller ClusterIP
  kubernetes.core.k8s_info:
    api_version: v1
    kind: Service
    name: ingress-nginx-controller
    namespace: ingress-nginx
  register: nginx_svc
  when: ingress_type == 'nginx'

- name: Set clusterip from nginx service
  set_fact:
    clusterip: "{{ nginx_svc.resources[0].spec.clusterIP }}"
  when: ingress_type == 'nginx'

# [GW] Resolve Envoy Gateway LoadBalancer / ClusterIP
- name: Get Envoy Gateway service ClusterIP
  kubernetes.core.k8s_info:
    api_version: v1
    kind: Service
    name: envoy-fabric-gateway   # Name follows pattern: envoy-<gateway-name>
    namespace: "{{ namespace }}"
  register: envoy_svc
  when: ingress_type == 'gateway-api'

- name: Set clusterip from Envoy Gateway service
  set_fact:
    clusterip: "{{ envoy_svc.resources[0].spec.clusterIP }}"
  when: ingress_type == 'gateway-api'

# [BOTH] Apply CoreDNS override
- name: Apply CoreDNS wildcard override
  kubernetes.core.k8s:
    state: present
    resource_definition: "{{ lookup('template',
      'templates/k8s/coredns/coredns.yaml.j2') }}"
```

> **Note on the Envoy Gateway service name:** Envoy Gateway creates one `Service`
> per `Gateway` resource, named `envoy-<gateway-namespace>-<gateway-name>` (or
> `envoy-<gateway-name>` when the gateway is in the same namespace as the
> controller). Confirm the exact name against the Envoy Gateway version pinned in
> `envoy_gateway_kustomize_ref` and expose it as a variable
> `envoy_gateway_service_name` if the naming convention changes between releases.

---

### 5.4 W4 — RBAC extension

Both cluster role templates must be extended to include Gateway API resource
groups alongside the existing `networking.k8s.io/ingresses` entry.

**Files:**
- `roles/fabric_operator_crds/templates/k8s/rbac/hlf-operator-clusterrole.yaml`
- `roles/hlfsupport_console/templates/k8s/cluster_role.yml.j2`

Add the following rule block to each (after the existing
`extensions / networking.k8s.io` block):

```yaml
  - apiGroups:
      - gateway.networking.k8s.io
    resources:
      - gateways
      - gatewayclasses
      - httproutes
      - tlsroutes
      - referencegrants
    verbs:
      - get
      - list
      - create
      - update
      - patch
      - watch
      - delete
      - deletecollection
```

This rule is **additive and harmless** when `ingress_type == 'nginx'`: if the
Gateway API CRDs are not installed, the rules are simply never exercised.
Therefore this change can be applied unconditionally to both paths.

---

### 5.5 W5 — Console wait logic

**File:** `roles/hlfsupport_console/tasks/k8s/create.yml`

The current wait task (lines 146–169) queries `networking.k8s.io/v1 Ingress` and
reads the console URL from `spec.rules[0].host`. Under Gateway API the console URL
is determined by the `HTTPRoute`'s `hostnames` field.

Replace the three tasks (wait for ingress, set URL, wait for ingress to start) with
a conditional block:

```yaml
# [NGINX] Wait for console Ingress and derive URL
- name: Wait for console Ingress to exist
  kubernetes.core.k8s_info:
    namespace: "{{ namespace }}"
    api_version: networking.k8s.io/v1
    kind: Ingress
    name: "{{ console }}"
  register: console_route
  until: console_route.resources
  retries: "{{ wait_timeout }}"
  delay: 1
  when: ingress_type == 'nginx'

- name: Set console URL from Ingress
  set_fact:
    console_url: "https://{{ console_route.resources[0].spec.rules[0].host }}"
  when: ingress_type == 'nginx'

# [GW] Wait for console HTTPRoute and derive URL
- name: Wait for console HTTPRoute to exist
  kubernetes.core.k8s_info:
    namespace: "{{ namespace }}"
    api_version: gateway.networking.k8s.io/v1
    kind: HTTPRoute
    name: "{{ console }}"
  register: console_httproute
  until: console_httproute.resources
  retries: "{{ wait_timeout }}"
  delay: 1
  when: ingress_type == 'gateway-api'

- name: Set console URL from HTTPRoute
  set_fact:
    console_url: "https://{{ console_httproute.resources[0].spec.hostnames[0] }}"
  when: ingress_type == 'gateway-api'

# [BOTH] Health-check the console
- name: Wait for console to respond
  uri:
    url: "{{ console_url }}"
    status_code: "200"
    validate_certs: no
  register: result
  until: result.status == 200
  retries: "{{ wait_timeout }}"
  delay: 1

- name: Print console URL
  debug:
    msg: "Fabric Operations Console available at {{ console_url }}"
```

The same pattern applies to the equivalent block in
`roles/fabric_console/tasks/k8s/create.yml` (line 57), which currently only
prints a URL without waiting for an Ingress resource.

---

### 5.6 W6 — CI bootstrap

**File:** `.github/scripts/kind_with_nginx.sh` — keep as-is, renamed to make its
scope explicit.

**New file:** `.github/scripts/kind_with_envoy_gateway.sh`

```bash
#!/usr/bin/env bash
# Sets up a KIND cluster with Envoy Gateway for Gateway API integration tests.
# Replaces kind_with_nginx.sh when ingress_type=gateway-api.
set -eo pipefail

KIND_CLUSTER_NAME=${KIND_CLUSTER_NAME:-kind}
KIND_CLUSTER_IMAGE=${KIND_CLUSTER_IMAGE:-kindest/node:v1.29.0}
KIND_API_SERVER_ADDRESS=${KIND_API_SERVER_ADDRESS:-127.0.0.1}
KIND_API_SERVER_PORT=${KIND_API_SERVER_PORT:-8888}
ENVOY_GATEWAY_VERSION=${ENVOY_GATEWAY_VERSION:-v1.2.0}

function kind_with_envoy_gateway() {
  delete_cluster
  create_cluster
  install_gateway_api_crds
  install_envoy_gateway
  apply_gatewayclass_and_gateway
  apply_coredns_override
}

function delete_cluster() {
  kind delete cluster --name "$KIND_CLUSTER_NAME" || true
}

function create_cluster() {
  cat <<EOF | kind create cluster --name "$KIND_CLUSTER_NAME" \
                                   --image "$KIND_CLUSTER_IMAGE" --config=-
---
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - containerPort: 443
        hostPort: 443
        protocol: TCP
      - containerPort: 7050       # orderer gRPC passthrough
        hostPort: 7050
        protocol: TCP
      - containerPort: 7051       # peer gRPC passthrough
        hostPort: 7051
        protocol: TCP
networking:
  apiServerAddress: ${KIND_API_SERVER_ADDRESS}
  apiServerPort: ${KIND_API_SERVER_PORT}
EOF
}

function install_gateway_api_crds() {
  # Install the standard Gateway API CRDs (includes TLSRoute as experimental)
  kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/experimental-install.yaml
  kubectl wait --for condition=established \
    crd/gateways.gateway.networking.k8s.io \
    crd/httproutes.gateway.networking.k8s.io \
    crd/tlsroutes.gateway.networking.k8s.io \
    --timeout=60s
}

function install_envoy_gateway() {
  helm install eg oci://docker.io/envoyproxy/gateway-helm \
    --version "${ENVOY_GATEWAY_VERSION}" \
    -n envoy-gateway-system --create-namespace
  kubectl -n envoy-gateway-system rollout status deploy envoy-gateway \
    --timeout=120s
}

function apply_gatewayclass_and_gateway() {
  kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: fabric-envoy-gateway
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
EOF

  # Gateway is created by the Ansible role during the test run.
  # Wait for the GatewayClass to be Accepted first.
  kubectl wait --for=condition=Accepted \
    gatewayclass/fabric-envoy-gateway --timeout=60s
}

function apply_coredns_override() {
  # After the Gateway is Programmed (done by Ansible), resolve its ClusterIP.
  # For CI, we poll until the envoy service appears.
  local CLUSTER_IP=""
  for i in $(seq 1 30); do
    CLUSTER_IP=$(kubectl -n oss-hlf-infra get svc \
      -l "gateway.envoyproxy.io/owning-gateway-name=fabric-gateway" \
      -o jsonpath='{.items[0].spec.clusterIP}' 2>/dev/null || true)
    [ -n "$CLUSTER_IP" ] && break
    sleep 5
  done

  kubectl apply -f - <<EOF
---
kind: ConfigMap
apiVersion: v1
metadata:
  name: coredns
  namespace: kube-system
data:
  Corefile: |
    .:53 {
        errors
        health { lameduck 5s }
        ready
        rewrite name regex (.*)\.localho\.st host.ingress.internal
        hosts {
          ${CLUSTER_IP} host.ingress.internal
          fallthrough
        }
        kubernetes cluster.local in-addr.arpa ip6.arpa {
           pods insecure
           fallthrough in-addr.arpa ip6.arpa
           ttl 30
        }
        prometheus :9153
        forward . /etc/resolv.conf { max_concurrent 1000 }
        cache 30
        loop
        reload
        loadbalance
    }
EOF
  kubectl -n kube-system rollout restart deployment/coredns
}

kind_with_envoy_gateway

mkdir -p _cfg
kubectl config view --raw > _cfg/k8s_context.yaml
```

**File:** `.github/workflows/fvtest.yml` (and `main.yml`)

Add a matrix dimension `ingress_type: [nginx, gateway-api]` so both paths are
exercised in CI:

```yaml
strategy:
  matrix:
    ingress_type: [nginx, gateway-api]
steps:
  - name: Bootstrap cluster
    run: |
      if [ "${{ matrix.ingress_type }}" = "gateway-api" ]; then
        .github/scripts/kind_with_envoy_gateway.sh
      else
        .github/scripts/kind_with_nginx.sh
      fi
  - name: Run integration tests
    env:
      INGRESS_TYPE: ${{ matrix.ingress_type }}
    run: .github/scripts/run-integration-tests.sh
```

---

### 5.7 W7 — Route resources (post-operator overlay)

This is the most complex workstream. It exists because the `fabric-operator`
currently creates `networking.k8s.io/v1 Ingress` objects automatically when
reconciling `IBPPeer`, `IBPOrderer`, `IBPCA`, and `IBPConsole`. Under Gateway API
those `Ingress` objects are harmless but insufficient; we need `HTTPRoute` and
`TLSRoute` resources instead.

**Strategy for the first iteration:** an Ansible post-task that reads the
operator-created resources and creates the corresponding Gateway API routes.
This is a transitional overlay, not the end-state. A follow-up upstream PR to
`fabric-operator` should add native Gateway API support behind a
`INGRESS_CLASS=gateway` environment variable.

#### 5.7.1 Template: `HTTPRoute` for console, CA, gRPC-Web, and operations

**New file:** `roles/fabric_console/templates/k8s/gateway/httproute.yaml.j2`

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: "{{ component_name }}"
  namespace: "{{ namespace }}"
spec:
  parentRefs:
    - name: fabric-gateway
      sectionName: https
  hostnames:
    - "{{ component_hostname }}"
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: "{{ component_service }}"
          port: "{{ component_service_port }}"
```

#### 5.7.2 Template: `TLSRoute` for peer gRPC API

**New file:** `roles/endorsing_organization/templates/k8s/gateway/tlsroute-peer.yaml.j2`

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TLSRoute
metadata:
  name: "{{ peer_name | lower | replace(' ', '-') }}-api"
  namespace: "{{ namespace }}"
spec:
  parentRefs:
    - name: fabric-gateway
      sectionName: peer-passthrough
  hostnames:
    - "{{ peer_api_hostname }}"    # SNI match, e.g. org1peer-api.localho.st
  rules:
    - backendRefs:
        - name: "{{ peer_service }}"
          port: 7051
```

#### 5.7.3 Template: `TLSRoute` for orderer gRPC API

**New file:** `roles/ordering_organization/templates/k8s/gateway/tlsroute-orderer.yaml.j2`

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TLSRoute
metadata:
  name: "{{ orderer_name | lower | replace(' ', '-') }}-api"
  namespace: "{{ namespace }}"
spec:
  parentRefs:
    - name: fabric-gateway
      sectionName: orderer-passthrough
  hostnames:
    - "{{ orderer_api_hostname }}"   # SNI match, e.g. orderingservice1-api.localho.st
  rules:
    - backendRefs:
        - name: "{{ orderer_service }}"
          port: 7050
```

#### 5.7.4 Post-task in endorsing_organization

**File:** `roles/endorsing_organization/tasks/create.yml`

After the existing peer creation tasks, add:

```yaml
- name: Create Gateway API TLSRoute for peer gRPC API
  kubernetes.core.k8s:
    state: present
    namespace: "{{ namespace }}"
    resource_definition: "{{ lookup('template',
      'templates/k8s/gateway/tlsroute-peer.yaml.j2') }}"
  when: ingress_type == 'gateway-api'
  vars:
    peer_api_hostname: "{{ peer_api_url | urlsplit('hostname') }}"
    peer_service: "{{ peer_name | lower | replace(' ', '-') }}"
```

#### 5.7.5 Post-task in ordering_organization

**File:** `roles/ordering_organization/tasks/create.yml`

Same pattern:

```yaml
- name: Create Gateway API TLSRoute for orderer gRPC API
  kubernetes.core.k8s:
    state: present
    namespace: "{{ namespace }}"
    resource_definition: "{{ lookup('template',
      'templates/k8s/gateway/tlsroute-orderer.yaml.j2') }}"
  when: ingress_type == 'gateway-api'
  vars:
    orderer_api_hostname: "{{ orderer_api_url | urlsplit('hostname') }}"
    orderer_service: "{{ ordering_service_name | lower | replace(' ', '-') }}"
```

#### 5.7.6 Upstream contribution target

File a PR against `hyperledger-labs/fabric-operator` proposing:
- A new env var `INGRESS_CLASS` with values `nginx` (default) and `gateway-api`.
- When `INGRESS_CLASS=gateway-api`, the operator reconciler emits `HTTPRoute` +
  `TLSRoute` instead of `Ingress` objects.
- The operator's `ClusterRole` is extended to include `gateway.networking.k8s.io`
  verbs (mirrors W4 above).

Until that PR is merged, W7's post-task overlay is the supported path.

---

### 5.8 W8 — Documentation

#### Files to update

| File | Change |
|------|--------|
| `docs/source/tutorials/oss-installing.rst` | Add Gateway API installation path; replace IKS/nginx SSL passthrough note with Gateway API equivalent |
| `docs/source/tutorials/hlfsupport-installing.rst` | Same |
| `docs/source/roles/fabric-operator-crds.rst` | Add `ingress_type` parameter documentation; update "Ingress Controllers" section |
| `docs/source/roles/fabric-console.rst` | Same |
| `docs/source/roles/hlfsupport_console.rst` | Same |

#### New pages to create

| File | Content |
|------|---------|
| `docs/source/tutorials/gateway-api-install.rst` | Step-by-step: install KIND, Envoy Gateway, bootstrap a Fabric network with `ingress_type: gateway-api` |
| `docs/source/tutorials/migrate-nginx-to-gateway.rst` | Upgrade guide for existing nginx-based deployments |

#### Key content for `gateway-api-install.rst`

The tutorial must explain:

1. The three-listener Gateway model and why ports 443 / 7050 / 7051 are chosen.
2. That `api_url` for peers now resolves to port 7051 and for orderers to port 7050.
3. That `grpcwp_url`, `operations_url`, and CA `api_url` remain on port 443.
4. The `kubectl get gateway -n <namespace>` command to verify the Gateway is
   programmed (replacing the `kubectl get ingress` instructions in the current docs).
5. The `localho.st` wildcard DNS trick and the CoreDNS override — unchanged
   conceptually, but now pointing at the Envoy Gateway service.

---

## 6. `api_url` port change impact analysis

The port change for `api_url` values touches the following files.
Each must be updated in its Gateway API conditional branch (not globally).

| File | Current sample port | New port (GW path) |
|------|--------------------|--------------------|
| `plugins/modules/peer.py` line 533 | `:32000` | `:7051` |
| `plugins/modules/peer_info.py` line 97 | `:32000` | `:7051` |
| `plugins/modules/ordering_service_node.py` line 422 | `:32000` | `:7050` |
| `plugins/modules/ordering_service_node_info.py` line 94 | `:32000` | `:7050` |
| `plugins/modules/ordering_service.py` line 339 | `:32000` | `:7050` |
| `plugins/modules/ordering_service_info.py` line 95 | `:32000` | `:7050` |
| `plugins/modules/external_ordering_service_node.py` line 179 | `:32000` | `:7050` |
| `plugins/modules/external_peer.py` line 161 | `:32000` | `:7051` |
| `plugins/module_utils/url_utils.py` | hard-codes `:443` as normalised port | Extend to handle `:7050`/`:7051` as protocol-native ports |
| `tests/integration/.../one_node_ordering_service.json.j2` line 3 | `:443` | `:7050` |
| `tutorial/ordering-org-vars.yml` | `api_endpoint: https://....:32000` | Port comment only; actual URL set at runtime by operator |
| `tutorial/org1-vars.yml` | Same | Same |

`url_utils.py` — [`translate_url_to_os_format()`](../../plugins/module_utils/url_utils.py:8) —
currently hard-codes `'443'` as the canonical port in the "os format". It must be
updated to accept an optional `canonical_port` argument (defaulting to `'443'` for
backwards compatibility) so callers in `peer_metadata.py` and
`ordering_service_node_metadata.py` can pass `'7051'` / `'7050'` when
`ingress_type == 'gateway-api'`.

---

## 7. Deprecation and sunset timeline

| Milestone | Action |
|-----------|--------|
| **v2.1 (this plan)** | `ingress_type: nginx` is the default. `ingress_type: gateway-api` is available as beta. Deprecation notice added to nginx path documentation. |
| **v2.2** | `ingress_type: gateway-api` promoted to stable. Nginx path still supported but produces an `ansible.builtin.warn`. |
| **v2.3** | Nginx path removed. `ingress_type` default changed to `gateway-api`. |

The timeline assumes upstream `fabric-operator` Gateway API support lands by v2.2;
otherwise v2.2 is delayed until the overlay in W7 is replaced by native operator
support.

---

## 8. Acceptance criteria

A migration is considered complete when all of the following pass:

1. **[BOTH]** `ansible-lint` and `yamllint` pass on all modified files.
2. **[NGINX]** All existing integration tests pass with `ingress_type: nginx`
   (or unset) without modification.
3. **[GW]** A KIND cluster bootstrapped with `kind_with_envoy_gateway.sh` and
   `ingress_type: gateway-api` passes the full integration test suite.
4. **[GW]** Peer `api_url` resolves to port 7051; orderer `api_url` resolves to
   port 7050; both reach their pod TLS stack without termination at the gateway
   (verified by comparing the TLS certificate presented at the gateway address
   against the `tls_cert` stored in the console).
5. **[GW]** Console and CA HTTPS endpoints are TLS-terminated at the gateway
   (verified by inspecting the serving certificate CN).
6. **[GW]** A `fabric-sdk-py` channel join and peer query succeed end-to-end over
   the Gateway API path.
7. **[BOTH]** Documentation builds without warnings (`make -C docs html`).
