# New domain & URL management (proposal)

**Status:** proposal, not implemented.
**Builds on:** [`URL-MANAGEMENT-EXISTING.md`](./URL-MANAGEMENT-EXISTING.md)
(how URLs are built today) and
[`REVIEW-MIGRATION-PLAN-STEP-1.md`](./REVIEW-MIGRATION-PLAN-STEP-1.md)
("Variable scope", B2).
**Feeds:** [`MIGRATION-STEP-1.md`](./MIGRATION-STEP-1.md) sub-tasks 1.1, 1.2,
1.4, 1.6, 1.8, 1.9.

Sources: same revisions as `URL-MANAGEMENT-EXISTING.md`
(collection `9490cc9`, fabric-operations-console `2ec7e1c`, fabric-operator
`6ea612b`). The key mechanisms were checked on a local KIND cluster on
2026-10-16 (§9): 6 of 7 checks pass, the end-to-end scenario B run waits for
sub-task 1.9.

---

## 1. Goals

| # | Goal |
|---|---|
| G1 | Clear separation between the **exposed** domain (what users and clients outside the cluster see) and the **HLF network** domain (what is baked into the CA, peer and orderer FQDNs and certificates). |
| G2 | Minimal change in the Fabric Ansible Collection, **no change** in the Fabric Operator or the Operations Console. |
| G3 | Support the Step 1 target: nothing exposed at first deployment, HLF network domain internal to the cluster, and the console exposable **later**, by hand, through an Ingress or a Gateway API route, with a working URL and TLS certificate. |
| G4 | No regression for the current default: everything exposed through nginx, one domain. |

---

## 2. The key fact: the operator already supports two domains

Today the collection sets one field, `IBPConsole.spec.networkinfo.domain`, and
the operator uses it for both the console and the nodes
(`URL-MANAGEMENT-EXISTING.md` §2). The `IBPConsole` CRD also has an optional
**`spec.deployer.domain`** field:

- *operator* `pkg/offering/base/console/override/deployercm.go:172-175`:

  ```go
  // used for passing separate domains for optools and deployer
  if instance.Spec.Deployer != nil && instance.Spec.Deployer.Domain != "" {
      config.Domain = instance.Spec.Deployer.Domain
  }
  ```
- The deployer writes `config.Domain` into every CA, peer and orderer CR it
  creates (`spec.domain`), so it decides every node FQDN and TLS SAN.
- The console keeps using `networkinfo.domain` for its own hostname, its
  Ingress rule, its `HOST_URL` and, without a TLS secret, its self-signed
  certificate (§5).
- The other `spec.deployer` fields (`create_db`, `components_db`,
  `connectionstring`) are only applied when non-empty
  (`deployercm.go:91-100`). Setting `domain` alone has no other effect.

The decoupling therefore only needs the collection to fill in a field the
operator already has.

The second building block is also already in the CRD:
**`IBPConsole.spec.ingress.class`**. It is copied into the console Ingress
annotation `kubernetes.io/ingress.class`
(*operator* `pkg/offering/k8s/console/override/ingress.go:50-54`, default
`nginx`). The nginx controller deployed by the collection only serves
`--ingress-class=nginx`
(`roles/fabric_operator_crds/templates/k8s/ingress/ingress-nginx-controller.yaml:33-34`).
Any other class leaves the console Ingress in place but **unserved**.

```
                        IBPConsole (one CR, two domains)
              ┌──────────────────────────────────────────────┐
              │ spec.networkinfo.domain  = exposed_domain     │──► console hostname, HOST_URL,
              │ spec.ingress.class       = nginx | <none>     │    console TLS SAN, console Ingress
              │ spec.deployer.domain     = hlf_node_domain    │──► deployer Config.Domain
              │   (rendered only when ≠ exposed_domain)       │          │
              └──────────────────────────────────────────────┘          ▼
                                       IBPCA / IBPPeer / IBPOrderer  spec.domain
                                                                         │
                                       <ns>-<cr>-<endpoint>.<hlf_node_domain>:443
                                       = api_url, operations_url, … and node TLS SANs
```

---

## 3. Variables

### 3.1 Two ways of building node FQDNs

The operator always builds `<ns>-<cr>-<endpoint>.<spec.domain>`. The
collection chooses `spec.domain` (fact `hlf_node_domain`) from
`hlf_network_domain`:

| Case | `hlf_node_domain` (= `spec.domain`) | Node FQDN | CoreDNS rewrite when unexposed |
|---|---|---|---|
| **Cluster-local**: `hlf_network_domain == cluster_domain` | `<namespace>.svc.<cluster_domain>` | `<service>.<namespace>.svc.<cluster_domain>`, a real Service FQDN | **none**: kube-dns answers it |
| **Otherwise** (default): previous way | `hlf_network_domain` | `<ns>-<cr>-<endpoint>.<hlf_network_domain>` (as today) | one rule per endpoint type (sub-task 1.8) |

In the cluster-local case, `<service>` is exactly the name of the
per-endpoint Service created by sub-task 1.6:

```
default-org1peer-operations . default . svc . cluster.local
└──────── <service> ──────┘ └<namespace>┘     └ cluster_domain ┘
            (Service name)              = hlf_network_domain
```

Hence:

```
hlf_network_domain_is_cluster_local := (hlf_network_domain == cluster_domain)
```

and when it is `true`, no CoreDNS rewrite is needed.

### 3.2 Definitions

