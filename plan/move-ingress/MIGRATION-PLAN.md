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

## 1.1 Design constraint: the ingress controller is a prerequisite, not a role task

The `fabric_operator_crds` role **does not install any ingress controller**. This
is the current, documented, intentional design:

> *"This role does not install an ingress controller."*
> — `docs/source/roles/fabric-operator-crds.rst`

ingress-nginx is installed exclusively by the CI shell script
`.github/scripts/kind_with_nginx.sh`, which runs **before** any Ansible playbook
in the `fvtest.yml` workflow. The CoreDNS wildcard override is also applied by
that same shell script — the Jinja2 template at
`roles/fabric_operator_crds/templates/k8s/coredns/coredns.yaml.j2` exists but
is not wired to any Ansible task.

For end-users on managed cloud clusters (IKS, EKS, GKE), the documentation
directs them to install and configure a compatible ingress controller manually
before running any collection playbook.

**This plan preserves that boundary without exception.** The migration
introduces:

- A new CI bootstrap script `kind_with_envoy_gateway.sh` to replace
  `kind_with_nginx.sh` for the Gateway API path.
- Updated prerequisite documentation telling users what to install before
  using `ingress_type: gateway-api`.
- **Zero changes** to the task entry points of `fabric_operator_crds`,
  `fabric_console`, `endorsing_organization`, or `ordering_organization` for
  gateway controller installation.

Workstreams W2 (Gateway installation templates) and W3 (CoreDNS override) are
therefore **CI script and documentation work only** — not Ansible role work.

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
| Fabric CA — API + Operations | HTTPS REST | **7054** | TLS passthrough |
| Fabric Operations Console | HTTPS | **443** (via `IBPConsole`) | HTTPS reverse-proxy |
| Fabric Operator | Internal health only (`:8383` TCP) | — | **Not ingress-routed** |
| CRD Webhook (hlfsupport) | HTTPS (`:3000` container → `:443` ClusterIP) | — | **Not ingress-routed** (ClusterIP only) |
| gRPC-Web proxy (`grpc-web` sidecar) | HTTP/1.1 + WebSocket | **443** (sidecar) | HTTPS reverse-proxy |

### 2.2 Gateway listener topology

Under the Gateway API path, a single `Gateway` resource carries **four listeners**,
each covering one protocol class. SNI within each passthrough listener distinguishes
individual nodes.

| Listener name | External port | Protocol mode | Serves |
|---------------|--------------|---------------|--------|
| `https` | **443** | `HTTPS` — TLS terminated at gateway | Console, gRPC-Web proxy, Orderer OSN Admin, Peer Operations |
| `ca-passthrough` | **7054** | `TLS` — Passthrough | All Fabric CA API and operations endpoints |
| `orderer-passthrough` | **7050** | `TLS` — Passthrough | All orderer gRPC API endpoints |
| `peer-passthrough` | **7051** | `TLS` — Passthrough | All peer gRPC API endpoints |

This means:
- `api_url` for orderers changes from `grpcs://<host>:443` (or `:32000`) to `grpcs://<host>:7050`.
- `api_url` for peers changes to `grpcs://<host>:7051`.
- CA `api_url` and `operations_url` use TLS passthrough on `:7054`.
- `grpcwp_url`, peer and orderer `operations_url`, and console URLs remain on `:443`.

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
| W1 | Variable abstraction + defaults | `fabric_operator_crds` role defaults | None |
| W2 | CI bootstrap script (Gateway API) | `.github/scripts/` new shell script | None |
| W3 | CI workflow matrix | `.github/workflows/fvtest.yml` | W2 |
| W4 | RBAC extension | All cluster role templates | W1 |
| W5 | Console wait logic | `hlfsupport_console` role | W1 |
| W6 | Route resources (post-operator overlay) | New Ansible role templates + tasks | W2, upstream |
| W7 | Documentation | `docs/` | All |

---

## 5. Detailed task specifications

### 5.1 W1 — Variable abstraction

**File:** `roles/fabric_operator_crds/defaults/main.yml`

Add `ingress_type: nginx` as a new default. Also add `ingress_ca_port`,
`ingress_grpc_orderer_port`, `ingress_grpc_peer_port`, `gateway_class_name`, and the per-service `expose_*`
boolean flags derived from the exposition analysis in PRE-ANALYSIS §2.4:

```yaml
# Ingress controller type: nginx | gateway-api
ingress_type: nginx

# Gateway API path only: the GatewayClass name installed as a cluster prerequisite.
# The default targets Envoy Gateway (CI/PoC). Set this to the name of a
# GatewayClass provisioned by the selected conformant implementation.
gateway_class_name: fabric-envoy-gateway

# Gateway API path only: external ports for TLS passthrough listeners.
# These must match the Gateway listener ports and the hostPort mappings
# in the KIND node configuration for local development.
ingress_ca_port: 7054
ingress_grpc_orderer_port: 7050
ingress_grpc_peer_port: 7051

# Gateway API path only: per-service exposition flags.
#
# These control which HTTPRoute / TLSRoute resources are created by W6 post-tasks.
# Defaults are production-safe (all externally-accessed services exposed).
# In-cluster deployments (Scenario A — CI pod, GitOps, trusted lead-org bootstrap)
# can set expose_ca / expose_peer / expose_orderer to false and rely on ClusterIP
# for Ansible reachability. See PRE-ANALYSIS §2.4 for the full rationale.
#
# Console is always exposed; there is no expose_console flag.
expose_ca: true             # CA api_url + operations_url on TLS passthrough :7054
expose_peer: true           # Peer api_url on TLS passthrough :7051
expose_orderer: true        # Orderer api_url on TLS passthrough :7050

# Operations endpoints (/healthz) are only needed externally when the control
# machine cannot reach the Kubernetes API for readiness checks. Default false:
# the recommended path is to use kubernetes.core.k8s_info to watch status.conditions
# instead of polling /healthz over an external gateway route.
expose_peer_operations: false
expose_orderer_operations: false

# gRPC-Web proxy route is never needed by Ansible — it is consumed by browsers
# via the Operations Console UI. Set true for human-facing deployments.
expose_grpcweb: false
```

These variables are consumed by the route-resource tasks (W6) and the console
wait-logic task (W5). **`roles/fabric_operator_crds/tasks/k8s/create.yml` is
not changed by this workstream** — it does not install any ingress controller
today and will not do so after the migration.

---

### 5.2 W2 — CI bootstrap script (Gateway API)

The ingress-nginx controller is currently installed by
`.github/scripts/kind_with_nginx.sh` before any Ansible playbook runs. The
Gateway API equivalent is a new parallel script. **The existing
`kind_with_nginx.sh` is not modified.**

**New file:** `.github/scripts/kind_with_envoy_gateway.sh`

