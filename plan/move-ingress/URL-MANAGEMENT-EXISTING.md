# URL management: from the Fabric Ansible Collection to the Fabric Operator

How the URLs of every Fabric component (`api_url`, `operations_url`,
`grpcwp_url`, `osnadmin_url`) are built, which variable controls each part,
and where the collection consumes them. Input for hardening the domain
variables of [`MIGRATION-STEP-1.md`](./MIGRATION-STEP-1.md) (sub-tasks 1.1,
1.1b, 1.3b, 1.4b) and fixing the variable-scope finding of
[`REVIEW-MIGRATION-PLAN-STEP-1.md`](./REVIEW-MIGRATION-PLAN-STEP-1.md).

**Sources read (2026-10-16):**

| Codebase | Revision | Abbreviation below |
|---|---|---|
| this repository (`fabric-ansible-collection`) | `move-ingress-plan` @ `9490cc9` | *collection* |
| [`hyperledger-labs/fabric-operations-console`](https://github.com/hyperledger-labs/fabric-operations-console) — `packages/athena` (REST API) and `packages/fabric-deployer` | `main` @ `2ec7e1c` | *athena*, *deployer* |
| [`hyperledger-labs/fabric-operator`](https://github.com/hyperledger-labs/fabric-operator) | `main` @ `6ea612b` | *operator* |

Nothing here was checked against a running cluster.

---

## 1. Summary

1. **The collection never builds a node URL.** The organization roles and the
   `certificate_authority` / `peer` / `ordering_service` modules send only a
   **display name** to the console REST API. They have no domain, hostname
   or port parameter.
2. **The node domain is the console's domain.** `console_domain` →
   `IBPConsole.spec.networkinfo.domain` → deployer `Config.Domain` → every
   node CR's `spec.domain`. One value, set once, when the console is created.
3. **The node name is derived from the display name by athena**: lowercased,
   every non-`[a-z0-9]` character removed (`Org1 Peer` → `org1peer`). It
   becomes the CR name.
4. **The operator assembles every URL** as
   `<scheme>://<namespace>-<cr name>-<endpoint>.<spec.domain>:443`, writes it
   into the `<cr name>-connection-profile` ConfigMap, puts the same hostnames
   in the node TLS certificate and in the Ingress rules.
5. **The URLs flow back** operator ConfigMap → deployer → athena (stored in the
   component document) → collection modules (`api_url`, `operations_url`, …),
   which use them as-is for health waits, enrollment, channel configuration
   and connection profiles.
6. **`ingress_domain` (in `fabric_operator_crds/defaults`) is used nowhere.**
   The plan's `ingress_domain` therefore has no effect today: whatever the plan
   calls `ingress_domain` is, in reality, `console_domain`.
7. **`cluster_domain` plays no part in this chain.** It is only needed by the
   collection's own Step 1 additions (per-endpoint Services, CoreDNS rewrites).

```
 collection                   console (athena + deployer)              operator
 ──────────                   ───────────────────────────              ────────
 console_domain ─────────────► IBPConsole.spec.networkinfo.domain
   (fabric_console role /        │  (operator writes it to the
    00-deploy-fabric-console)    │   deployer settings.yaml)
                                 ▼
                              deployer Config.Domain ──────────────► <CR>.spec.domain
 module(name="Org1 Peer") ──► athena make_subdomain()                       │
   POST /ak/api/v3/             "org1peer" = dep_component_id ─────► <CR>.metadata.name
   kubernetes/components/                                                   │
   fabric-peer                                                              ▼
                                                     GetEndpoints(): <ns>-<cr>-<ep>.<domain>:443
                                                       ├─► <cr>-connection-profile ConfigMap
                                                       ├─► TLS CSR hosts (SANs)
                                                       └─► Ingress rules (nginx, SSL passthrough)
                                                                            │
 module result.api_url ◄──── athena component doc ◄──── deployer GET ◄──────┘
   operations_url, …            api_url, operations_url, …   endpoints.api, .operations, …
```

---

## 2. Step 1 — The domain: `console_domain` is the only input

### 2.1 Collection side

`console_domain` is the single domain variable of the collection. It is
**mandatory** for both console roles
(`roles/fabric_console/tasks/create.yml:10-13`,
`roles/hlfsupport_console/tasks/create.yml:10-13`) and rendered into the
`IBPConsole` CR:

| Writer | Location |
|---|---|
| `fabric_console` role | `roles/fabric_console/templates/k8s/hlf-operations-console.yaml.j2:17-18` **and again** `:34-35` (duplicate `networkinfo:` key, same value) — same in `openshift/` |
| `hlfsupport_console` role | `roles/hlfsupport_console/templates/{k8s,openshift}/console.yml.j2:21` |
| Tutorial / CI (inline CR, role not used) | `tutorial/00-deploy-fabric-console.yml:15` (`hlf_console_domain`, default `127-0-0-1.nip.io`), `:59` |
| CI | `.github/workflows/fvtest.yml:36` (`<runner-ip>.nip.io`), `.github/scripts/deploy-console.sh:45` |

`ingress_domain: localho.st` is declared in
`roles/fabric_operator_crds/defaults/main.yml:46` and **referenced by no task,
template, module or script** in the repository.

### 2.2 Console → deployer

- *operator* `pkg/offering/base/console/console.go:519`: an `IBPConsole`
  without `networkinfo.domain` is rejected.
- *operator* `pkg/offering/base/console/override/deployercm.go:84-89`: the
  domain is copied to the deployer's `settings.yaml` (`config.Domain`).
  `:173-174`: `spec.deployer.domain`, if set, **overrides** it ("used for
  passing separate domains for optools and deployer"). The collection never
  sets `spec.deployer`.
- *deployer* `config/config_struct.go:57`: `Domain string \`json:"domain"\``.

### 2.3 Deployer → node CRs

The deployer writes its `Config.Domain` into every CR it creates, ignoring any
domain from the API request (none is sent anyway):

| Component | *deployer* location | CR field |
|---|---|---|
| CA | `deployer/components/ca/ca.go:160` | `IBPCA.spec.domain` |
| Peer | `deployer/components/peer/peer.go:241` | `IBPPeer.spec.domain` |
| Orderer | `deployer/components/orderer/orderer.go:229` (cluster), `:407` (pre-create) | `IBPOrderer.spec.domain` |

**Consequence:** all CAs, peers and orderers created through one console share
the console's domain. A node domain cannot be chosen per component, and the
domain cannot be changed by the collection after the console exists.

### 2.4 Console's own URL

Same domain, different hostname shape (no CR-name-based label):

- Ingress host: `<ns>-<console name>-console.<domain>`
  (*operator* `pkg/offering/k8s/console/override/ingress.go:56`).
- `HOST_URL=https://<ns>-<console name>-console.<domain>:443`
  (*operator* `pkg/offering/k8s/console/override/envcm.go:41`).
- The collection prints the same string
  (`roles/fabric_console/tasks/k8s/create.yml:59`,
  `tutorial/00-deploy-fabric-console.yml:145`), and CI builds `API_ENDPOINT`
  from it (`fvtest.yml:57`, `deploy-console.sh:47`). The collection's
  `api_endpoint` variable is this URL; it is the only URL the collection
  composes itself.

---

## 3. Step 2 — The node name: built by athena from the display name

The modules send a payload with `display_name` (and `cluster_name` for an
ordering service), never `id` / `component_name`:

| Module | Payload | Endpoint |
|---|---|---|
| `certificate_authority` | `plugins/modules/certificate_authority.py:464-469` | `POST /ak/api/v3/kubernetes/components/fabric-ca` (`plugins/module_utils/consoles.py:242`) |
| `peer` | `plugins/modules/peer.py:796-803` | `…/fabric-peer` (`consoles.py:446`) |
| `ordering_service` | `plugins/modules/ordering_service.py:684-694` | `…/fabric-orderer` (`consoles.py:654`) |

athena turns the display name into the deployer id, which becomes the CR name
(*athena* `libs/comp_formatting_lib.js:538`, `make_subdomain()` at `:719-748`,
`build_id()` in `libs/component_lib.js:229-259`):

1. If the request has an `id`: lowercased, every non-`[a-zA-Z0-9]` character
   removed, **used as-is**. The collection never sends one.
2. Otherwise, from the display name:
   - lowercased, characters outside `[a-zA-Z0-9-_]` removed;
   - prefixed with `ibp` if it does not start with a letter;
   - truncated to 64 characters;
   - **if already taken** (by another deployer id or document id): a numeric
     suffix is incremented, or `_0` appended (`component_lib.js:269-281`);
   - finally `-` and `_` are removed;
   - if still taken: random `id0<random>`.

| Display name | CR name |
|---|---|
| `Org1 CA` | `org1ca` |
| `Org1 Peer` | `org1peer` |
| `Org1 Peer` (second time, name taken) | `org1peer0` (`org1peer_0` → `_` removed) |
| `Org1 Peer1` (taken) | `org1peer2` |
| `1st Peer` | `ibp1stpeer` |

**Ordering nodes.** The ordering service CR name comes from the same function
(`Ordering Service` → `orderingservice`). The operator then names node *i*
`<cr name>node<i>`, `i` starting at 1 (*operator*
`pkg/offering/base/orderer/orderer.go:428`,
`pkg/offering/base/orderer/override/orderernode.go:59`). athena names the
display names `Ordering Service_1`, `_2`, … (`comp_formatting_lib.js:463-466`).

**Consequence for assumptions S1/S2 of sub-task 1.3b:** "lowercase + remove
non-`[a-z0-9]`" is right for a **fresh** name. It is wrong when the name is
already taken, when it starts with a digit, or when it exceeds 64 characters.
The only reliable source for the CR name is the URL the console returns
(first DNS label minus `<ns>-` and `-<endpoint>`), or `dep_component_id` in
the component document.

---

## 4. Step 3 — The URLs: assembled by the operator

### 4.1 Format

`<scheme>://<namespace>-<cr name>-<endpoint>.<spec.domain>:443`

| Component | Endpoint | URL (operator) | Console field | Native port behind it | *operator* source |
|---|---|---|---|---|---|
| CA | `ca` | `https://…-ca.<d>:443` | `api_url` (also `ca_url`) | 7054 | `pkg/offering/base/ca/ca.go:606-611` |
| CA | `operations` | `https://…-operations.<d>:443` | `operations_url` | 9443 | idem |
| Peer | `peer` | `grpcs://…-peer.<d>:443` | `api_url` | 7051 | `pkg/offering/base/peer/peer.go:1057-1063` |
| Peer | `operations` | `https://…-operations.<d>:443` | `operations_url` | 9443 | idem |
| Peer | `grpcweb` | `https://…-grpcweb.<d>:443` | `grpcwp_url` | 7443 | idem |
| Orderer node | `orderer` | `grpcs://…-orderer.<d>:443` | `api_url` | 7050 | `pkg/offering/base/orderer/node.go:1076-1087` |
| Orderer node | `operations` | `https://…-operations.<d>:443` | `operations_url` | 8443 | idem |
| Orderer node | `grpcweb` | `https://…-grpcweb.<d>:443` | `grpcwp_url` | 7443 | idem |
| Orderer node | `admin` | `https://…-admin.<d>:443` (Fabric ≥ 2.4.1 only) | `osnadmin_url` | 9443 | idem |

`<namespace>` is the namespace the console's deployer runs in; all nodes are
created in it.

### 4.2 The same hostnames are used in three places

The operator derives three artefacts from the same `<ns>-<cr>-<endpoint>.<domain>`
strings. They therefore always agree with each other:

1. **Connection profile** — ConfigMap `<cr name>-connection-profile`
   (`ca.go:556`, `peer.go:1004`, `node.go:1028`), field `endpoints`.
2. **TLS certificate SANs** — CSR hosts for peers
   (`pkg/offering/k8s/peer/peer.go:133-138`) and orderers
   (`pkg/offering/k8s/orderer/orderer.go:131-145`), plus the legacy
   `<ns>-<cr>.<domain>` and `127.0.0.1`. CA: self-generated certificate with
   `-ca`, the legacy name and `-operations` (`pkg/offering/base/ca/ca.go:806-818`),
   reused by the operations port (`pkg/initializer/ca/ca.go:295-298`).
3. **Ingress rules** — one host per endpoint, nginx SSL passthrough
   (`pkg/offering/k8s/{ca,peer,orderer}/override/ingress.go`,
   `definitions/*/ingress.yaml` annotation `ssl-passthrough: "true"`).

The certificate hostnames are fixed at **first enrollment**. Changing the
domain afterwards updates the CR's CSR hosts but does not re-enroll
(operator TODO at `pkg/offering/k8s/orderer/orderer.go:140`). The domain is
therefore effectively immutable for existing nodes.

---

## 5. Step 4 — The URLs flow back to the collection

1. *deployer* reads `<cr name>-connection-profile` and returns `endpoints`
   (e.g. `deployer/components/orderer/get.go`, `getEndpoints()`). It also adds
   legacy `*_saas` variants (`<ns>-<cr>.<domain>:7050/8443/9443/7054`, no
   endpoint label, native ports).
2. *athena* copies `endpoints.api/.operations/.grpcweb/.admin` to
   `api_url`, `operations_url`, `grpcwp_url`, `osnadmin_url`
   (`libs/comp_formatting_lib.js:1026-1090`, stored at `:386-394`).
   The `*_saas` URLs are only used for components **migrated from IBP SaaS**
   (`:121-135`).
3. The collection reads them back in `extract_ca_info` / `extract_peer_info` /
   `extract_ordering_service_node_info`
   (`plugins/module_utils/consoles.py:366-371`, `:574-579`, `:876-896`) and
   returns them as module results.

### 5.1 Where the collection consumes them

| Use | Field | Location |
|---|---|---|
| Health wait inside the create module | `operations_url` + `/healthz` | `plugins/module_utils/peers.py:105-121`, `certificate_authorities.py:115-124`, same pattern in `ordering_services.py` |
| Peer / orderer enrollment against the CA | CA `api_url` → `host`, `port` | `plugins/modules/peer.py:595-626`, `ordering_service.py:462-490` |
| Channel config, consenters | orderer `api_url` → `host`, `port or 443` | `plugins/modules/channel_config.py:501-518`, `channel_consenter.py:165-204`, `channel_consenters.py:166-229` |
| Anchor peers | peer `api_url` | `plugins/modules/channel_member.py:196-199` |
| Connection profiles | `api_url` | `plugins/modules/connection_profile.py:197-206` |
| Legacy-to-open-source URL translation | adds `-<type>` to the first label and forces `:443` when port ≠ 443 | `plugins/module_utils/url_utils.py:8-30`, used by `*_metadata.py` |
| Anchor-peer rewrite in channel config | adds `-peer`, forces `:443` | `plugins/modules/channel_members.py:121-131` |

TLS: every console and node call uses `validate_certs=False`
(`consoles.py`, `peers.py:111`, `certificate_authorities.py:121`). The
`peer` / `osnadmin` CLI calls and node-to-node gRPC do verify hostnames
against the SANs of §4.2.

The last two rows hard-code the operator's URL **shape** (endpoint suffix in
the first label, port 443). Step 3 of the roadmap (`:7050/:7051/:7054`)
must revisit them.

---

## 6. What this means for the Step 1 plan

These are findings to act on; the decisions belong in
[`MIGRATION-STEP-1.md`](./MIGRATION-STEP-1.md).

1. **`ingress_domain` must not be an independent variable.** The node FQDNs
   use the console's `networkinfo.domain`, i.e. `console_domain`. A separate
   `ingress_domain` with another value would make the CoreDNS rewrites
   (1.4b), the cluster-local guard (1.1b) and the Service naming (1.3b) work on
   hostnames the operator never generates. Either drop `ingress_domain` and
   use `console_domain`, or keep it as an alias defaulting to
   `console_domain` and fail on a mismatch.
2. **The organization roles do not know the domain.** They only have
   `api_endpoint`. Options, in order of reliability:
   - parse the domain and CR names from the URLs the modules return
     (strip `<ns>-<cr>-<endpoint>.`), available only **after** the module call;
   - read `IBPConsole.spec.networkinfo.domain` with `k8s_info` (needs the
     console name and namespace, which these roles do not have today);
   - require it as an input variable, cross-checked against the returned
     URLs after the call.

   Sub-task 1.3b needs the Services **before** the module call (the health
   wait runs inside it), so a pre-call value is required; the post-call
   URLs can then double-check it.
3. **CR names must not be re-derived.** Assumption S1 breaks on name
   collisions, leading digits and long names (§3). Sub-task 1.3b could pass
   an explicit `id` to the console (athena then uses it verbatim, §3 rule 1),
   but the collection modules do not expose it today. Otherwise, the verify
   step of 1.3b must compare against the returned URLs and fail loudly.
4. **Variable scope.** Domain-related variables live in roles that are run
   by separate playbooks (`fabric_operator_crds`, `fabric_console`,
   `endorsing_organization`, `ordering_organization`). The derivation logic
   (normalisation, cluster-domain lookup, cluster-local facts) needs a single
   home reachable from all of them — a shared role called via
   `include_role`, as already done for `k8s_endpoint_services`.
5. **`cluster_domain` stays a collection-only concern.** No component of the
   chain above uses it; it is only needed to name the in-cluster Service
   FQDNs (`<svc>.<ns>.svc.<cluster_domain>`) that the collection adds in
   Step 1.
6. **The domain is fixed for the lifetime of the nodes** (§4.2). The nginx →
   Gateway API migration must keep the same `console_domain`.
