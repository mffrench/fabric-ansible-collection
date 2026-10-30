# Step 1 — Scenarios A, B and C

Flow diagrams of the three scenarios handled by
[`MIGRATION-STEP-1.md`](./MIGRATION-STEP-1.md#scenarios) (design:
[`URL-MANAGEMENT-NEW.md`](./URL-MANAGEMENT-NEW.md) §4), one diagram per
component: console, CA, peers, orderers.

Scenario D (nodes exposed under their own domain, for example
`fabric.example.com`) is Step 3 and is not drawn here
(URL-MANAGEMENT-NEW.md §4.4).

Names are those of the local KIND test cluster: namespace `default`, console
`hlf-console`, CA `org1ca`, peers `org1peer` and `org2peer` (two
organizations), ordering nodes `orderingservicenode1` to `3`, chaincode server
`fabcar-ccaas` (CCaaS). In the labels:
- `D` = `127-0-0-1.nip.io`, the exposed domain (scenarios A and C);
- `S` = `default.svc.cluster.local`, the HLF node domain of scenario B.

Legend: **red** box and arrows = through nginx; **blue** = per-endpoint Service
(sub-task 1.6); **yellow** = CoreDNS endpoint rewrite (sub-task 1.8);
**purple** = operations and grpc-web endpoints; dashed = data sent back on a
stream the other side opened (events, blocks). Numbers give the order of the
steps.

Checked on live CRs: the peer gossip endpoint is `<ns>-<peer>-peer.<domain>:443`,
the operator enrolls nodes at `<ns>-<ca>-ca.<domain>:443`, and orderers have no
separate cluster port, so Raft uses `<ns>-<node>-orderer.<domain>:443`. The
console proxies the UI's CA and grpc-web requests (URL-MANAGEMENT-NEW.md §5.3).

## Summary

| Flow | A | B | C |
|---|---|---|---|
| Ansible → console REST API | nginx, from outside | Service `hlf-console`, from the in-cluster Job | same as B |
| Operator → CA (node enrollment) | nginx | Service | CoreDNS rewrite → Service |
| Console → CA, operations, grpc-web | nginx | Services | CoreDNS rewrite → Services |
| App → peer (invoke, events) | nginx | Service, from any namespace | CoreDNS rewrite → Service |
| Peer → peer (endorsement, gossip) | nginx | Service | CoreDNS rewrite → Service |
| Peer → chaincode server (CCaaS) | Service | Service | Service |
| App or gateway peer → orderer (broadcast) | nginx | Service | CoreDNS rewrite → Service |
| Orderer → orderer (Raft) | nginx | Service | CoreDNS rewrite → Service |
| Orderer → peer (block delivery) | nginx | Service | CoreDNS rewrite → Service |
| From outside the cluster | everything, through nginx | nothing (the console can be exposed by hand) | nothing |

---

<a id="scenario-a"></a>
## Scenario A — everything exposed, non-Kubernetes FQDNs (default)

Every name is under `D`. From outside, `D` resolves to the KIND host, and port
443 reaches nginx, which routes on the TLS SNI (SSL passthrough). Inside the
cluster, the CoreDNS wildcard sends `*.D` to nginx too. So **every internal
flow** (operator to CA, console to nodes, gossip, endorsement, broadcast, Raft,
block delivery) makes a round trip through nginx, although both ends run in
the same cluster, most often in the same namespace: one extra hop, all the
network's traffic on the ingress controller, and nothing works when it is
down. The red arrows show these internal flows.

<a id="scenario-a-console"></a>
### Console