```bash
#!/usr/bin/env bash
# Sets up a KIND cluster with Envoy Gateway for Gateway API integration tests.
# Mirrors kind_with_nginx.sh structure. Called from fvtest.yml before any
# Ansible playbook is executed.
set -eo pipefail

KIND_CLUSTER_NAME=${KIND_CLUSTER_NAME:-kind}
KIND_CLUSTER_IMAGE=${KIND_CLUSTER_IMAGE:-kindest/node:v1.29.0}
KIND_API_SERVER_ADDRESS=${KIND_API_SERVER_ADDRESS:-127.0.0.1}
KIND_API_SERVER_PORT=${KIND_API_SERVER_PORT:-8888}
CONTAINER_REGISTRY_NAME=${CONTAINER_REGISTRY_NAME:-kind-registry}
CONTAINER_REGISTRY_ADDRESS=${CONTAINER_REGISTRY_ADDRESS:-127.0.0.1}
CONTAINER_REGISTRY_PORT=${CONTAINER_REGISTRY_PORT:-5000}
ENVOY_GATEWAY_VERSION=${ENVOY_GATEWAY_VERSION:-v1.3.0}
GATEWAY_API_VERSION=${GATEWAY_API_VERSION:-v1.6.0}
GATEWAY_CLASS_NAME=${GATEWAY_CLASS_NAME:-fabric-envoy-gateway}

function kind_with_envoy_gateway() {
  delete_cluster
  create_cluster
  install_gateway_api_crds
  install_envoy_gateway
  apply_gatewayclass
  apply_coredns_override
  launch_docker_registry
}

function delete_cluster() {
  kind delete cluster --name "$KIND_CLUSTER_NAME" || true
}

function create_cluster() {
  # Four hostPort mappings: 443 (HTTPS), 7054 (CA), 7050 (orderer gRPC), 7051 (peer gRPC)
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
      - containerPort: 7054
        hostPort: 7054
        protocol: TCP
      - containerPort: 7050
        hostPort: 7050
        protocol: TCP
      - containerPort: 7051
        hostPort: 7051
        protocol: TCP
networking:
  apiServerAddress: ${KIND_API_SERVER_ADDRESS}
  apiServerPort: ${KIND_API_SERVER_PORT}
containerdConfigPatches:
- |-
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors."localhost:${CONTAINER_REGISTRY_PORT}"]
    endpoint = ["http://${CONTAINER_REGISTRY_NAME}:${CONTAINER_REGISTRY_PORT}"]
EOF

  for node in $(kind get nodes --name "$KIND_CLUSTER_NAME"); do
    docker exec "$node" sysctl net.ipv4.conf.all.route_localnet=1
  done
}

function install_gateway_api_crds() {
  # TLSRoute is Standard in Gateway API v1.6 — standard channel is sufficient.
  kubectl apply -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"
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

function apply_gatewayclass() {
  # Only the GatewayClass is applied here. The Gateway resource itself is
  # created by the Ansible playbook, since it carries namespace and domain
  # variables that are not known at bootstrap time.
  # GATEWAY_CLASS_NAME overrides the name of the Envoy Gateway GatewayClass.
  # Other implementations must provision their own GatewayClass.
  kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: ${GATEWAY_CLASS_NAME}
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
EOF
  kubectl wait --for=condition=Accepted \
    gatewayclass/"${GATEWAY_CLASS_NAME}" --timeout=60s
}

function apply_coredns_override() {
  # Mirror of kind_with_nginx.sh:apply_coredns_override().
  # Resolves the ClusterIP of the Envoy-provisioned service for the Gateway.
  # The Gateway must have been created (by the test playbook) before this runs,
  # so the CI workflow must call apply_coredns_override() after the playbook step,
  # or poll until the service appears.
  local CLUSTER_IP=""
  for i in $(seq 1 30); do
    CLUSTER_IP=$(kubectl get svc -A \
      -l "gateway.envoyproxy.io/owning-gateway-name=fabric-gateway" \
      -o jsonpath='{.items[0].spec.clusterIP}' 2>/dev/null || true)
    [ -n "$CLUSTER_IP" ] && break
    sleep 5
  done

  cat <<EOF | kubectl apply -f -
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

function launch_docker_registry() {
  # Identical to kind_with_nginx.sh:launch_docker_registry()
  local running
  running="$(docker inspect -f '{{.State.Running}}' "${CONTAINER_REGISTRY_NAME}" 2>/dev/null || true)"
  if [ "${running}" != 'true' ]; then
    docker run --detach --restart always \
      --name "${CONTAINER_REGISTRY_NAME}" \
      --publish "${CONTAINER_REGISTRY_ADDRESS}:${CONTAINER_REGISTRY_PORT}:${CONTAINER_REGISTRY_PORT}" \
      registry:2
  fi
  docker network connect "kind" "${CONTAINER_REGISTRY_NAME}" || true
  cat <<EOF | kubectl apply -f -
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: local-registry-hosting
  namespace: kube-public
data:
  localRegistryHosting.v1: |
    host: "localhost:${CONTAINER_REGISTRY_PORT}"
    help: "https://kind.sigs.k8s.io/docs/user/local-registry/"
EOF
}

kind_with_envoy_gateway

mkdir -p _cfg
kubectl config view --raw > _cfg/k8s_context.yaml
```