| Variable | Meaning | Feeds | Default |
|---|---|---|---|
| `exposed_domain` | Domain users see. **Rename of `ingress_domain`.** Used to build the console URL even when the console is not exposed. | `IBPConsole.spec.networkinfo.domain`; console URL `https://<ns>-<console_name>-console.<exposed_domain>`; console TLS SAN | `console_domain` (legacy name, see §3.3) |
| `hlf_network_domain` | Domain of the HLF network nodes. Either `cluster_domain` (cluster-local, Service-shaped FQDNs) or any other domain (flat FQDNs, previous way). | `hlf_node_domain` → `IBPConsole.spec.deployer.domain` → node CRs `spec.domain` | `exposed_domain` (no behaviour change) |
| `cluster_domain` | Kubernetes cluster DNS zone. | `hlf_network_domain_is_cluster_local`; CoreDNS rewrite targets; in-cluster Service FQDNs | `""`, resolved from the `kube-system/coredns` ConfigMap, cross-checked when set (sub-task 1.1) |
| `expose_console`, `expose_ca`, `expose_peer`, `expose_orderer` | Whether a component is reachable from outside the cluster. | console Ingress class (§5.2); per-endpoint Services (1.6); CoreDNS rewrites (1.8) | `true` |
| `unexposed_ingress_class` | Ingress class no controller serves, set on the Ingress of an unexposed component (D3). | console `spec.ingress.class` (§5.2); node `spec.ingress.class` when neutralized (§5.4) | `none` |
| `neutralize_node_ingresses` | Also set `unexposed_ingress_class` on the CR of every unexposed CA, peer and orderer node (D4). | §5.4 | `false` |

Derived facts (set by the shared role of §6, never set by users):

| Fact | Value |
|---|---|
| `hlf_network_domain_is_cluster_local` | `hlf_network_domain == cluster_domain` (both normalised: lowercase, no trailing dot) |
| `hlf_node_domain` | `<namespace>.svc.<cluster_domain>` if cluster-local, else `hlf_network_domain` |
| `console_url` | `https://<namespace>-<console_name>-console.<exposed_domain>` |
| `console_incluster_url` | `https://<console_name>.<namespace>.svc.<cluster_domain>:3000` |

`<namespace>` is the namespace of the console. The deployer creates every
node in it (`URL-MANAGEMENT-EXISTING.md` §4.1), so it is also the namespace
of the per-endpoint Services. The organization roles' `k8s_namespace` must
equal it (checked by V5).

`spec.deployer.domain` is rendered **only when** `hlf_node_domain !=
exposed_domain`. With the defaults it is not rendered, and the CR is the
same as today.

### 3.3 Backward compatibility of `console_domain`

`console_domain` is mandatory today and used by every playbook, tutorial and
CI script. It stays accepted as a **deprecated alias** of `exposed_domain`
(D5), until the release that removes the nginx path (roadmap deprecation
timeline). The notice says so:

| `exposed_domain` | `console_domain` | Effective `exposed_domain` |
|---|---|---|
| unset | `D` | `D` (deprecation notice) |
| `D` | unset | `D` |
| `D` | `D` | `D` |
| `D` | `X ≠ D` | **fail**: both values named |
| unset | unset | **fail** (same as today's `console_domain not specified`) |

`ingress_domain` (`roles/fabric_operator_crds/defaults/main.yml:46`) is used by
no task or template today (`URL-MANAGEMENT-EXISTING.md` §2.1). It is removed,
not aliased.

### 3.4 Validation rules (fail fast, at role entry)

| # | Rule | Why |
|---|---|---|
| V1 | `exposed_domain` is neither `cluster_domain` nor inside it | The console URL must be resolvable from outside, even if it is only exposed later. |
| V2 | `hlf_network_domain` is `cluster_domain` or **outside** it; a sub-zone such as `svc.cluster.local` or `default.svc.cluster.local` is rejected, naming `cluster_domain` as the value to use | The role builds `<namespace>.svc.` itself in the cluster-local case. A sub-zone would be taken as a flat domain, with unclear results. |
| V3 | `hlf_network_domain_is_cluster_local` ⇒ `expose_ca`, `expose_peer`, `expose_orderer` all `false` | Cluster-local node FQDNs can't be resolved from outside. `expose_console` is **not** constrained: the console uses `exposed_domain`. |
| V4 | `<namespace>-<console_name>-console` ≤ 63 characters | First DNS label of the console URL. |
| V5 | After every CA/peer/orderer module call, every returned URL host ends with `.` + `hlf_node_domain` | Detects a console deployed with another domain, or a `k8s_namespace` different from the console namespace (§6.3). |

---

## 4. Scenarios

| | **A. Exposed, non-Kubernetes FQDNs (default)** | **B. Step 1 target** | **C. Unexposed, non-Kubernetes FQDNs** | **D. Later (Step 3)** |
|---|---|---|---|---|
| `exposed_domain` | `127-0-0-1.nip.io` | `example.com` | `127-0-0-1.nip.io` | `example.com` |
| `hlf_network_domain` | = exposed (default) | `cluster.local` (= `cluster_domain`) | = exposed (default) | `fabric.example.com` |
| `hlf_network_domain_is_cluster_local` | `false` | **`true`** | `false` | `false` |
| `hlf_node_domain` (`spec.domain`) | `127-0-0-1.nip.io` | `default.svc.cluster.local` | `127-0-0-1.nip.io` | `fabric.example.com` |
| `spec.deployer.domain` rendered | no | yes | no | yes |
| `expose_console` | `true` | `false` | `false` | `true` |
| `expose_ca/peer/orderer` | `true` | `false` | `false` | `true` |
| Console Ingress class | `nginx` | `none` (unserved) | `none` | `nginx` / gateway route |
| Per-endpoint Services (1.6) | no | yes | yes | no |
| CoreDNS endpoint rewrites (1.8) | no | **no** | yes (per endpoint type) | no |
| Where org playbooks run | anywhere | in-cluster (1.9) | in-cluster (1.9) | anywhere |

B is the Step 1 target. C is the current `expose-none` CI design of
sub-task 1.8, kept as the "else" branch and as a compatibility leg. D only
outlines Step 3.

### 4.1 Scenario A: everything exposed, non-Kubernetes FQDNs (default, no regression)

```
   client (outside)            nginx :443 (SSL passthrough)              cluster
   ───────────────             ──────────────────────────              ───────
   default-hlf-console-console.<D> ─────────► console Ingress ───────► console :3000
   default-org1peer-peer.<D>       ─────────► peer Ingress    ───────► peer    :7051
   default-org1peer-operations.<D> ─────────► peer Ingress    ───────► peer    :9443
   …                                                             (one rule per endpoint)

   D = exposed_domain = hlf_network_domain = hlf_node_domain = console_domain
```

The rendered `IBPConsole` is the same as today, apart from removing the
duplicate `networkinfo:` key (§7.1):

```yaml
spec:
  networkinfo:
    domain: "127-0-0-1.nip.io"
  # no spec.deployer   → nodes use networkinfo.domain, as today
  # no spec.ingress    → class defaults to nginx, as today
```

### 4.2 Scenario B: Step 1 target, nothing exposed, HLF domain = cluster domain

```yaml
# vars
exposed_domain: example.com
hlf_network_domain: cluster.local      # = cluster_domain
expose_console: false
expose_ca: false
expose_peer: false
expose_orderer: false
```

Rendered `IBPConsole` (`namespace: default`):

```yaml
spec:
  networkinfo:
    domain: "example.com"                  # console URL + console TLS SAN
  deployer:
    domain: "default.svc.cluster.local"    # <namespace>.svc.<cluster_domain>
  ingress:
    class: "none"                          # console Ingress exists, nginx ignores it
```

Resulting names:

| Object | Name | Resolves through |
|---|---|---|
| Console URL (not served yet) | `https://default-hlf-console-console.example.com` | nothing yet: added by hand later (§5.3) |
| Console in-cluster | `https://hlf-console.default.svc.cluster.local:3000` | operator Service `hlf-console` (named after the CR, port `optools`) |
| CA API | `https://default-org1ca-ca.default.svc.cluster.local:443` | per-endpoint Service `default-org1ca-ca` → 7054 |
| Peer API | `grpcs://default-org1peer-peer.default.svc.cluster.local:443` | Service `default-org1peer-peer` → 7051 |
| Peer operations | `https://default-org1peer-operations.default.svc.cluster.local:443` | Service `default-org1peer-operations` → 9443 |
| Orderer admin | `https://default-orderingservicenode1-admin.default.svc.cluster.local:443` | Service `default-orderingservicenode1-admin` → 9443 |

```
                                  cluster (namespace "default")
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │  ansible-runner Job ──► https://hlf-console.default.svc.cluster.local:3000   │
 │                              │  (console REST API)                           │
 │                              ▼                                               │
 │  console ─ deployer ─► IBPPeer.spec.domain = default.svc.cluster.local       │
 │                                                                              │
 │  default-org1peer-peer.default.svc.cluster.local:443                         │
 │      │   plain kube-dns answer: it IS a Service FQDN, no CoreDNS rewrite     │
 │      ▼                                                                       │
 │  Service default-org1peer-peer       443 → 7051 ──► peer pod                 │
 │  Service default-org1peer-operations 443 → 9443 ─┘                           │
 │  Service default-org1peer-grpcweb    443 → 7443 ─┘                           │
 └──────────────────────────────────────────────────────────────────────────────┘
        nginx :443 ── console Ingress has class "none" ── not served
                   └─ node Ingresses: hosts *.default.svc.cluster.local (§5.4)
```

Node TLS SANs (`URL-MANAGEMENT-EXISTING.md` §4.2) are generated from the same
`spec.domain`, so they match the names clients dial. No `csr_hosts` change is
needed.

### 4.3 Scenario C: nothing exposed, non-Kubernetes FQDNs

`hlf_network_domain` is left at its default (`exposed_domain`, here
`127-0-0-1.nip.io`), or set to any other domain outside `cluster_domain`.
The FQDNs keep the flat form, which matches no Service name, so the CoreDNS
rules of sub-task 1.8 are needed: **one per endpoint type**, keyed on
`hlf_network_domain`:

```
rewrite stop {
    name regex ^(default-[a-z0-9]+-operations)\.127-0-0-1\.nip\.io {1}.default.svc.cluster.local
    answer name ^(default-[a-z0-9]+-operations)\.default\.svc\.cluster\.local {1}.127-0-0-1.nip.io
}
```

```
default-org1peer-operations.127-0-0-1.nip.io
   │  CoreDNS: rewrite (operations rule)
   ▼
default-org1peer-operations.default.svc.cluster.local → Service → :9443
```

These rules depend on the CR-name pattern `[a-z0-9]+` (assumption S1 of
1.6) and only work when CA, peer and orderer are **all** unexposed
(sub-task 1.6 note on partial exposure). Scenario C stays useful as a
compatibility test: the same deployment as A, without nginx in the path.

### 4.4 Scenario D: later, nodes exposed (Step 3, outline only)

`hlf_network_domain: fabric.example.com` (≠ `exposed_domain`) with a public
wildcard record `*.fabric.example.com` pointing to the ingress controller or
gateway. The FQDNs keep the previous flat form
(`default-org1peer-peer.fabric.example.com`), and `spec.deployer.domain` is
rendered. Since node TLS SANs are fixed at enrollment, moving from B or C to D
on the **same** nodes is not possible without re-enrollment: the domain is
chosen at first deployment. Out of scope for Step 1.

### 4.5 CoreDNS decision, summarised

```
                         ┌─────────────────────────────┐
                         │ CA, peer and orderer all    │── no ──► no rewrite (nodes go through
                         │ unexposed?                  │          the ingress, scenarios A / D)
                         └──────────────┬──────────────┘
                                        │ yes
                         ┌──────────────▼──────────────┐
                         │ hlf_network_domain ==       │── yes ─► no rewrite: FQDNs are Service
                         │ cluster_domain ?            │          FQDNs (scenario B)
                         └──────────────┬──────────────┘
                                        │ no
                                        ▼
                         one rewrite per endpoint type
                         <ns>-<cr>-<ep>.<hlf_network_domain>
                           → <ns>-<cr>-<ep>.<ns>.svc.<cluster_domain>
                         (scenario C, sub-task 1.8)
```

---

## 5. The console: URL and TLS without exposure

### 5.1 Console URL

The console URL is always built from `exposed_domain`, whether exposed or
not, and independently of `hlf_network_domain`:

```
console_url = https://<namespace>-<console_name>-console.<exposed_domain>
            = https://default-hlf-console-console.example.com
```

This is the same string the operator uses for the console Ingress host and
`HOST_URL` (*operator* `pkg/offering/k8s/console/override/ingress.go:56`,
`envcm.go:41`), so the collection and the console always agree. The console
role prints it with a note when `expose_console: false`:

```
Console URL (not exposed): https://default-hlf-console-console.example.com
Reachable in-cluster at:   https://hlf-console.default.svc.cluster.local:3000
To expose it, route the URL above to Service hlf-console:3000 (see §5.3).
```

### 5.2 Not exposing the console without touching the operator

The operator always creates the console Ingress. With
`expose_console: false` the console role sets `spec.ingress.class` to a class
no controller serves (`unexposed_ingress_class`, default `none`, D3). The
Ingress exists, but nginx ignores it.

Re-running the role with `expose_console: true` sets the class back to
`nginx`; the operator updates the Ingress (`UpdateIngress`, same file).
No manual cleanup needed.

### 5.3 TLS certificate of the console

The console pod terminates TLS itself on port 3000. nginx runs in SSL
passthrough mode for it (`definitions/console/ingress.yaml`). Two cases:

| `console_tls_secret` | Certificate presented by the console | SAN |
|---|---|---|
| unset (default) | Self-signed, generated by athena at first start (`packages/athena/app.js:1236-1255`), stored on the console PVC (`/certs/tls.crt`, `couchdb` PVC sub-path `tls`), so kept across restarts | host of `HOST_URL` = `<ns>-<console>-console.<exposed_domain>` (+ the proxy URL host, the same by default) |
| set | The Secret's `tls.crt` / `tls.key`, mounted at `/certs/tls` (*operator* `pkg/offering/base/console/override/deployment.go:115-118`) | whatever the issuer put in it, which must include `console_url`'s host |

Both are tied to `exposed_domain`, not to the exposure, and not to
`hlf_network_domain`. A console created unexposed already carries the right
certificate for the URL it will be exposed under later. The existing
`console_tls_secret` variable of the `fabric_console` role is kept; the
proposal only documents it and adds it to the tutorial CR.

The certificate chosen decides how the console can be exposed later:

```
 (1) TLS passthrough — the console's own certificate reaches the client
     client ──TLS(SNI=console host)──► nginx / Gateway (passthrough) ──► console :3000
     needs: console certificate trusted by the client (console_tls_secret from a
            real CA, e.g. cert-manager) or accepted as self-signed

 (2) TLS termination at the edge — the edge presents its own certificate
     client ──TLS──► Gateway (terminate, cert for console host) ──TLS──► console :3000
     needs: edge certificate for the console host; backend TLS to :3000
            (BackendTLSPolicy, or skip verification of the self-signed backend)
```

Manual exposure later, nginx Ingress (passthrough, same as the operator's):

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hlf-console-exposed
  namespace: default
  annotations:
    nginx.ingress.kubernetes.io/ssl-passthrough: "true"
spec:
  ingressClassName: nginx
  rules:
    - host: default-hlf-console-console.example.com
      http:
        paths:
          - path: /
            pathType: ImplementationSpecific
            backend:
              service: { name: hlf-console, port: { name: optools } }
```

Manual exposure later, Gateway API (passthrough, `TLSRoute`):

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2   # check the version served by the installed Gateway API CRDs
kind: TLSRoute
metadata:
  name: hlf-console
  namespace: default
spec:
  parentRefs: [{ name: fabric-gateway, sectionName: tls-passthrough }]
  hostnames: ["default-hlf-console-console.example.com"]
  rules:
    - backendRefs: [{ name: hlf-console, port: 3000 }]
```

The simplest path is to re-run the console role with `expose_console: true`
(§5.2), which re-enables the operator's own Ingress.

**Browser access to the nodes.** With the default `spec.proxying: true`, the
operator sets the console's `proxy_tls_fabric_reqs` to `always`
(*operator* `pkg/offering/base/console/override/consolecm.go:125-132`). The
browser UI then reaches CA and grpc-web endpoints **through the console URL**
(*athena* `libs/component_lib.js:1023-1056`); the console pod calls the node
FQDNs from inside the cluster. Exposing only the console is therefore enough
for the UI to manage in-cluster nodes in scenario B.

### 5.4 Node Ingress objects: opt-in neutralization (B2, D4)

#### Problem

`expose_ca/peer/orderer: false` changes how the **collection** reaches the
nodes (per-endpoint Services). It does not stop the **operator** from
publishing them: for every CA, peer and orderer node CR, it creates an
Ingress with class `nginx` and one SSL-passthrough rule per endpoint. The
deployer has no setting to turn that off.

Scenario B, after `Create peer`:

```yaml
kind: Ingress
metadata:
  name: org1peer
  annotations: { kubernetes.io/ingress.class: nginx }
spec:
  ingressClassName: nginx
  rules:
    - host: default-org1peer-peer.default.svc.cluster.local         # → :7051
    - host: default-org1peer-operations.default.svc.cluster.local   # → :9443
    - host: default-org1peer-grpcweb.default.svc.cluster.local      # → :7443
```

The hostnames don't resolve outside the cluster, but a client that can reach
nginx's `:443` doesn't need DNS. It only has to send the right SNI:

```bash
curl -k --resolve default-org1peer-operations.default.svc.cluster.local:443:<nginx-ip> \
     https://default-org1peer-operations.default.svc.cluster.local/healthz
# {"status":"OK"}  ← reached the peer through nginx
```

So scenario B hides the nodes but doesn't isolate them (review option (a)).
In scenario C the hostnames are under `exposed_domain` and resolve publicly.

#### Mechanism

The class is set on the **node CR**, not on the Ingress:

| Where | Effect |
|---|---|
| Ingress (`ingressClassName: none`) | Reverted: on the next spec change of the CR, the operator rebuilds the Ingress and writes the CR's class (default `nginx`) back (*operator* `pkg/manager/resources/ingress/manager.go:85-106`). |
| CR (`spec.ingress.class: none`) | Kept: the operator copies it into the annotation and `spec.ingressClassName` on every Ingress update (`manager.go:221-262`). Patching it is a spec change, so the operator applies it immediately (`controllers/ibppeer/ibppeer_controller.go:626-630`). |

`IBPCA`, `IBPPeer` and `IBPOrderer` all have `spec.ingress.class`
(*operator* `api/v1beta1/common_struct.go:67`).

#### Example (`endorsing_organization`, after the peer module call)

```yaml
- name: Neutralize the operator Ingress of unexposed peers
  kubernetes.core.k8s:
    state: patched
    api_version: ibp.com/v1beta1
    kind: IBPPeer
    namespace: "{{ k8s_namespace }}"
    name: "{{ item }}"                       # CR name, from the returned api_url
    definition:
      spec:
        ingress:
          class: "{{ unexposed_ingress_class }}"
  loop: "{{ endorsing_organization_peer_cr_names }}"
  when:
    - neutralize_node_ingresses | bool
    - not expose_peer | bool
```

The same task covers `IBPCA` (the organization CA) and every `IBPOrderer`
node (`orderingservicenode1`, `…node2`, …). A follow-up `k8s_info` waits
until the Ingress shows `ingressClassName: none`.

```
 before:  outside ──SNI default-org1peer-*──► nginx :443 ──► peer   (reachable)
 after:   outside ──SNI default-org1peer-*──► nginx :443 ──► 404    (not served)
 always:  in-cluster ──► Service default-org1peer-* ──► peer        (1.6, unchanged)
```

Per component: `expose_peer: false` with `expose_ca: true` neutralizes
only the peers. To expose a node again, set its CR class back to `nginx`.

#### Limits and why opt-in

- **Exposure window.** The operator creates the Ingress with class `nginx`
  as soon as it sees the CR. The patch only lands after the module call,
  which blocks until the node is healthy. During node startup the endpoints
  are reachable through nginx. Closing that window needs an operator change,
  out of scope (G2).
- **Not a network boundary.** Pod-to-pod traffic inside the cluster is a
  `NetworkPolicy` concern.
- **Default `false`** (D4). §9 checks 2, 3 and 7 passed on a CA on
  2026-10-16:
  - nginx ignores the class (404, `unknown ingressclass`);
  - a later console update keeps `spec.ingress` on the CR;
  - the spec patch does not restart the node pod.

  Repeat check 3 on a peer before changing the default.

---

## 6. Variable scope: one shared role

### 6.1 Problem

The domain variables are needed by roles run from **separate playbooks**:

```
playbook 00   fabric_operator_crds, fabric_console / hlfsupport_console
playbook 01+  endorsing_organization, ordering_organization  (only know api_endpoint)
CI scripts    kind_with_nginx.sh (CoreDNS), run-tests.sh
```

Defaults of one role are not visible in another, and `include_tasks:
set_facts.yml` from `hlfsupport_console` looks in its own role (review
finding).

### 6.2 Proposal: internal role `network_domains`

```
roles/network_domains/
├── defaults/main.yml   exposed_domain, hlf_network_domain, cluster_domain,
│                       expose_*, unexposed_ingress_class,
│                       neutralize_node_ingresses
└── tasks/
    ├── main.yml        alias + validation (§3.3, §3.4 V1–V4),
    │                   cluster_domain resolution (sub-task 1.1),
    │                   facts: hlf_network_domain_is_cluster_local,
    │                          hlf_node_domain, console_url, console_incluster_url
    └── verify_urls.yml V5: compare returned node URLs with hlf_node_domain
```

```
            ┌────────────────────────── network_domains ─────────────────────────┐
            │ inputs: exposed_domain | console_domain, hlf_network_domain,       │
            │         cluster_domain, expose_*, namespace, console_name          │
            │ facts : exposed_domain, hlf_network_domain, cluster_domain,        │
            │         hlf_network_domain_is_cluster_local, hlf_node_domain,      │
            │         console_url, console_incluster_url                         │
            └──────▲──────────────────▲─────────────────────▲─────────────────────┘
       include_role│     include_role │        include_role │ (+ tasks_from: verify_urls)
 fabric_console /  │  fabric_operator │  endorsing_organization /
 hlfsupport_console│  _crds (CoreDNS) │  ordering_organization (1.6 Services)
```

Core of `tasks/main.yml` (after normalisation, the `console_domain` alias and
`cluster_domain` resolution; `_hlf_network_domain` is the normalised input,
defaulting to `exposed_domain`):

```yaml
- name: Reject a sub-zone of the cluster domain as hlf_network_domain
  ansible.builtin.fail:
    msg: >-
      hlf_network_domain='{{ _hlf_network_domain }}' is inside the cluster
      domain '{{ cluster_domain }}'. For in-cluster node FQDNs, set
      hlf_network_domain to '{{ cluster_domain }}': the role then builds
      <service>.<namespace>.svc.{{ cluster_domain }} itself.
  when:
    - _hlf_network_domain != cluster_domain
    - _hlf_network_domain.endswith('.' ~ cluster_domain)

- name: Set the HLF network facts
  ansible.builtin.set_fact:
    hlf_network_domain_is_cluster_local: "{{ _hlf_network_domain == cluster_domain }}"
    hlf_node_domain: >-
      {{ (network_domains_namespace ~ '.svc.' ~ cluster_domain)
         if _hlf_network_domain == cluster_domain
         else _hlf_network_domain }}
    console_url: >-
      https://{{ network_domains_namespace }}-{{ console_name }}-console.{{ exposed_domain }}
```

The role only computes and checks facts. It creates no Kubernetes resource.
The only cluster access is the read of `kube-system/coredns` for
`cluster_domain`, done only when a Kubernetes-facing caller needs it
(`network_domains_resolve_cluster_domain`, `true` for the console roles and
for organization roles with an unexposed component). The REST-only path of
the organization roles keeps needing no kubeconfig.

If the caller does not resolve `cluster_domain`, the cluster-local case
cannot be detected. A `hlf_network_domain` that ends like a cluster domain
(`cluster.local`) would then be used as a flat domain without warning. So
the role resolves `cluster_domain` whenever `hlf_network_domain` differs from
`exposed_domain`.

### 6.3 How the organization roles learn `hlf_network_domain`

The organization roles get the same vars files as the console playbook in the
tutorial (`common-vars.yml`). So `hlf_network_domain` (and `exposed_domain`)
go into `common-vars.yml`, read by every playbook. To protect against a
vars file that does not match the console actually deployed:

1. **Before the module call** (needed by 1.6, the health wait runs inside
   the module): use `hlf_node_domain` computed from the vars.
2. **After the module call** (V5): check the domain of the returned URLs:

   ```yaml
   - name: Check the console uses the expected HLF node domain
     ansible.builtin.assert:
       that: (item | urlsplit('hostname')).endswith('.' ~ hlf_node_domain)
       fail_msg: >-
         The console created {{ item }}, which is not under
         '{{ hlf_node_domain }}'. Either the console was deployed with another
         hlf_network_domain (check its spec.deployer.domain), or k8s_namespace
         differs from the console namespace.
       quiet: true
     loop: "{{ network_domains_urls | select | list }}"
   ```

   On a mismatch in an unexposed scenario, the health wait inside the module
   usually times out first, with an unclear error. The assert still matters:
   on a rerun the module finds the existing component and returns at once,
   so the assert then reports the real cause. In an exposed scenario the
   module succeeds through nginx and the assert is the only thing that
   catches the mismatch.

A pre-call read of `IBPConsole.spec.deployer.domain` with `k8s_info` would
be stronger, but the organization roles do not know the console name and
namespace. Kept as a later option.

---

## 7. Changes required

### 7.1 Fabric Ansible Collection

| # | File(s) | Change | Default path impact |
|---|---|---|---|
| C1 | `roles/network_domains/` (new) | §6.2 | none (only computes facts) |
| C2 | `roles/fabric_console/templates/{k8s,openshift}/hlf-operations-console.yaml.j2` | `networkinfo.domain: {{ exposed_domain }}`; remove the duplicate `networkinfo:` block (`:34-35`); add `deployer.domain: {{ hlf_node_domain }}` **only when** `hlf_node_domain != exposed_domain`; add `ingress.class: {{ unexposed_ingress_class }}` **only when** `not expose_console` | rendered CR unchanged |
| C3 | `roles/hlfsupport_console/templates/{k8s,openshift}/console.yml.j2` | same as C2 | unchanged |
| C4 | `roles/fabric_console/tasks/create.yml`, `roles/hlfsupport_console/tasks/create.yml` | replace the `console_domain` check by `include_role: network_domains` | same failure when no domain is given |
| C5 | `roles/fabric_console/tasks/k8s/create.yml:59` (+ hlfsupport) | print `console_url`; when not exposed, print the notice of §5.1 | same message |
| C6 | `tutorial/00-deploy-fabric-console.yml` | same as C2 on the inline CR; keep `hlf_console_domain` as input of `exposed_domain` | unchanged |
| C7 | `tutorial/common-vars.yml` | add `exposed_domain`, `hlf_network_domain` (commented, default = exposed) | none |
| C8 | `roles/endorsing_organization`, `roles/ordering_organization` | `include_role: network_domains`; 1.6 uses `hlf_node_domain`; V5 after each module call; node Ingress neutralization when `neutralize_node_ingresses` (§5.4) | V5 only (an assert that holds today) |
| C9 | `roles/fabric_operator_crds/defaults/main.yml` | remove unused `ingress_domain` | none |
| C10 | `.github/scripts/kind_with_nginx.sh` | 1.8 follows §4.5: rewrites keyed on `HLF_NETWORK_DOMAIN` (default `INGRESS_DOMAIN`), skipped when it equals `CLUSTER_DOMAIN` | unchanged (`expose-all`) |
| C11 | docs | `docs/source/roles/fabric-console.rst` (new variables, `console_domain` deprecation), the two Step 1 tutorials (1.11, 1.12) | — |

No module (`plugins/`) changes: the modules keep consuming the URLs the
console returns.

### 7.2 Fabric Operator and Operations Console

None. The proposal only uses fields that already exist:
`spec.networkinfo.domain`, `spec.deployer.domain`, `spec.ingress.class`,
`spec.tlsSecretName`.

### 7.3 Impact on `MIGRATION-STEP-1.md`

**Applied on 2026-10-16.** Sub-tasks 1.1 and 1.2 were rewritten around a
prototype `network_domains` role
([`.url_management_new_checks/network_domains/`](./.url_management_new_checks/network_domains/),
13/13 test cases pass on KIND); 1.5 (console CR) and 1.7 (D4) were added;
the other sub-tasks and the acceptance criteria were updated as listed
below (sub-task numbers as renumbered on 2026-10-21).

| Sub-task | Update |
|---|---|
| 1.1 | Variables of §3, moved to `network_domains`; `ingress_domain` → `exposed_domain`; add `hlf_network_domain` and the derived `hlf_node_domain`; `cluster_domain` resolution unchanged. |
| 1.2 | `ingress_domain_is_cluster_local` → `hlf_network_domain_is_cluster_local` = `hlf_network_domain == cluster_domain`; the old "only `<ns>.svc.<cluster_domain>` is supported" guard becomes V2 (set `cluster_domain`, the role adds `<ns>.svc.`); V3; `expose_console` no longer conflicts with a cluster-local HLF domain. |
| 1.4 | `expose_console: false` = Ingress class `none` + notice with `console_url`; in-cluster health check through the console Service. The console serves **HTTPS** on 3000 (athena terminates TLS, §5.3): the plan's `http://<console>.<ns>.svc.cluster.local:3000` URLs (1.4, 1.9, 1.10, 1.12) must become `https://`. |
| 1.6 | FQDNs use `hlf_node_domain`; add V5. |
| 1.8 | Decision tree of §4.5; rules keyed on `hlf_network_domain` instead of `ingress_domain`. |
| 1.9 | New `expose-none-internal` CI leg (scenario B) next to the existing `expose-none` (scenario C). |
| 1.10 | Assertion 1 becomes: console Ingress class is not `nginx`; node Ingress hosts are under `hlf_node_domain`. Assertion 6 is skipped in scenario B (no rewrite). |

---

## 8. No-regression argument (G4)

With no new variable set:

1. `exposed_domain` = `console_domain` (alias, §3.3).
2. `hlf_network_domain` = `exposed_domain`, which V1 keeps outside
   `cluster_domain` ⇒ not cluster-local ⇒ `hlf_node_domain` =
   `exposed_domain` ⇒ `spec.deployer` **not rendered** ⇒ the deployer keeps
   using `networkinfo.domain`, as today.
3. `expose_console` = `true` ⇒ `spec.ingress` **not rendered** ⇒ class
   `nginx`, as today.
4. The duplicate `networkinfo:` key held the same value twice; YAML keeps the
   last one. Removing one copy does not change the parsed CR.
5. All `expose_*` = `true` ⇒ no per-endpoint Service, no CoreDNS rewrite.
6. V5 checks that node URLs end with `.` + `exposed_domain`, which is always
   true today (§2).

The CI `expose-all` leg is the check: it must run unchanged and pass.

---

## 9. Checks before implementing

**Run on 2026-10-16** on a local KIND cluster (`kindest/node:v1.25.3`,
macOS arm64) bootstrapped with `.github/scripts/kind_with_nginx.sh` and
`.github/scripts/deploy-console.sh` (nginx, `default` namespace, console
`hlf-console`, `exposed_domain` = `127-0-0-1.nip.io`). Collection rebuilt
from `move-ingress-plan` (2.1.3), Fabric CLI 2.5.15. Scripts, playbooks and
logs: [`.url_management_new_checks/`](./.url_management_new_checks/)
(see its `README.md`). The test resources were deleted afterwards.

| # | Check | How | Result |
|---|---|---|---|
| 1 | `spec.deployer.domain` reaches the node CRs | patch the console with `deployer.domain: default.svc.cluster.local`, create a CA (`Check1 CA`) through the `certificate_authority` module, read `IBPCA.spec.domain`, the connection profile and the URLs the console returns | **Pass**, with one caveat (finding F1). `IBPCA.spec.domain = default.svc.cluster.local`; console `api_url = https://default-check1-ca.default.svc.cluster.local:443`, `operations_url = https://default-check1-operations.default.svc.cluster.local:443`; TLS SANs `default-check1-ca`, `default-check1`, `default-check1-operations` `.default.svc.cluster.local`. With two hand-made per-endpoint Services (443 → 7054, 443 → 9443), `/cainfo` and `/healthz` answer through plain kube-dns, **no CoreDNS change**, and strict TLS verification against the CA's TLS cert passes (`ssl_verify_result=0`). |
| 2 | nginx ignores an Ingress with class `none` | set `IBPConsole.spec.ingress.class: none`, probe the console URL through nginx; then set it back to `nginx` | **Pass.** The operator updated the Ingress (`ingressClassName` and annotation `none`). nginx: `removing ingress because of unknown ingressclass`; the console URL went from HTTP 200 (console cert) to 404 (nginx fake cert). The in-cluster Service still answered 200. Back to `nginx`: 200 again. No dummy `IngressClass` needed. |
| 3 | a console update does not overwrite `spec.ingress` of a node CR | with `IBPCA.spec.ingress.class: none`, update the CA through the module (`resources.ca.requests` 100m/200M → 110m/210M) | **Pass.** The new resources reached the CR; `spec.ingress.class` stayed `none`, the Ingress stayed unserved (404 through nginx). The update rolls out a new CA pod because the resources changed, as expected. |
| 4 | athena self-signed SAN = console host of `exposed_domain` | `openssl s_client` through nginx (SNI = console host) and on the in-cluster Service `hlf-console:3000` | **Pass.** Same certificate both ways: `CN = SAN = default-hlf-console-console.127-0-0-1.nip.io` (O=`ibp2-auto-gen`, valid 2 years), stored in `/certs` on the console PVC. See finding F2 for the in-cluster name. |
| 5 | scenario B end to end: CA, peer, orderer created and joined, playbooks in-cluster, **no** CoreDNS change | CI leg `expose-none-internal` | **Not run.** Needs the in-cluster Ansible runner of sub-task 1.9: from the laptop, the module health waits can't resolve cluster-local names (finding F4). Checks 1 and 6 cover the domain and URL parts. |
| 6 | V5 on every URL shape | Ansible test on the real CA URLs plus samples | **Pass**, 10/10 cases: CA `https`, peer `grpcs`, orderer admin, empty `osnadmin_url` (skipped), wrong domain, wrong namespace, legacy mode, suffix trap (`x127-0-0-1.nip.io`). It also confirms V5 must compare with `hlf_node_domain`: comparing with `hlf_network_domain` (`cluster.local`) would accept a URL from another namespace. |
| 7 | patching `spec.ingress.class` on a node CR does not restart the node pod | note pod UID, `restartCount`, Deployment generation; patch `IBPCA.spec.ingress.class: none`; wait 30 s; compare | **Pass.** Same pod UID, 0 restarts, Deployment generation and revision unchanged. The Ingress switched to `none` in about 4 s; nginx then returned 404 for the CA SNI (`/cainfo` was 200 before). |

### 9.1 Findings

| # | Finding | Impact on the proposal |
|---|---|---|
| F1 | The deployer reads `settings.yaml` **only at startup**. After patching `spec.deployer.domain`, the operator updated the `hlf-console-deployer` ConfigMap and the mounted file within ~10 s, but a CA created next still got the old domain. After `kubectl rollout restart deploy/hlf-console`, the new domain was used. | Render `spec.deployer.domain` when the console is **created** (C2, C6), as proposed. Changing `hlf_network_domain` on an existing console needs a console restart and only affects nodes created afterwards; existing nodes keep their domain (§4.4). The console role should restart the console when it changes `spec.deployer.domain` on an existing CR, or refuse the change. |
| F2 | The console certificate only names `<ns>-<console>-console.<exposed_domain>`, not `hlf-console.<ns>.svc.<cluster_domain>`. | `console_incluster_url` works only without hostname verification. The collection never verifies (`validate_certs=False`), so it is not affected; strict in-cluster clients need `console_tls_secret` with the in-cluster name as an extra SAN. Document it in §5.3. |
| F3 | The CA meant to be `Check1 CA` was stored as `Check1`, and a second `certificate_authority` call with `name: Check1 CA` did not find it (HTTP 400 when it then tried to create a new CA). | **Closed (2026-10-16): test-harness error.** The playbook was run with `-e ca_display_name="Check1 CA"`; the shell passes `ca_display_name=Check1 CA`, and Ansible's key=value parser keeps only `Check1` (reproduced: that form gives `Check1`, `-e '{"ca_display_name":"Check1 CA"}'` gives `Check1 CA`). The console stored exactly what it received. No impact on the design. |
| F4 | From the laptop, the module health wait fails on `nodename nor servname provided` for cluster-local FQDNs. | Expected; confirms that scenario B playbooks must run in-cluster (sub-task 1.9). |

D4 can move to "on by default for unexposed components" for the CA, as
checks 2, 3 and 7 passed on a CA. The peer and orderer CRs use the same
Ingress manager; repeat check 3 on a peer update when sub-task 1.9 can run
scenario B.

---

## 10. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | If `hlf_network_domain == cluster_domain`: node FQDNs are `<service>.<namespace>.svc.<hlf_network_domain>` (`spec.deployer.domain = <namespace>.svc.<cluster_domain>`), `hlf_network_domain_is_cluster_local = true`, no CoreDNS rewrite. Otherwise: previous way, `<ns>-<cr>-<endpoint>.<hlf_network_domain>`, with per-endpoint-type rewrites when unexposed | **decided** (2026-10-16) |
| D2 | Default of `hlf_network_domain`: `exposed_domain` (no behaviour change) | **decided** (2026-10-16) |
| D3 | Unserved Ingress class: `unexposed_ingress_class`, default `none`, overridable | **decided** (2026-10-16) |
| D4 | Node Ingress neutralization (§5.4): opt-in `neutralize_node_ingresses: false`; revisit the default once §9 checks 2, 3 and 7 pass (passed on a CA 2026-10-16; peer check 3 pending) | **decided** (2026-10-16) |
| D5 | `console_domain`: deprecated alias of `exposed_domain`, removed in the release that removes nginx (roadmap deprecation timeline) | **decided** (2026-10-16) |