```mermaid
flowchart LR
  subgraph out["Outside the cluster"]
    user["Browser or Ansible"]
  end
  subgraph k8s["KIND cluster, namespace default"]
    nginx["nginx Ingress controller<br/>port 443, SSL passthrough"]
    console["console pod<br/>athena 3000, deployer"]
    api["Kubernetes API"]
    op["Fabric Operator"]
    ca["CA pod org1ca<br/>7054 api"]
    ops["CA, peer and orderer pods<br/>operations 9443, 8443, grpcweb 7443"]
  end
  user -->|"1 REST API and UI<br/>default-hlf-console-console.D:443"| nginx
  nginx -->|"console Ingress"| console
  console -->|"2 deployer creates IBPCA, IBPPeer, IBPOrderer"| api
  op -->|"3 watches the CRs, creates Deployments, Services, Ingresses"| api
  op -->|"4 node enrollment<br/>default-org1ca-ca.D:443"| nginx
  console -->|"5 UI proxy to the CA: default-org1ca-ca.D:443<br/>6 status and grpc-web: *-operations.D, *-grpcweb.D"| nginx
  nginx -->|"7054"| ca
  nginx -->|"9443, 8443, 7443"| ops
  classDef red fill:#fde2e2,stroke:#c62828,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  class nginx red
  class ops purple
  linkStyle 4,5 stroke:#c62828,stroke-width:2px
```

<a id="scenario-a-ca"></a>
### CA

```mermaid
flowchart LR
  subgraph out["Outside the cluster"]
    admin["Ansible or fabric-ca-client<br/>CA admin"]
    web["Browser, console UI"]
  end
  subgraph k8s["KIND cluster, namespace default"]
    nginx["nginx Ingress controller"]
    console["console pod"]
    op["Fabric Operator"]
    ca["CA pod org1ca<br/>7054 api"]
    caops["CA pod org1ca<br/>9443 operations"]
  end
  admin -->|"1 enroll the registrar: POST /enroll<br/>2 create an identity: POST /register<br/>3 enroll it: POST /enroll<br/>4 revoke it: POST /revoke<br/>default-org1ca-ca.D:443"| nginx
  web -->|"same actions in the UI<br/>default-hlf-console-console.D:443"| nginx
  nginx -->|"console Ingress"| console
  console -->|"proxy to the CA<br/>default-org1ca-ca.D:443"| nginx
  op -->|"node enrollment, ecert and TLS<br/>default-org1ca-ca.D:443"| nginx
  console -->|"status<br/>default-org1ca-operations.D/healthz"| nginx
  nginx -->|"7054"| ca
  nginx -->|"9443"| caops
  classDef red fill:#fde2e2,stroke:#c62828,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  class nginx red
  class caops purple
  linkStyle 3,4,5 stroke:#c62828,stroke-width:2px
```

<a id="scenario-a-peers"></a>
### Peers

```mermaid
flowchart LR
  subgraph out["Outside the cluster"]
    app["Client application<br/>Fabric Gateway SDK"]
    web["Browser, console UI"]
  end
  subgraph k8s["KIND cluster, namespace default"]
    nginx["nginx Ingress controller"]
    console["console pod"]
    p1["peer pod org1peer<br/>7051 gRPC"]
    p1ops["peer pod org1peer<br/>9443 operations, 7443 grpcweb"]
    p2["peer pod org2peer<br/>other organization, 7051"]
    cc["Service fabcar-ccaas<br/>chaincode server, 9999"]
  end
  app -->|"1 invoke: Evaluate, Endorse, Submit<br/>default-org1peer-peer.D:443"| nginx
  nginx -->|"7051"| p1
  p1 -.->|"2 block and chaincode events<br/>on the stream the app opened, back through nginx"| app
  p1 -->|"3 endorsement by org2<br/>4 gossip with the other peers<br/>default-org2peer-peer.D:443"| nginx
  nginx -->|"7051"| p2
  p1 -->|"5 chaincode, direct Service"| cc
  web -->|"default-hlf-console-console.D:443"| nginx
  nginx -->|"console Ingress"| console
  console -->|"6 grpc-web for the UI: default-org1peer-grpcweb.D:443<br/>7 status: default-org1peer-operations.D/healthz"| nginx
  nginx -->|"7443, 9443"| p1ops
  classDef red fill:#fde2e2,stroke:#c62828,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  class nginx red
  class p1ops purple
  linkStyle 3,8 stroke:#c62828,stroke-width:2px
```