> **Note on CoreDNS timing:** The CoreDNS override in `kind_with_nginx.sh` can
> run immediately after nginx starts because nginx has a stable ClusterIP as
> soon as the controller pod is ready. With Envoy Gateway, the per-Gateway
> Envoy service is only created *after* a `Gateway` resource is applied (which
> happens in the user's Ansible playbook). The CI workflow (W3) must therefore
> split the bootstrap into two phases: (1) cluster + Envoy Gateway install
> before the playbook, (2) CoreDNS override after the playbook has applied the
> `Gateway` resource. The `apply_coredns_override()` function above handles this
> by polling until the service label appears.

---

### 5.3 W3 — CI workflow matrix and test runner

This workstream covers two files that must change together: the GitHub Actions
workflow (`.github/workflows/fvtest.yml`) and the test runner script
(`.github/scripts/run-tests.sh`). A careful audit of the existing code reveals
several issues in both files that must be fixed before the matrix can work.

#### 5.3.1 Existing problems in `run-tests.sh`

The current `run-tests.sh` has three bugs that make it unusable for either path:

1. **Crashes immediately with `set -euo pipefail`**: the script opens with
   `TYPE=$1` / `TARGET=$2` but `fvtest.yml` calls it with no arguments. The
   `pipefail` + `nounset` combination causes an immediate `unbound variable` exit.

2. **Does not inject connection vars into the tutorial playbooks**: the workflow
   writes `console_domain` and (for the gateway path) `ingress_type` + `expose_*`
   to `_cfg/domain.yml`, but no tutorial playbook's `vars_files:` list includes
   that file. The playbooks still use their hardcoded placeholder values
   (`api_endpoint: https://ibp-console.example.org:32000`, etc.).

3. **Does not stamp unique run IDs**: parallel test runs on a shared console
   collide because component names are fixed. The more complete
   `run-tutorial-tests.sh` already handles this with `yq` patching; `run-tests.sh`
   does not.

The correct mechanism — used by `run-tutorial-tests.sh` — is:
- Patch the tutorial `vars` files in place with `yq` using env vars set by the
  workflow step.
- Write `ingress_type` and `expose_*` into `common-vars.yml` with `yq` (the same
  pattern used for connection vars), because every tutorial playbook declares
  `common-vars.yml` in its `vars_files:` list.  No custom env var or wrapper is
  needed; Ansible's standard variable loading picks them up automatically.

#### 5.3.2 CoreDNS timing constraint (Gateway API path)

With nginx, CoreDNS can be applied immediately after the controller is ready,
because nginx has a stable `ClusterIP` from the moment its `Service` is created.
With Envoy Gateway, the per-namespace Envoy proxy `Service` is only created after
a `Gateway` resource exists — which happens during the Ansible playbook run (W5).

The consequence is a **sequencing dependency** that cannot be handled by a simple
post-playbook step in the workflow:

```
Bootstrap → [Run all playbooks] → Apply CoreDNS → [Continue playbooks]
```

This is not how the test runner works — the playbooks run as a single sequential
shell invocation. The correct solution is to split the test run at the point where
the `Gateway` resource has been created (i.e. after `01-create-ordering-organization-components.yml`
has applied the `fabric-gateway` resource) and insert the CoreDNS override between
the two halves. The test runner is responsible for this split on the gateway-api
path.

#### 5.3.3 Replacement `run-tests.sh`

**File:** `.github/scripts/run-tests.sh`

Replace the current broken script entirely:

```bash
#!/usr/bin/env bash
# Copyright the Hyperledger Fabric contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Runs the full tutorial test suite against a pre-bootstrapped KIND cluster.
#
# Required environment variables (set by the CI workflow bootstrap step):
#   API_ENDPOINT   – Console HTTPS URL, e.g. https://10-0-0-1.nip.io:443
#   API_AUTHTYPE   – basic
#   API_KEY        – console username / API key
#   API_SECRET     – console password / API secret
#   K8S_NAMESPACE  – Kubernetes namespace for Fabric components
#
# Optional:
#   INGRESS_TYPE             – nginx | gateway-api  (default: nginx)
#   EXPOSE_CA                – true | false         (default: true)
#   EXPOSE_PEER              – true | false         (default: true)
#   EXPOSE_ORDERER           – true | false         (default: true)
#   EXPOSE_PEER_OPERATIONS   – true | false         (default: true, CI Scenario B)
#   EXPOSE_ORDERER_OPERATIONS– true | false         (default: true, CI Scenario B)
#   EXPOSE_GRPCWEB           – true | false         (default: false)
#
# See PRE-ANALYSIS §2.5.3 for why the operations defaults are true in CI
# even though the production role default is false.

set -euo pipefail

INGRESS_TYPE=${INGRESS_TYPE:-nginx}
EXPOSE_CA=${EXPOSE_CA:-true}
EXPOSE_PEER=${EXPOSE_PEER:-true}
EXPOSE_ORDERER=${EXPOSE_ORDERER:-true}
EXPOSE_PEER_OPERATIONS=${EXPOSE_PEER_OPERATIONS:-true}
EXPOSE_ORDERER_OPERATIONS=${EXPOSE_ORDERER_OPERATIONS:-true}
EXPOSE_GRPCWEB=${EXPOSE_GRPCWEB:-false}

# Unique run ID prevents name collisions when multiple runs share a console.
TEST_RUN_ID=$(dd if=/dev/urandom bs=4096 count=1 2>/dev/null | shasum | awk '{print $1}')
SHORT_TEST_RUN_ID=$(echo "${TEST_RUN_ID}" | awk '{print substr($1,1,8)}')

pushd tutorial

# --- 1. Patch unique component names into shared vars files ---
yq -yi ".ordering_org_name=\"Ordering Org ${SHORT_TEST_RUN_ID}\""            common-vars.yml
yq -yi ".ordering_service_name=\"Ordering Service ${SHORT_TEST_RUN_ID}\""    common-vars.yml
yq -yi ".org1_name=\"Org1 ${SHORT_TEST_RUN_ID}\""                            common-vars.yml
yq -yi ".org1_msp_id=\"Org1${SHORT_TEST_RUN_ID}MSP\""                        common-vars.yml
yq -yi ".org2_name=\"Org2 ${SHORT_TEST_RUN_ID}\""                            common-vars.yml
yq -yi ".org2_msp_id=\"Org2${SHORT_TEST_RUN_ID}MSP\""                        common-vars.yml
yq -yi ".ordering_service_msp=\"Orderer${SHORT_TEST_RUN_ID}MSP\""             ordering-org-vars.yml
yq -yi ".org1_ca_name=\"Org1 CA ${SHORT_TEST_RUN_ID}\""                       org1-vars.yml
yq -yi ".org1_peer_name=\"Org1 Peer ${SHORT_TEST_RUN_ID}\""                   org1-vars.yml
yq -yi ".org2_ca_name=\"Org2 CA ${SHORT_TEST_RUN_ID}\""                       org2-vars.yml
yq -yi ".org2_peer_name=\"Org2 Peer ${SHORT_TEST_RUN_ID}\""                   org2-vars.yml

# --- 2. Inject connection info and namespace into per-org vars files ---
# These values come from the CI environment (set by the workflow bootstrap step).
for VARS_FILE in ordering-org-vars.yml org1-vars.yml org2-vars.yml; do
    yq -yi ".api_endpoint=\"${API_ENDPOINT}\""   "${VARS_FILE}"
    yq -yi ".api_authtype=\"${API_AUTHTYPE}\""   "${VARS_FILE}"
    yq -yi ".api_key=\"${API_KEY}\""             "${VARS_FILE}"
    yq -yi ".api_secret=\"${API_SECRET}\""       "${VARS_FILE}"
    yq -yi ".api_timeout=300"                    "${VARS_FILE}"
    yq -yi ".k8s_namespace=\"${K8S_NAMESPACE}\"" "${VARS_FILE}"
    yq -yi ".wait_timeout=1800"                  "${VARS_FILE}"
done

# --- 3. Write ingress_type and expose_* flags into common-vars.yml ---
# common-vars.yml is listed in vars_files: of every tutorial playbook, so writing
# these values there is the standard, documented way to pass global vars without
# modifying any playbook file or wrapping ansible-playbook.
# (ansible-playbook -e @<file> also works per the Ansible CLI docs, but requires
# patching every call site; writing to common-vars.yml avoids that.)
yq -yi ".ingress_type=\"${INGRESS_TYPE}\""                           common-vars.yml
yq -yi ".expose_ca=${EXPOSE_CA}"                                     common-vars.yml
yq -yi ".expose_peer=${EXPOSE_PEER}"                                 common-vars.yml
yq -yi ".expose_orderer=${EXPOSE_ORDERER}"                           common-vars.yml
yq -yi ".expose_peer_operations=${EXPOSE_PEER_OPERATIONS}"           common-vars.yml
yq -yi ".expose_orderer_operations=${EXPOSE_ORDERER_OPERATIONS}"     common-vars.yml
yq -yi ".expose_grpcweb=${EXPOSE_GRPCWEB}"                           common-vars.yml

# --- 4. Cleanup trap ---
function cleanup {
    ./join_network.sh destroy
}
trap cleanup EXIT

# --- 5. Run the test sequence ---
# For the Gateway API path the CoreDNS override must be applied AFTER the first
# playbook has created the fabric-gateway Gateway resource (W5), because the
# Envoy-provisioned Service ClusterIP does not exist until that point.
# The COREDNS_HOOK env var lets the caller inject a shell function name that is
# called at the right moment; if unset (nginx path) it is a no-op.
COREDNS_HOOK=${COREDNS_HOOK:-}

./build_network.sh build      # creates Gateway resource during playbook 01
if [ -n "${COREDNS_HOOK}" ]; then
    "${COREDNS_HOOK}"         # apply CoreDNS override now that the Service exists
fi
./join_network.sh join
./deploy_smart_contract.sh

trap - EXIT
./join_network.sh destroy
```

> **Note on variable injection:** `ANSIBLE_EXTRA_VARS` is **not** a recognised
> Ansible environment variable and has no effect.  The standard documented
> mechanism for passing extra vars from outside a playbook is
> `ansible-playbook -e key=value` or `ansible-playbook -e @<vars-file>`
> (the `@` prefix tells Ansible to read a YAML/JSON file; see the
> [ansible-playbook CLI reference](https://docs.ansible.com/projects/ansible/latest/cli/ansible-playbook.html#cmdoption-ansible-playbook-e)).
> The `-e @<file>` form would require every call site in `build_network.sh`,
> `join_network.sh`, and `deploy_smart_contract.sh` to be patched.  Writing
> the values into `common-vars.yml` — which every playbook already declares in
> its `vars_files:` list — achieves the same result with no call-site changes
> and stays within the `run-tests.sh` scope of this workstream.

#### 5.3.4 Updated `fvtest.yml`

**File:** `.github/workflows/fvtest.yml`

Replace the existing single-job workflow:

```yaml
# Copyright the Hyperledger Fabric contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
---
name: FV Testing using KIND
on:
  workflow_dispatch:

jobs:
  fvtest:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false      # let both matrix legs complete even if one fails
      matrix:
        ingress_type: [nginx, gateway-api]
    name: FV test (${{ matrix.ingress_type }})

    steps:
      - uses: actions/checkout@v4

      - name: Use Python 3.9
        uses: actions/setup-python@v5
        with:
          python-version: "3.9"

      - uses: BSFishy/pip-action@v1
        with:
          requirements: requirements.txt

      - name: Install kind
        uses: helm/kind-action@v1.4.0
        with:
          install_only: true

      # ── nginx path ──────────────────────────────────────────────────────────
      - name: Bootstrap cluster (nginx)
        if: matrix.ingress_type == 'nginx'
        run: |
          set -xev
          export KIND_API_SERVER_ADDRESS=$(sh .github/scripts/get-host-ip.sh)
          .github/scripts/kind_with_nginx.sh
          mkdir -p _cfg
          kubectl config view --raw \
            | sed "s/127.0.0.1/$KIND_API_SERVER_ADDRESS/g" > _cfg/k8s_context.yaml
          echo "KUBECONFIG=$PWD/_cfg/k8s_context.yaml"         >> "$GITHUB_ENV"
          echo "INGRESS_TYPE=nginx"                             >> "$GITHUB_ENV"
          echo "API_ENDPOINT=https://$(echo $KIND_API_SERVER_ADDRESS \
            | tr -s '.' '-').nip.io:443"                       >> "$GITHUB_ENV"
          echo "K8S_NAMESPACE=fabricinfra"                     >> "$GITHUB_ENV"

      # ── gateway-api path ─────────────────────────────────────────────────────
      - name: Bootstrap cluster (gateway-api)
        if: matrix.ingress_type == 'gateway-api'
        run: |
          set -xev
          export KIND_API_SERVER_ADDRESS=$(sh .github/scripts/get-host-ip.sh)
          .github/scripts/kind_with_envoy_gateway.sh
          mkdir -p _cfg
          kubectl config view --raw \
            | sed "s/127.0.0.1/$KIND_API_SERVER_ADDRESS/g" > _cfg/k8s_context.yaml
          echo "KUBECONFIG=$PWD/_cfg/k8s_context.yaml"         >> "$GITHUB_ENV"
          echo "INGRESS_TYPE=gateway-api"                      >> "$GITHUB_ENV"
          echo "API_ENDPOINT=https://$(echo $KIND_API_SERVER_ADDRESS \
            | tr -s '.' '-').nip.io:443"                       >> "$GITHUB_ENV"
          echo "K8S_NAMESPACE=fabricinfra"                     >> "$GITHUB_ENV"
          # CI topology is Scenario B — all services exposed externally.
          # expose_peer_operations / expose_orderer_operations are true because
          # wait_for() polls /healthz over the external gateway (see PRE-ANALYSIS §2.5.3).
          echo "EXPOSE_CA=true"                                 >> "$GITHUB_ENV"
          echo "EXPOSE_PEER=true"                               >> "$GITHUB_ENV"
          echo "EXPOSE_ORDERER=true"                            >> "$GITHUB_ENV"
          echo "EXPOSE_PEER_OPERATIONS=true"                    >> "$GITHUB_ENV"
          echo "EXPOSE_ORDERER_OPERATIONS=true"                 >> "$GITHUB_ENV"
          echo "EXPOSE_GRPCWEB=false"                           >> "$GITHUB_ENV"

      # ── shared steps ─────────────────────────────────────────────────────────
      - name: Build and install collection
        run: |
          ansible-galaxy collection build -f
          ansible-galaxy collection install \
            "$(ls -1 | grep fabric_ansible_collection)" -f

      - name: Install Hyperledger Fabric binaries (2.4.7)
        uses: hyperledgendary/setup-hyperledger-fabric-action@v0.0.1
        with:
          version: 2.4.7

      - name: Run tests
        env:
          API_AUTHTYPE: basic
          API_KEY:    ${{ secrets.CONSOLE_API_KEY }}
          API_SECRET: ${{ secrets.CONSOLE_API_SECRET }}
        run: .github/scripts/run-tests.sh

      # Gateway API only: the CoreDNS hook is called from INSIDE run-tests.sh
      # (via COREDNS_HOOK) after the fabric-gateway Gateway resource is created.
      # No separate post-run step is needed; the hook is defined here as an
      # exported function so the sub-shell run-tests.sh invokes can call it.
      # The COREDNS_HOOK var is set only for the gateway-api leg.
      - name: Verify CoreDNS override was applied (gateway-api)
        if: matrix.ingress_type == 'gateway-api'
        run: |
          kubectl -n kube-system get configmap coredns -o yaml \
            | grep -q "host.ingress.internal"
          echo "CoreDNS override confirmed."
```

> **Note on `COREDNS_HOOK`:** Rather than inserting a separate workflow step
> between the first playbook and the rest of the test run — which would require
> splitting `run-tests.sh` externally — the script accepts a `COREDNS_HOOK` env
> var naming a shell function to call at the right moment. For the gateway-api
> matrix leg, the workflow sets:
>
> ```
> COREDNS_HOOK=apply_gateway_coredns_override
> ```
>
> and also exports the function body so `run-tests.sh`'s sub-shell inherits it:
>
> ```bash
> apply_gateway_coredns_override() {
>   source .github/scripts/kind_with_envoy_gateway.sh
>   apply_coredns_override
> }
> export -f apply_gateway_coredns_override
> ```
>
> This keeps the workflow and the test runner decoupled: the workflow defines
> *when* and *how* to apply CoreDNS for its specific implementation; the script
> just calls the hook at the right point in the test sequence.
>
> For the nginx leg, `COREDNS_HOOK` is unset and the hook call is a no-op.

#### 5.3.5 Parity table

The following table shows that both matrix legs now exercise exactly the same
test sequence with the same mechanism, and the only differences are the
infrastructure-level bootstrap step and the `expose_*` overrides:

| Step | nginx leg | gateway-api leg |
|------|-----------|----------------|
| Cluster bootstrap | `kind_with_nginx.sh` | `kind_with_envoy_gateway.sh` |
| Ingress controller | nginx (SSL passthrough) | Envoy Gateway (TLSRoute + HTTPRoute) |
| CoreDNS override | Applied inside `kind_with_nginx.sh` (immediately) | Applied via `COREDNS_HOOK` after Gateway resource is created |
| `INGRESS_TYPE` | `nginx` | `gateway-api` |
| `expose_peer_operations` | N/A (nginx always exposes all) | `true` (CI Scenario B — `wait_for()` polls via gateway) |
| `expose_orderer_operations` | N/A | `true` |
| Unique run ID stamping | ✅ `run-tests.sh` (both legs) | ✅ same |
| Connection var injection | ✅ `run-tests.sh` (both legs) | ✅ same |
| Tutorial sequence | `build_network.sh build` → `join_network.sh join` → `deploy_smart_contract.sh` | ✅ identical |
| Cleanup | `join_network.sh destroy` | ✅ identical |
| Collection build | ✅ shared step | ✅ same |
| Fabric binaries | v2.4.7 (shared step) | ✅ same |

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

### 5.5 W5 — Console wait logic and Gateway resource creation

Before the wait logic can query an `HTTPRoute`, a `Gateway` resource must exist
in the namespace. Since the gateway controller installation is a prerequisite
(§1.1), the `fabric_operator_crds` role must create the `Gateway` resource itself
when `ingress_type == 'gateway-api'`. This is the only Gateway API–related manifest
that belongs inside an Ansible role, because it is namespace-scoped and
parameterised with `ingress_domain` and `ingress_tls_secret` — values only known
at role execution time.

**New file:** `roles/fabric_operator_crds/templates/k8s/gateway/fabric-gateway.yaml.j2`

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: fabric-gateway
  namespace: "{{ namespace }}"
spec:
  gatewayClassName: "{{ gateway_class_name }}"
  listeners:
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
    - name: ca-passthrough
      port: {{ ingress_ca_port }}
      protocol: TLS
      hostname: "*.{{ ingress_domain }}"
      tls:
        mode: Passthrough
      allowedRoutes:
        namespaces:
          from: Same
    - name: orderer-passthrough
      port: {{ ingress_grpc_orderer_port }}
      protocol: TLS
      hostname: "*.{{ ingress_domain }}"
      tls:
        mode: Passthrough
      allowedRoutes:
        namespaces:
          from: Same
    - name: peer-passthrough
      port: {{ ingress_grpc_peer_port }}
      protocol: TLS
      hostname: "*.{{ ingress_domain }}"
      tls:
        mode: Passthrough
      allowedRoutes:
        namespaces:
          from: Same
```

Add to **`roles/fabric_operator_crds/tasks/k8s/create.yml`**:

```yaml
# [GW] Create the Gateway resource (namespace-scoped, domain-parameterised).
# The GatewayClass and Envoy Gateway controller are cluster-level prerequisites
# installed by the CI bootstrap script or by the cluster administrator.
- name: Create fabric Gateway resource
  kubernetes.core.k8s:
    state: present
    namespace: "{{ namespace }}"
    resource_definition: "{{ lookup('template',
      'templates/k8s/gateway/fabric-gateway.yaml.j2') }}"
  when: ingress_type == 'gateway-api'

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