<a id="scenario-a-orderers"></a>
### Orderers

```mermaid
flowchart LR
  subgraph out["Outside the cluster"]
    app["Client application<br/>SDK without the gateway"]
    ans["Ansible: osnadmin, channel join"]
  end
  subgraph k8s["KIND cluster, namespace default"]
    nginx["nginx Ingress controller"]
    p1["peer pod org1peer<br/>gateway and committing peer"]
    console["console pod"]
    o1["orderer node 1<br/>7050 gRPC"]
    o2["orderer node 2<br/>7050 gRPC"]
    o3["orderer node 3<br/>7050 gRPC"]
    oadm["orderer node 1<br/>9443 admin"]
    oops["orderer nodes<br/>8443 operations, 7443 grpcweb"]
  end
  app -->|"1 broadcast<br/>default-orderingservicenode1-orderer.D:443"| nginx
  p1 -->|"1 broadcast from the gateway<br/>3 deliver: pull the new blocks<br/>*-orderer.D:443"| nginx
  o1 -->|"2 Raft with the other consenters<br/>default-orderingservicenode2-orderer.D:443, node3"| nginx
  ans -->|"default-orderingservicenode1-admin.D:443"| nginx
  console -->|"status and grpc-web<br/>*-operations.D, *-grpcweb.D"| nginx
  nginx -->|"7050"| o1
  nginx -->|"7050"| o2
  nginx -->|"7050"| o3
  nginx -->|"9443"| oadm
  nginx -->|"8443, 7443"| oops
  classDef red fill:#fde2e2,stroke:#c62828,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  class nginx red
  class oops purple
  linkStyle 1,2,4 stroke:#c62828,stroke-width:2px
```

---

<a id="scenario-b"></a>
## Scenario B — nothing exposed, cluster-local HLF domain (Step 1 target)

The console's deployer gives every node a name under `S`
(`spec.deployer.domain`). Each name is the FQDN of a per-endpoint Service that
maps 443 to the native port, so plain kube-dns resolves it: no CoreDNS change,
no nginx. The organization playbooks run in-cluster (the `ansible-runner` Job,
sub-task 1.9). An application in another namespace reaches the nodes the same
way, if the NetworkPolicies of `default` let it in. Nothing is reachable from
outside the cluster.

<a id="scenario-b-console"></a>
### Console

```mermaid
flowchart LR
  web["Browser, outside the cluster"]
  subgraph k8s["KIND cluster, namespace default"]
    job["ansible-runner Job"]
    svcC["Service hlf-console<br/>3000, created by the operator"]
    console["console pod<br/>athena, deployer<br/>deployer.domain S"]
    api["Kubernetes API"]
    op["Fabric Operator"]
    sCA["Service default-org1ca-ca<br/>443 to 7054"]
    ca["CA pod org1ca"]
    sOps["Services *-operations, *-grpcweb<br/>443 to 9443, 8443, 7443"]
    nodes["CA, peer and orderer pods"]
    nginx["nginx Ingress controller"]
  end
  job -->|"1 REST API<br/>hlf-console.default.svc.cluster.local:3000"| svcC
  svcC --> console
  console -->|"2 deployer creates the CRs"| api
  op -->|"3 watches the CRs, creates the pods"| api
  op -->|"4 node enrollment<br/>default-org1ca-ca.S:443"| sCA
  sCA --> ca
  console -->|"5 UI proxy to the CA"| sCA
  console -->|"6 status and grpc-web<br/>*-operations.S, *-grpcweb.S"| sOps
  sOps --> nodes
  web -.->|"default-hlf-console-console.example.com<br/>not served: Ingress class none"| nginx
  classDef blue fill:#e3f2fd,stroke:#1565c0,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  class svcC,sCA blue
  class sOps purple
```

<a id="scenario-b-ca"></a>
### CA