This is the **only** Gateway API–related task added to
`roles/fabric_operator_crds/tasks/k8s/create.yml`. The controller itself is
never installed from within the role.

---

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

### 5.6 W6 — Route resources (post-operator overlay)

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

**Conditionality:** each route-creation task is guarded by two conditions:
1. `ingress_type == 'gateway-api'` — the overall path switch.
2. The service-specific `expose_*` flag (see W1 defaults and PRE-ANALYSIS §2.4).

This allows in-cluster deployments (Scenario A — CI pods, GitOps, or a trusted
lead-org hosting components for joining organisations) to suppress unnecessary
external routes by setting `expose_peer: false`, `expose_orderer: false`, and/or
`expose_ca: false` while still using `ingress_type: gateway-api` for the console
route (which is always created).

#### 5.6.1 Template: `HTTPRoute` for console (always created)

**New file:** `roles/fabric_console/templates/k8s/gateway/httproute-console.yaml.j2`

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
          port: {{ component_service_port }}
```

The console `HTTPRoute` task carries only `when: ingress_type == 'gateway-api'` —
there is no `expose_console` flag because the console is always required externally
(see PRE-ANALYSIS §2.4.3).

#### 5.6.2 Template: `TLSRoute` for CA API and operations (gated by `expose_ca`)

**New file:** `roles/certificate_authority/templates/k8s/gateway/tlsroute-ca.yaml.j2`

CA enrollment validates the certificate presented by the CA itself. The route must
therefore use TLS passthrough rather than terminating and re-originating TLS at the
Gateway.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: TLSRoute
metadata:
  name: "{{ ca_name | lower | replace(' ', '-') }}-api"
  namespace: "{{ namespace }}"
spec:
  parentRefs:
    - name: fabric-gateway
      sectionName: ca-passthrough
  hostnames:
    - "{{ ca_api_hostname }}"     # SNI match, e.g. org1ca-api.localho.st
  rules:
    - backendRefs:
        - name: "{{ ca_service }}"
          port: 7054
```