```mermaid
flowchart LR
  subgraph k8s["KIND cluster, namespace default"]
    job["ansible-runner Job<br/>CA admin"]
    console["console pod<br/>UI proxy, once the console is exposed"]
    op["Fabric Operator"]
    sCA["Service default-org1ca-ca<br/>443 to 7054"]
    sCAo["Service default-org1ca-operations<br/>443 to 9443"]
    ca["CA pod org1ca"]
  end
  job -->|"1 enroll the registrar: POST /enroll<br/>2 create an identity: POST /register<br/>3 enroll it: POST /enroll<br/>4 revoke it: POST /revoke<br/>default-org1ca-ca.S:443"| sCA
  console -->|"same actions from the UI"| sCA
  op -->|"node enrollment, ecert and TLS"| sCA
  sCA -->|"7054"| ca
  console -->|"status"| sCAo
  sCAo -->|"9443"| ca
  classDef blue fill:#e3f2fd,stroke:#1565c0,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  class sCA blue
  class sCAo purple
```

<a id="scenario-b-peers"></a>
### Peers

```mermaid
flowchart LR
  ext["Application outside the cluster"]
  blocked["no route: nothing exposed<br/>Step 3 exposes the peers"]
  subgraph k8s["KIND cluster"]
    subgraph apps["namespace apps"]
      app["Client application<br/>Fabric Gateway SDK"]
    end
    subgraph nsdef["namespace default"]
      sP1["Service default-org1peer-peer<br/>443 to 7051"]
      p1["peer pod org1peer"]
      sP2["Service default-org2peer-peer<br/>443 to 7051"]
      p2["peer pod org2peer"]
      cc["Service fabcar-ccaas<br/>9999"]
      console["console pod"]
      sOps["Services default-org1peer-operations, -grpcweb<br/>443 to 9443, 7443"]
    end
  end
  app -->|"1 invoke<br/>default-org1peer-peer.S:443"| sP1
  sP1 --> p1
  p1 -.->|"2 block and chaincode events<br/>on the stream the app opened"| app
  p1 -->|"3 endorsement by org2, 4 gossip<br/>default-org2peer-peer.S:443"| sP2
  sP2 --> p2
  p1 -->|"5 chaincode"| cc
  console -->|"6 grpc-web, 7 status"| sOps
  sOps --> p1
  ext -.-> blocked
  classDef blue fill:#e3f2fd,stroke:#1565c0,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  class sP1,sP2 blue
  class sOps purple
```

<a id="scenario-b-orderers"></a>
### Orderers

```mermaid
flowchart LR
  ext["Application outside the cluster"]
  blocked["no route: nothing exposed<br/>Step 3 exposes the orderers"]
  subgraph k8s["KIND cluster"]
    subgraph apps["namespace apps"]
      app["Client application<br/>SDK without the gateway"]
    end
    subgraph nsdef["namespace default"]
      job["ansible-runner Job<br/>osnadmin"]
      p1["peer pod org1peer<br/>gateway and committing peer"]
      s1["Service default-orderingservicenode1-orderer<br/>443 to 7050"]
      s2["Service ...node2-orderer<br/>443 to 7050"]
      s3["Service ...node3-orderer<br/>443 to 7050"]
      sa["Service default-orderingservicenode1-admin<br/>443 to 9443"]
      o1["orderer node 1"]
      o2["orderer node 2"]
      o3["orderer node 3"]
      console["console pod"]
      sOps["Services *-operations, *-grpcweb<br/>443 to 8443, 7443"]
    end
  end
  app -->|"1 broadcast<br/>default-orderingservicenode1-orderer.S:443"| s1
  p1 -->|"1 broadcast from the gateway<br/>3 deliver: pull the new blocks"| s1
  s1 --> o1
  o1 -->|"2 Raft"| s2
  o1 -->|"2 Raft"| s3
  s2 --> o2
  s3 --> o3
  job -->|"channel join"| sa
  sa --> o1
  console -->|"status, grpc-web"| sOps
  sOps --> o1
  ext -.-> blocked
  classDef blue fill:#e3f2fd,stroke:#1565c0,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  class s1,s2,s3,sa blue
  class sOps purple
```