Post-task condition: `when: ingress_type == 'gateway-api' and expose_ca | bool`

#### 5.6.3 Template: `HTTPRoute` for operations endpoints (gated by `expose_*_operations`)

**New file:** `roles/endorsing_organization/templates/k8s/gateway/httproute-operations.yaml.j2`
(reused for both peer and orderer operations by varying `component_*` vars)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: "{{ component_name }}-operations"
  namespace: "{{ namespace }}"
spec:
  parentRefs:
    - name: fabric-gateway
      sectionName: https
  hostnames:
    - "{{ component_operations_hostname }}"   # e.g. org1peer-operations.localho.st
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: "{{ component_service }}"
          port: {{ component_operations_port }}
```

Post-task conditions:
- Peer: `when: ingress_type == 'gateway-api' and expose_peer_operations | bool`
- Orderer: `when: ingress_type == 'gateway-api' and expose_orderer_operations | bool`

When `expose_*_operations` is `false` (the default), the recommended alternative
for startup readiness is `kubernetes.core.k8s_info` watching `status.conditions`
on the `IBPPeer` / `IBPOrderer` resource — no gateway route required.

#### 5.6.4 Template: `HTTPRoute` for gRPC-Web proxy (gated by `expose_grpcweb`)

**New file:** `roles/endorsing_organization/templates/k8s/gateway/httproute-grpcweb.yaml.j2`

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: "{{ peer_name | lower | replace(' ', '-') }}-grpcweb"
  namespace: "{{ namespace }}"
spec:
  parentRefs:
    - name: fabric-gateway
      sectionName: https
  hostnames:
    - "{{ peer_grpcweb_hostname }}"   # e.g. org1peer-grpcwebproxy.localho.st
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: "{{ peer_grpcweb_service }}"
          port: 443
```

Post-task condition: `when: ingress_type == 'gateway-api' and expose_grpcweb | bool`

#### 5.6.5 Template: `TLSRoute` for peer gRPC API (gated by `expose_peer`)

**New file:** `roles/endorsing_organization/templates/k8s/gateway/tlsroute-peer.yaml.j2`

```yaml
apiVersion: gateway.networking.k8s.io/v1
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

#### 5.6.6 Template: `TLSRoute` for orderer gRPC API (gated by `expose_orderer`)

**New file:** `roles/ordering_organization/templates/k8s/gateway/tlsroute-orderer.yaml.j2`

```yaml
apiVersion: gateway.networking.k8s.io/v1
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

#### 5.6.7 Post-task in endorsing_organization

**File:** `roles/endorsing_organization/tasks/create.yml`

After the existing peer creation tasks, add (in order):

```yaml
- name: Create Gateway API TLSRoute for peer gRPC API
  kubernetes.core.k8s:
    state: present
    namespace: "{{ namespace }}"
    resource_definition: "{{ lookup('template',
      'templates/k8s/gateway/tlsroute-peer.yaml.j2') }}"
  when:
    - ingress_type == 'gateway-api'
    - expose_peer | bool
  vars:
    peer_api_hostname: "{{ peer_api_url | urlsplit('hostname') }}"
    peer_service: "{{ peer_name | lower | replace(' ', '-') }}"

- name: Create Gateway API HTTPRoute for peer operations endpoint
  kubernetes.core.k8s:
    state: present
    namespace: "{{ namespace }}"
    resource_definition: "{{ lookup('template',
      'templates/k8s/gateway/httproute-operations.yaml.j2') }}"
  when:
    - ingress_type == 'gateway-api'
    - expose_peer_operations | bool
  vars:
    component_name: "{{ peer_name | lower | replace(' ', '-') }}"
    component_operations_hostname: "{{ peer_operations_url | urlsplit('hostname') }}"
    component_service: "{{ peer_name | lower | replace(' ', '-') }}"
    component_operations_port: 9443

- name: Create Gateway API HTTPRoute for peer gRPC-Web proxy
  kubernetes.core.k8s:
    state: present
    namespace: "{{ namespace }}"
    resource_definition: "{{ lookup('template',
      'templates/k8s/gateway/httproute-grpcweb.yaml.j2') }}"
  when:
    - ingress_type == 'gateway-api'
    - expose_grpcweb | bool
  vars:
    peer_grpcweb_hostname: "{{ peer_grpcwp_url | urlsplit('hostname') }}"
    peer_grpcweb_service: "{{ peer_name | lower | replace(' ', '-') }}-grpcwebproxy"
```

#### 5.6.8 Post-task in ordering_organization

**File:** `roles/ordering_organization/tasks/create.yml`

```yaml
- name: Create Gateway API TLSRoute for orderer gRPC API
  kubernetes.core.k8s:
    state: present
    namespace: "{{ namespace }}"
    resource_definition: "{{ lookup('template',
      'templates/k8s/gateway/tlsroute-orderer.yaml.j2') }}"
  when:
    - ingress_type == 'gateway-api'
    - expose_orderer | bool
  vars:
    orderer_api_hostname: "{{ orderer_api_url | urlsplit('hostname') }}"
    orderer_service: "{{ ordering_service_name | lower | replace(' ', '-') }}"

- name: Create Gateway API HTTPRoute for orderer operations endpoint
  kubernetes.core.k8s:
    state: present
    namespace: "{{ namespace }}"
    resource_definition: "{{ lookup('template',
      'templates/k8s/gateway/httproute-operations.yaml.j2') }}"
  when:
    - ingress_type == 'gateway-api'
    - expose_orderer_operations | bool
  vars:
    component_name: "{{ ordering_service_name | lower | replace(' ', '-') }}"
    component_operations_hostname: "{{ orderer_operations_url | urlsplit('hostname') }}"
    component_service: "{{ ordering_service_name | lower | replace(' ', '-') }}"
    component_operations_port: 9443
```

#### 5.6.9 Post-task in certificate_authority

**File:** `roles/certificate_authority/tasks/create.yml` (or the equivalent CA
creation role)

```yaml
- name: Create Gateway API TLSRoute for CA API
  kubernetes.core.k8s:
    state: present
    namespace: "{{ namespace }}"
    resource_definition: "{{ lookup('template',
      'templates/k8s/gateway/tlsroute-ca.yaml.j2') }}"
  when:
    - ingress_type == 'gateway-api'
    - expose_ca | bool
  vars:
    ca_api_hostname: "{{ ca_api_url | urlsplit('hostname') }}"
    ca_service: "{{ ca_name | lower | replace(' ', '-') }}"
```

#### 5.6.10 Upstream contribution target

File a PR against `hyperledger-labs/fabric-operator` proposing:
- A new env var `INGRESS_CLASS` with values `nginx` (default) and `gateway-api`.
- When `INGRESS_CLASS=gateway-api`, the operator reconciler emits `HTTPRoute` +
  `TLSRoute` instead of `Ingress` objects, respecting the same conditionality
  (console always, peers/orderers/CA conditional on configuration).
- The operator's `ClusterRole` is extended to include `gateway.networking.k8s.io`
  verbs (mirrors W4 above).