---

<a id="scenario-c"></a>
## Scenario C — nothing exposed, non-Kubernetes FQDNs

Same Services and same flows as B, but the nodes keep the names of A (under
`D`). Those names match no Service, so CoreDNS answers them with **one rewrite
per endpoint type**, written before the `*.D` wildcard: each name gets the IP
of its own Service, and the client keeps dialling the original name, so TLS
still matches. The rules are cluster-wide: an application in another
namespace gets the same answer. They only match the names of namespace
`default` (`^(default-[a-z0-9]+-<endpoint>)`). The console name matches no
rule: it still goes to nginx, which does not serve it (class `none`), so the
Job uses the console Service.

<a id="scenario-c-console"></a>
### Console

```mermaid
flowchart LR
  subgraph k8s["KIND cluster, namespace default"]
    job["ansible-runner Job"]
    svcC["Service hlf-console<br/>3000"]
    console["console pod<br/>networkinfo.domain D<br/>no deployer.domain"]
    api["Kubernetes API"]
    op["Fabric Operator"]
    dns["CoreDNS<br/>one rewrite per endpoint type"]
    sCA["Service default-org1ca-ca<br/>443 to 7054"]
    ca["CA pod org1ca"]
    sOps["Services *-operations, *-grpcweb<br/>443 to 9443, 8443, 7443"]
    nodes["CA, peer and orderer pods"]
    nginx["nginx Ingress controller"]
  end
  job -->|"1 REST API<br/>hlf-console.default.svc.cluster.local:3000"| svcC
  svcC --> console
  console -->|"2 deployer creates the CRs"| api
  op -->|"3 watches the CRs, creates the pods"| api
  op -->|"4 node enrollment<br/>default-org1ca-ca.D:443"| dns
  console -->|"5 UI proxy to the CA<br/>6 status and grpc-web"| dns
  dns -->|"ca rule"| sCA
  sCA --> ca
  dns -->|"operations and grpcweb rules"| sOps
  sOps --> nodes
  dns -.->|"default-hlf-console-console.D: wildcard<br/>Ingress class none, not served"| nginx
  classDef blue fill:#e3f2fd,stroke:#1565c0,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  classDef yellow fill:#fff8e1,stroke:#f9a825,color:#000
  class svcC,sCA blue
  class sOps purple
  class dns yellow
```

<a id="scenario-c-ca"></a>
### CA

```mermaid
flowchart LR
  subgraph k8s["KIND cluster, namespace default"]
    job["ansible-runner Job<br/>CA admin"]
    console["console pod<br/>UI proxy, once the console is exposed"]
    op["Fabric Operator"]
    dns["CoreDNS<br/>ca and operations rules"]
    sCA["Service default-org1ca-ca<br/>443 to 7054"]
    sCAo["Service default-org1ca-operations<br/>443 to 9443"]
    ca["CA pod org1ca"]
  end
  job -->|"1 enroll the registrar: POST /enroll<br/>2 create an identity: POST /register<br/>3 enroll it: POST /enroll<br/>4 revoke it: POST /revoke<br/>default-org1ca-ca.D:443"| dns
  console -->|"same actions from the UI, status"| dns
  op -->|"node enrollment, ecert and TLS"| dns
  dns -->|"ca rule"| sCA
  dns -->|"operations rule"| sCAo
  sCA -->|"7054"| ca
  sCAo -->|"9443"| ca
  classDef blue fill:#e3f2fd,stroke:#1565c0,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  classDef yellow fill:#fff8e1,stroke:#f9a825,color:#000
  class sCA blue
  class sCAo purple
  class dns yellow
```

<a id="scenario-c-peers"></a>
### Peers