Until that PR is merged, W6's post-task overlay is the supported path.

---

### 5.7 W7 — Documentation and role tutorials

W7 must provide a Gateway API tutorial for every collection role that creates a
Gateway API resource or creates a component whose Service can be exposed by one.
The tutorials must state which variables the user sets in the playbook or its
`vars_files`; they must not imply that the collection installs a Gateway API
controller or GatewayClass.

#### Files to update

| File | Change |
|------|--------|
| `docs/source/tutorials/oss-installing.rst` | Add Gateway API installation path; replace IKS/nginx SSL passthrough note with Gateway API equivalent |
| `docs/source/tutorials/hlfsupport-installing.rst` | Same |
| `docs/source/roles/fabric-operator-crds.rst` | Document the Gateway resource and its Gateway API variables |
| `docs/source/roles/fabric-console.rst` | Link to the console Gateway API tutorial and document console hostname/TLS inputs |
| `docs/source/roles/hlfsupport_console.rst` | Link to the console Gateway API tutorial and document console hostname/TLS inputs |
| `docs/source/roles/endorsing-organization.rst` | Link to the peer and CA Gateway API tutorial and document the peer exposure switches |
| `docs/source/roles/ordering-organization.rst` | Link to the orderer and CA Gateway API tutorial and document the orderer exposure switches |
| `docs/source/index.rst` | Add the four Gateway API tutorial pages to the Tutorials toctree |

#### New pages to create

| File | Content |
|------|---------|
| `docs/source/tutorials/gateway-api-install.rst` | Cluster prerequisite and shared Gateway setup, followed by links to each role tutorial |
| `docs/source/tutorials/gateway-api-console.rst` | Use `fabric_console` or `hlfsupport_console` with the HTTPS console route |
| `docs/source/tutorials/gateway-api-endorsing-organization.rst` | Use `endorsing_organization` with peer gRPC, operations, gRPC-Web, and CA routes |
| `docs/source/tutorials/gateway-api-ordering-organization.rst` | Use `ordering_organization` with orderer gRPC, operations, and CA routes |
| `docs/source/tutorials/migrate-nginx-to-gateway.rst` | Upgrade guide for existing nginx-based deployments |

#### Shared Gateway API variables

Each role tutorial must start by referring to `gateway-api-install.rst` and list
these shared variables. A value is required when `ingress_type: gateway-api` is
selected unless stated otherwise.

| Variable | Required | Used by | Tutorial requirement |
|----------|----------|---------|----------------------|
| `ingress_type` | Yes | `fabric_operator_crds`, `fabric_console`, `hlfsupport_console`, `endorsing_organization`, `ordering_organization` | Set to `gateway-api`. |
| `gateway_class_name` | Yes | `fabric_operator_crds` | Name of the pre-provisioned GatewayClass. |
| `ingress_domain` | Yes | `fabric_operator_crds` and all route hostnames | DNS suffix covered by the Gateway wildcard listener, for example `example.com`. |
| `ingress_tls_secret` | Conditional | `fabric_operator_crds` | Name of the existing same-namespace TLS Secret used by the HTTPS listener; omit only when the documented default `fabric-tls-secret` exists. |
| `ingress_ca_port` | No | `fabric_operator_crds`, `endorsing_organization`, `ordering_organization` | Override only when the external TLS listener cannot use `7054`. |
| `ingress_grpc_orderer_port` | No | `fabric_operator_crds`, `ordering_organization` | Override only when the external TLS listener cannot use `7050`. |
| `ingress_grpc_peer_port` | No | `fabric_operator_crds`, `endorsing_organization` | Override only when the external TLS listener cannot use `7051`. |

#### Role tutorial tasks and exhaustive new route variables

1. **`fabric_operator_crds` — `gateway-api-install.rst`**

   Document installing the conformant Gateway API controller and GatewayClass as a
   cluster prerequisite, creating the TLS Secret in the target namespace, and then
   running `fabric_operator_crds`. Show the shared variables above and verify
   `Gateway/fabric-gateway` reports `Programmed=True`. This is the only role that
   creates the shared Gateway; it exposes no Fabric component Service itself.

2. **`fabric_console` and `hlfsupport_console` — `gateway-api-console.rst`**

   Provide one tutorial with separate examples for both console roles. It must
   establish the exact `IBPConsole` Service name and generated hostname from the
   corresponding operator before documenting the HTTPS `HTTPRoute`, then verify that
   route. The only new Gateway API input consumed by each console role is
   `ingress_type: gateway-api`; `console_domain` and `console_tls_secret` remain the
   role's existing required or optional console inputs. The tutorial must also point
   to the `fabric_operator_crds` deployment that supplies the shared Gateway and
   document its shared variables; console playbooks must not redundantly set
   `gateway_class_name`, `ingress_domain`, `ingress_tls_secret`, or either gRPC port
   unless they run that role too.

3. **`endorsing_organization` — `gateway-api-endorsing-organization.rst`**

   Demonstrate peer creation with a TLSRoute on the peer listener and show optional
   HTTPRoutes for operations and gRPC-Web. The exhaustive new route variables are:

   | Variable | Required | Route created |
   |----------|----------|---------------|
   | `expose_peer` | Yes | Peer gRPC TLSRoute when `true`; set `false` for in-cluster-only peer access. |
   | `expose_peer_operations` | Yes | Peer operations HTTPRoute when `true`; default `false`. |
   | `expose_grpcweb` | Yes | Peer gRPC-Web HTTPRoute when `true`; default `false`. |
   | `expose_ca` | Yes | Organization CA route when `true`; set `false` when enrollment remains in-cluster. |
   | `peer_api_url` | Yes when `expose_peer: true` | Supplies the peer TLSRoute hostname. |
   | `peer_operations_url` | Yes when `expose_peer_operations: true` | Supplies the operations HTTPRoute hostname. |
   | `peer_grpcwp_url` | Yes when `expose_grpcweb: true` | Supplies the gRPC-Web HTTPRoute hostname. |
   | `ca_api_url` | Yes when `expose_ca: true` | Supplies the CA route hostname. |

   `ingress_type` and the four `expose_*` variables are the new inputs consumed by
   this role. The tutorial must combine them with the shared Gateway values when the
   same playbook also runs `fabric_operator_crds`, use `:7051` in `peer_api_url`,
   use `:7054` for CA `api_url` and `operations_url`, and use `:443` for peer
   operations and gRPC-Web URLs. Before implementation, W6 must
   confirm the operator-provided names of these URLs and the peer, gRPC-Web, and CA
   Services so the examples match the generated resources.

4. **`ordering_organization` — `gateway-api-ordering-organization.rst`**

   Demonstrate orderer creation with a TLSRoute on the orderer listener and an
   optional operations HTTPRoute. The exhaustive new route variables are:

   | Variable | Required | Route created |
   |----------|----------|---------------|
   | `expose_orderer` | Yes | Orderer gRPC TLSRoute when `true`; set `false` for in-cluster-only orderer access. |
   | `expose_orderer_operations` | Yes | Orderer operations HTTPRoute when `true`; default `false`. |
   | `expose_ca` | Yes | Organization CA route when `true`; set `false` when enrollment remains in-cluster. |
   | `orderer_api_url` | Yes when `expose_orderer: true` | Supplies the orderer TLSRoute hostname. |
   | `orderer_operations_url` | Yes when `expose_orderer_operations: true` | Supplies the operations HTTPRoute hostname. |
   | `ca_api_url` | Yes when `expose_ca: true` | Supplies the CA route hostname. |

   `ingress_type`, `expose_orderer`, `expose_orderer_operations`, and `expose_ca`
   are the new inputs consumed by this role. The tutorial must combine them with the
   shared Gateway values when the same playbook also runs `fabric_operator_crds`,
   use `:7050` in `orderer_api_url`, use `:7054` for CA `api_url` and
   `operations_url`, and use `:443` for orderer operations URLs. Before
   implementation, W6 must confirm the operator-provided names of these URLs and
   the orderer and CA Services so the examples match the generated resources.

`certificate_authority` is an Ansible module used from the endorsing and ordering
organization roles, not a standalone role in this collection. Its Gateway API
exposure is therefore documented in both organization tutorials through
`expose_ca` and `ca_api_url`; W6 must identify the concrete CA creation task before
those tutorials are implemented.

#### Key content for `gateway-api-install.rst`

The tutorial must explain:

1. The four-listener `Gateway` model and why ports 443 / 7054 / 7050 / 7051 are chosen.
2. That the `GatewayClass` and Envoy Gateway controller must be installed as a
   cluster-level prerequisite **before** running any collection playbook —
   mirroring the existing nginx prerequisite instructions.
3. That `api_url` for peers now resolves to port 7051 and for orderers to port 7050.
4. That CA `api_url` and `operations_url` use TLS passthrough on port 7054, while
   `grpcwp_url` and peer and orderer `operations_url` remain on port 443.
5. The `kubectl get gateway -n <namespace>` command to verify the Gateway is
   programmed (replacing the `kubectl get ingress` instructions in the current docs).
6. The `localho.st` wildcard DNS trick and the CoreDNS override — now applied
   **after** the playbook creates the `Gateway` resource (not before), and now
   pointing at the Envoy Gateway service ClusterIP.

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

[`translate_url_to_os_format()`](../../plugins/module_utils/url_utils.py:8)
currently hard-codes `'443'` as the canonical port in the "os format". It must be
updated to accept an optional `canonical_port` argument (defaulting to `'443'` for
backwards compatibility) so callers in `peer_metadata.py` and
`ordering_service_node_metadata.py` can pass `'7051'` / `'7050'` when
`ingress_type == 'gateway-api'`.

---

## 7. Deprecation and sunset timeline

| Milestone | Action |
|-----------|--------|
| **v2.1 (this plan)** | `ingress_type: nginx` is the default. `ingress_type: gateway-api` is available as a preview. Deprecation notice added to nginx path documentation. Note: `TLSRoute` is Standard in Gateway API v1.6; there is no API stability concern with the Gateway API path itself. |
| **v2.2** | `ingress_type: gateway-api` promoted to stable default. Nginx path still supported but produces an `ansible.builtin.warn`. |
| **v2.3** | Nginx path removed. `ingress_type` default changed to `gateway-api`. |

The timeline assumes upstream `fabric-operator` Gateway API support lands by v2.2;
otherwise v2.2 is delayed until the overlay in W6 is replaced by native operator
support.

---

## 8. Acceptance criteria

A migration is considered complete when all of the following pass:

1. **[BOTH]** `ansible-lint` and `yamllint` pass on all modified files.
2. **[BOTH — CI runner]** `run-tests.sh` executes successfully with no positional
   arguments (the existing `$1`/`$2` crash is fixed). `fvtest.yml` sets all required
   env vars (`API_ENDPOINT`, `API_AUTHTYPE`, `API_KEY`, `API_SECRET`, `K8S_NAMESPACE`,
   `KUBECONFIG`) via `$GITHUB_ENV` before calling `run-tests.sh`.
3. **[BOTH — parity]** Both matrix legs (`nginx` and `gateway-api`) run the same
   tutorial sequence — `build_network.sh build` → `join_network.sh join` →
   `deploy_smart_contract.sh` — with unique run IDs stamped into vars files by
   `run-tests.sh` via `yq`, identical to the mechanism in `run-tutorial-tests.sh`.
4. **[NGINX]** All existing integration tests pass with `ingress_type: nginx`
   (or unset) without modification. `roles/fabric_operator_crds/tasks/k8s/create.yml`
   is byte-for-byte identical to its pre-migration state when `ingress_type == 'nginx'`.
5. **[GW]** A KIND cluster bootstrapped with `kind_with_envoy_gateway.sh` and
   `ingress_type: gateway-api` passes the full integration test suite.
6. **[GW — topology]** The CI runs in **Scenario B** (Ansible runner outside the
   cluster): the runner dials peer `api_url` (`CORE_PEER_ADDRESS`), orderer
   `api_url` (`--orderer`), CA `api_url` (fabric-sdk-py enrolment), and all
   `operations_url` endpoints (`/healthz` via `wait_for()`) through the gateway's
   `hostPort` mappings. `common-vars.yml` must have `expose_peer_operations: true`
   and `expose_orderer_operations: true` (written by `run-tests.sh` step 3).
   (See PRE-ANALYSIS §2.5.3.)
7. **[GW — CoreDNS]** The CoreDNS override is applied via `COREDNS_HOOK` **between**
   `build_network.sh build` and `join_network.sh join` (after the `fabric-gateway`
   Gateway resource exists), and correctly resolves `*.localho.st` to the Envoy
   Gateway service ClusterIP.
8. **[GW]** Peer `api_url` resolves to port 7051; orderer `api_url` resolves to
   port 7050; both reach their pod TLS stack without termination at the gateway
   (verified by comparing the TLS certificate presented at the gateway address
   against the `tls_cert` stored in the console).
9. **[GW]** The console HTTPS endpoint is TLS-terminated at the gateway (verified
   by inspecting the serving certificate CN), while the CA API and operations
   endpoints on port 7054 preserve the CA's serving certificate through TLS
   passthrough.
10. **[GW]** A `fabric-sdk-py` channel join and peer query succeed end-to-end over
    the Gateway API path.
11. **[BOTH]** Documentation builds without warnings (`make -C docs html`).
12. **[FUTURE]** A separate workstream (out of scope for this migration) will
    investigate replacing `wait_for()` HTTP-poll calls with `kubernetes.core.k8s_info`
    readiness watches, which would make `expose_peer_operations` and
    `expose_orderer_operations` unnecessary and enable true Scenario A CI.
    (See PRE-ANALYSIS §2.5.4.)