```mermaid
flowchart LR
  ext["Application outside the cluster"]
  blocked["no route: nothing exposed<br/>Step 3 exposes the peers"]
  subgraph k8s["KIND cluster"]
    subgraph apps["namespace apps"]
      app["Client application<br/>Fabric Gateway SDK"]
    end
    subgraph nsdef["namespace default"]
      dns["CoreDNS<br/>peer, operations, grpcweb rules"]
      sP1["Service default-org1peer-peer<br/>443 to 7051"]
      p1["peer pod org1peer"]
      sP2["Service default-org2peer-peer<br/>443 to 7051"]
      p2["peer pod org2peer"]
      cc["Service fabcar-ccaas<br/>9999"]
      console["console pod"]
      sOps["Services default-org1peer-operations, -grpcweb<br/>443 to 9443, 7443"]
    end
  end
  app -->|"1 invoke<br/>default-org1peer-peer.D:443"| dns
  dns -->|"peer rule"| sP1
  sP1 --> p1
  p1 -.->|"2 block and chaincode events<br/>on the stream the app opened"| app
  p1 -->|"3 endorsement by org2, 4 gossip<br/>default-org2peer-peer.D:443"| dns
  dns -->|"peer rule"| sP2
  sP2 --> p2
  p1 -->|"5 chaincode, direct Service"| cc
  console -->|"6 grpc-web, 7 status"| dns
  dns -->|"grpcweb and operations rules"| sOps
  sOps --> p1
  ext -.-> blocked
  classDef blue fill:#e3f2fd,stroke:#1565c0,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  classDef yellow fill:#fff8e1,stroke:#f9a825,color:#000
  class sP1,sP2 blue
  class sOps purple
  class dns yellow
```

<a id="scenario-c-orderers"></a>
### Orderers

```mermaid
flowchart LR
  ext["Application outside the cluster"]
  blocked["no route: nothing exposed<br/>Step 3 exposes the orderers"]
  subgraph k8s["KIND cluster"]
    subgraph apps["namespace apps"]
      app["Client application<br/>SDK without the gateway"]
    end
    subgraph nsdef["namespace default"]
      job["ansible-runner Job<br/>osnadmin"]
      p1["peer pod org1peer<br/>gateway and committing peer"]
      dns["CoreDNS<br/>orderer, admin, operations, grpcweb rules"]
      s1["Service default-orderingservicenode1-orderer<br/>443 to 7050"]
      s2["Service ...node2-orderer<br/>443 to 7050"]
      s3["Service ...node3-orderer<br/>443 to 7050"]
      sa["Service default-orderingservicenode1-admin<br/>443 to 9443"]
      o1["orderer node 1"]
      o2["orderer node 2"]
      o3["orderer node 3"]
      console["console pod"]
      sOps["Services *-operations, *-grpcweb<br/>443 to 8443, 7443"]
    end
  end
  app -->|"1 broadcast<br/>default-orderingservicenode1-orderer.D:443"| dns
  p1 -->|"1 broadcast from the gateway<br/>3 deliver: pull the new blocks"| dns
  o1 -->|"2 Raft<br/>default-orderingservicenode2-orderer.D:443, node3"| dns
  job -->|"channel join<br/>default-orderingservicenode1-admin.D:443"| dns
  console -->|"status, grpc-web"| dns
  dns -->|"orderer rule"| s1
  dns -->|"orderer rule"| s2
  dns -->|"orderer rule"| s3
  dns -->|"admin rule"| sa
  dns -->|"operations and grpcweb rules"| sOps
  s1 --> o1
  s2 --> o2
  s3 --> o3
  sa --> o1
  sOps --> o1
  ext -.-> blocked
  classDef blue fill:#e3f2fd,stroke:#1565c0,color:#000
  classDef purple fill:#f3e5f5,stroke:#6a1b9a,color:#000
  classDef yellow fill:#fff8e1,stroke:#f9a825,color:#000
  class s1,s2,s3,sa blue
  class sOps purple
  class dns yellow
```
