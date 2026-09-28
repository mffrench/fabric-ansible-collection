# Pre-Analysis

@fabric-ansible-collection/is a project helping to deploy Hyperledger Fabric on Kubernetes with Hyperledger Operator (see @https://github.com/hyperledger-labs/fabric-operator) and Hyperledger Operations Console (see @https://github.com/hyperledger-labs/fabric-operations-console).

However currently our @fabric-ansible-collection/ project handle Kubernetes NGINX Controller only which has been deprecated since March 2026. We consequently would like to migrate to Kubernetes Gateway API (see @https://gateway-api.sigs.k8s.io/docs/introduction/) or some Istio mesh (see @https://istio.io/latest/docs/) given the multi-protocol architecture of Hyperledger Fabric where it would be good to have some port routing completing SNI routing.

Before preparing a plan, provide a comprehensive summary of the appropriate choice between Kubernetes Gateway API and Istio and the major concern to address in @./fabric-ansible-collection/plan/move-ingress/PRE-ANALYSIS.md.

--

For GRPC API, you say `SNI-based routing is the only viable mechanism` why port routing would not be viable ?

--

`The Istio approach with a dedicated gRPC port (e.g. :7051) leverages port routing to separate protocol classes` : why would Kubernetes Gateway API not allows port routing ? Is there not the capability to use dedicated Gateway with Gateway Class ?

# Plan initialisation

Following pre-analysis, write a comprehensive migration plan allowing the Fabric Ansible Collection user to deploy either deprecated nginx ingress controller or deploy new Kubernetes Gateway with shared-port-per-protocol-class respecting HLF componants default port :
- HLF orderer : 7050
- HLF peer : 7051
- HLF CA : 7054
- Hyperledger Operator : ?
- Hyperledger Operations Console : ?

# Plan evaluation

## Ingress controller looks to be a pre-requisites rather than a component to install by the Fabric Ansible Collections

From the MIGRATION-PLAN.md, first step require either an ingress (either nginx either Gateway API) installation from `roles/fabric_operator_crds/tasks/k8s/create.yml`, but that task doesn't handle such ingress install before the migration. We should not change the tasks behavior along the migration. Can you re-analyse the Fabric Ansible Collection project and explicit in the PRE-ANALYSIS.md it the project provide a way to install the ingress nginx controller or if this is handled as a pre-requisite ?

---

In the PRE-ANALYSIS.md there is following statement:

`The fabric-ansible-collection currently provisions ingress-nginx (controller-v1.1.2) as the sole Kubernetes ingress solution.`

This is not entirely correct : ingress-nginx is a pre-requirement of the fabric ansible collection and the project provision the ingress-nginx for the CI github requirement.

Can you hunt and correct any statement making think the fabric ansible collection handle ingress provisionning ?

## Kubernetes Gateway API features classification

In the PRE-ANALYSIS.md, there is following statement:

`Key constraint: TLSRoute is still a beta resource in Gateway API v1.1, and only some implementations support it today.`

However according to @https://kubernetes.io/blog/2026/04/21/gateway-api-v1-5/ the TLSRoute have been promoted as standard feature (and so GA). Can you double chec PRE-ANALYSIS.md and MIGRATION-PLAN.md so that you ensure coherence with the last Gateway API version ?

## Kubernetes Gateway API implementations providers comparative study

I do realise now Istio is also providing a Kubernetes Gateway API implementation. Can you provide a comprehensive summary of pros and cons on the different Kubernetes Gateway API ? Can you provide advise so that for the CI testing environment and PoC we rely on the low cost solution but insuring it is compliant with Kubernetes Gateway API interface ?

## Optional exposition of Hyperledger Fabric network components

Most of the time, in a decentralized setup of an Hyperledger Fabric Network dispatched accross severals Kubernetes clusters, it will be required to expose HLF Orderers and HLF Peers. However, event in such case, it's not clear why componant like HLF CA or HLF Operator should expose endpoint to the Kubernetes Gateway API. Also, in the case where the network is initialized within one cluster only and where each organization could have their own namespace, it looks that only the Fabric Operations Console should be exposed.

In the PRE-ANALYSIS.md, can you evaluate rational of network exposition for each service and consequently look if such exposition can be optional or not within current Fabric Ansible Collection implementation ? Can you list services for which it is not possible to have optional network exposition and from there update the MIGRATION-PLAN.md to provide such options ?

## Network topology and integration tests

Can you ensure current integration tests are in the network topology scenario A where no service are required to expose their endpoint to the kubernetes ingress but the Hyperledger Fabric Operations Console ? Else can you update the CI / Integration Tests requirement accordingly ?

## Adapt Fabric Ansible Collection integration tests to ensure multi ingress solution

Can you ensure integration tests are handled so that both NGINX ingress and Fabric Gateway API are validated the same way ?

---

## Fix inconsistency between the current move ingress plan and the Kubernetes Gateway API

In @plan/move-ingress/MIGRATION-PLAN.md, you are using string as value for backendRefs ports. However, the @https://gateway-api.sigs.k8s.io/reference/api-spec/1.6/spec/#backendref documentation state it should be an integer. Can you review the Kubernetes Gateway API usage in the plan, list any discrepency like that and then finaly fix the plan for each discrepency I will double check ? We will last final version of Kubernetes Gateway API (1.6) documented here: @https://gateway-api.sigs.k8s.io/reference/api-spec/1.6/spec

## Add tutorials task in the plan so that any new variables should be documented through new tutorials

In @plan/move-ingress/MIGRATION-PLAN.md, some new definition are required by the end user when they want to deploy a Fabric network using Kubernetes Gateway API. For each role requiring exposing the underlying service to the ingress, plan dedicated tutorial tasks to add new tutorial demonstrating how we can use these roles coupled with Kubernetes API Gateway. Provide also for each roles the exaustive list of new required variables.

## Fix Fabric CA exposition from the ingress

The CA should remain passthrough rather than TLS-terminated. The current plan terminates TLS at the gateway for the CA, but CA enrollment validates the CA's own TLS certificate. Terminating TLS at the gateway will break enrollment unless it is configured as passthrough. Can you fix @plan/move-ingress/GATEWAY-API-IMPLEMENTATIONS.md, @plan/move-ingress/MIGRATION-PLAN.md & @plan/move-ingress/PRE-ANALYSIS.md ?

## Ansible extra-vars management

In  @plan/move-ingress/MIGRATION-PLAN.md, ANSIBLE_EXTRA_VARS is referenced as a way to setup ansible extra variables. However there is no reference in ansible documentation (@https://docs.ansible.com/projects/ansible/latest/) about that ANSIBLE_EXTRA_VARS user can export to replace the ansible command inline `--extra-vars` parameter. Base on the ansible documentation, can you correct if necessary ? If not necessary, can you tell the documentation reference showing its possible to setup ansible command extra vars with `ANSIBLE_EXTRA_VARS` ?

Use one file to setup all the extra vars (ingress_type and expose_*) and use ansible --extra-vars ability to read file like documented in @https://docs.ansible.com/projects/ansible/latest/cli/ansible.html.

## Configurable Fabric Operations Console exposition

Allthough the @plan/move-ingress/PRE-ANALYSIS.md is correct while stating the Fabric Operations Console must be reachable from the operator browser, we need to consider the case where we want to manually configure the Kubernetes ingress (nginx or Kubernetes Gateway API) to let the operator browser access the Fabric Operation Console. Check both @plan/move-ingress/PRE-ANALYSIS.md and @plan/move-ingress/MIGRATION-PLAN.md, apply necessary changes to introduce a new `expose_console` variable (default : true).

--

Can you complete the change by providing explanation about that `console_url` ? Where would that be used ?

--

Specify that `wait-for-console` task must use the Kubernetes Fabric Operation Console internal URL instead of using the one publicly exposed in case `expose_console=false`

--

For the `Print console URL`, do not require the user to pre-define the public URL through `console_url` variable but print that the current deployment didn't setup any Fabric Operation Console exposition as requested by the `expose_console` setup

## Divide and conquer !

The current @plan/move-ingress/MIGRATION-PLAN.md is a bit heavy and we need to split into different deliverables steps:

- step 1 : provide expose options with nginx ingress controller option only. In that first deliverable, we should focus on providing new tests case and tutorials to demonstrate there is no regression and how to handle the extrem opposite scenario where nothing is exposed through the NGINX ingress controller.
- step 2 : provide a first implementation of Kubernetes Gateway API with expose_console=true only (other remains false). In that second deliverable, we should focus on providing a first HTTPRoute setup orchestration while we still keep NGINX ingress controller implementation as an option. Provide integration tests and tutorials. That step should be compliant with Kubernetes Gateway API 1.3
- step 3 : provide a final implementation of Kubernetes Gateway API where all expose_* variables are set to true. In that third deliverable, we now provide Kubernetes API Gateway TLSRoute setup orchestration for the different components requiring it. NGINX ingress controller implementation is still an option and previous integrations tests and tutorials should continue work. New integrations tests and tutorials should be added to demonstrate the appropriate Kubernetes Gateway API implementation

Provide a roadmap summary in @plan/move-ingress/MIGRATION-ROADMAP.md.

For each sub-step X, provide a detailed plan in @plan/move-ingress/MIGRATION-STEP-X.md. The detailed plan should provide awaiting implementation changes but also new integration test to be implemented and new tutorials for final validation.

--

In step 3 the Gateway API version target is v1.6 but compatibility should remain with v1.3 in case we are using only HTTPRoute. Double check from Kubernetes Fabric Gateway documentation there is no breaking changes between the two versions  (provide URL sources of your analysis). Else provide a way to move smoothly from Gateway API v1.3 to Gateway API v1.6.


## Step 1 — Native ports for the no-expose scenario, CoreDNS per-component rewrites, and in-cluster test specification

The current `MIGRATION-STEP-1.md` sub-tasks 1.4–1.6 describe the `expose-none` CI leg but leave three problems unaddressed. Please update `MIGRATION-STEP-1.md` to resolve all three.

---

### Problem 1 — Port mismatch when `expose_*: false`

When `expose_*: false` the collection bypasses the ingress entirely. The `api_url` stored in the console for every component uses port `443` (set by the operator from the Ingress hostname). In-cluster Kubernetes `ClusterIP` Services forward to the pod on its **native Fabric port**. The operator's Service spec may map `443` → native port, but this is an implicit assumption that is not documented and not tested.

Independently, the convention in HLF documentation and the Gateway API migration plan (§8.6) is that gRPC API endpoints use their canonical ports:

| Component | Native gRPC port | Operations port |
|-----------|-----------------|-----------------|
| Peer      | 7051            | 9443            |
| Orderer   | 7050            | 8443            |
| CA        | 7054            | 9443            |

For the `expose-none` scenario the `api_url` in the console should reflect the **native port** so that (a) the URL is meaningful without an ingress in front of it, and (b) the same URL format is reused in Step 3 where the Gateway API TLS passthrough listeners are also bound to these native ports.

**Required changes to `MIGRATION-STEP-1.md`:**

Add a new **sub-task 1.3b — Post-creation `api_url` port patch for the `expose-none` scenario** with the following specification:

- After the `ordering_organization` and `endorsing_organization` roles complete (i.e. after the operator has provisioned components and written `api_url` values into the console registry), a conditional Ansible task block guarded by `not expose_peer | bool`, `not expose_orderer | bool`, `not expose_ca | bool` calls the console metadata API to overwrite `api_url` and `operations_url` with URLs using the native port instead of `:443`:
  - Peer: `PUT /ak/api/v3/components/fabric-peer/<id>` with `api_url: grpcs://<hostname>:7051`, `operations_url: https://<hostname>:9443`
  - Orderer: `PUT /ak/api/v3/components/fabric-orderer/<id>` with `api_url: grpcs://<hostname>:7050`, `operations_url: https://<hostname>:8443`
  - CA: `PUT /ak/api/v3/components/fabric-ca/<id>` with `api_url: https://<hostname>:7054`, `operations_url: https://<hostname>:9443`
- The **hostname part of the URL must not change** — it stays as the ingress-domain hostname (e.g. `fabricinfra-org1peer-peer.localho.st`). Only the port is rewritten. This preserves TLS SAN validity because the certificate was issued with that ingress hostname.
- The port values are sourced from the new variables already planned in sub-task 1.1: `ingress_grpc_peer_port` (7051), `ingress_grpc_orderer_port` (7050), `ingress_ca_port` (7054). Add three additional variables to `roles/fabric_operator_crds/defaults/main.yml`: `native_peer_operations_port: 9443`, `native_orderer_operations_port: 8443`, `native_ca_operations_port: 9443`.
- The metadata PUT uses the Ansible `uri` module. Include a concrete YAML snippet in the sub-task showing the exact `uri` task body, headers, and `when` guard.
- This sub-task applies to both `fabric_console` and `hlfsupport_console` role paths. Specify where in each task file the new block is inserted.

---

### Problem 2 — CoreDNS must route ingress hostnames to in-cluster Services, not to nginx

When `expose_*: false` no Ingress objects are created for CA, peer, or orderer. The current CoreDNS wildcard rewrite (`rewrite name regex (.*)\.localho\.st host.ingress.internal`) still resolves every `*.localho.st` name to the nginx ClusterIP. That silently routes traffic through nginx even when the intent is to bypass it, and will break as soon as no ingress controller is installed.

The correct mechanism is a **per-component CoreDNS `rewrite name exact` rule** that maps each ingress FQDN directly to its Kubernetes `ClusterIP` Service FQDN, which the `kubernetes` CoreDNS plugin resolves natively:

```
rewrite name exact <namespace>-<slug>-peer.<domain>       <peer-svc>.<namespace>.svc.cluster.local
rewrite name exact <namespace>-<slug>-orderer.<domain>    <orderer-svc>.<namespace>.svc.cluster.local
rewrite name exact <namespace>-<slug>-ca.<domain>         <ca-svc>.<namespace>.svc.cluster.local
rewrite name exact <namespace>-<slug>-operations.<domain> <component-svc>.<namespace>.svc.cluster.local
```

This approach preserves the original ingress FQDN as the dialled hostname → TLS certificate SANs remain valid → no `csr_hosts` changes or re-enrollment needed. It is also additive: the existing wildcard rewrite for the console continues to work alongside the per-component rules.

**Required changes to `MIGRATION-STEP-1.md`:**

Add a new **sub-task 1.4b — CoreDNS per-component rewrites for the `expose-none` CI leg** with the following specification:

- The rewrite rules are generated and applied by the CI bootstrap script (`.github/scripts/kind_with_nginx.sh`), **not by any Ansible role task**, consistent with the design constraint in MIGRATION-PLAN.md §1.1.
- The rules are applied **after** the Ansible playbook has run (so component names and namespace are known), via a `kubectl apply -f -` of a new CoreDNS `ConfigMap`.
- The `ConfigMap` for the `expose-none` leg keeps the wildcard rewrite for the console (or replaces it with a specific rule if `expose_console: false`) and adds one `rewrite name exact` rule per deployed component per organisation.
- The Kubernetes Service name created by the operator for each component follows the pattern `<component-slug>` within the namespace (e.g. service `org1peer` in namespace `fabricinfra` for a peer named `Org1 Peer`). Document this pattern explicitly so the script author knows the substitution.
- A new helper function `apply_coredns_component_rewrites()` is added to `kind_with_nginx.sh` that: (1) accepts the namespace and a list of `<ingress-fqdn>:<k8s-service-name>` pairs as arguments, (2) generates the CoreDNS `ConfigMap` YAML with one `rewrite name exact` block per pair, (3) applies it with `kubectl apply -f -`, (4) restarts CoreDNS with `kubectl -n kube-system rollout restart deployment/coredns`. Provide the complete bash function body in the sub-task.
- Document that this function is the direct prototype for the equivalent function in `kind_with_envoy_gateway.sh` in Step 2.

---

### Problem 3 — In-cluster test execution specification

The current sub-tasks 1.5 and 1.6 assume the GitHub Actions runner can reach peer, orderer, and CA endpoints directly. In the `expose-none` scenario with native ports (Problem 1) and per-component CoreDNS rewrites (Problem 2), the runner — which is **outside** the KIND cluster — cannot resolve ingress FQDNs to in-cluster Service IPs and cannot dial native ports through the KIND host-port mappings (which only expose ports `80` and `443`). The `expose-none` leg must therefore run Ansible playbooks **from inside the cluster**.

**Required changes to `MIGRATION-STEP-1.md`:**

Replace sub-tasks 1.5 and 1.6 with the following more precise specifications:

#### Sub-task 1.5 — CI workflow: `expose-none` matrix leg with in-cluster Ansible runner

The `expose-none` matrix leg runs the tutorial playbooks inside the KIND cluster using a **Kubernetes Job**. Specify:

- A Job manifest (inline YAML in the CI script or a file committed to `.github/`) with:
  - A container image that includes Python 3, Ansible, `hyperledger.fabric_ansible_collection`, the Hyperledger Fabric `peer` binary, and `configtxlator`. This is the same set of dependencies installed on the GitHub Actions runner for the `expose-all` leg; specify the Dockerfile or base image to use.
  - `restartPolicy: Never` so failures surface as a failed Job rather than being retried.
  - The tutorial directory (`tutorial/`) and enrolled identity JSON files mounted via a `ConfigMap` created by a preceding CI step (`kubectl create configmap tutorial-files --from-file=tutorial/`).
  - The `api_endpoint` variable overridden to the console's in-cluster Service URL: `http://<console-svc>.<namespace>.svc.cluster.local:3000`.
  - Environment variables injected for `ingress_type`, `expose_*` flags, and `wait_timeout`.
  - The Job command runs in sequence: `tutorial/build_network.sh build`, `tutorial/join_network.sh join`, `tutorial/deploy_smart_contract.sh`, with `set -e` so any failure exits non-zero.
- The CI workflow step:
  1. Creates the `ConfigMap` from the tutorial files.
  2. Applies the Job manifest with `kubectl apply -f`.
  3. Waits with `kubectl wait --for=condition=complete --timeout=20m job/<name>`.
  4. Retrieves logs unconditionally with `kubectl logs job/<name>` (captured as a CI step output or uploaded as an artefact).
  5. Fails the CI step if the Job did not complete successfully.
- The `expose-all` leg continues to run Ansible directly on the runner (current behaviour) and is unaffected. Use `fail-fast: false` on the matrix.
- Provide the exact diff to `fvtest.yml` showing the new `scenario` matrix dimension, the `if:` conditions per step, and the Job-submission steps.

#### Sub-task 1.6 — In-cluster service reachability assertions

Define explicit, automatable assertions for the `expose-none` leg verifying in-cluster reachability without relying on the external runner's network access. All assertions run as ephemeral pods via `kubectl run --rm -i --restart=Never` and are executed as a CI step **after** the in-cluster Ansible Job from sub-task 1.5 completes:

1. **No external Ingress objects exist** for CA, peer, or orderer (runner-side, using `kubectl`):
   ```bash
   count=$(kubectl get ingress -n <namespace> -o name | grep -cvE 'console' || true)
   [ "$count" -eq 0 ] || (echo "Unexpected Ingress objects found" && exit 1)
   ```

2. **Console ClusterIP Service responds** at its in-cluster URL:
   ```bash
   kubectl run curl-console --image=curlimages/curl:latest --restart=Never --rm -i \
     --namespace <namespace> \
     -- curl -sf http://<console-svc>.<namespace>.svc.cluster.local:3000/ak/api/v3/health
   ```

3. **Peer gRPC endpoint is reachable** at native port 7051 via ClusterIP (TLS handshake succeeds, connection is not refused):
   ```bash
   kubectl run grpc-peer --image=curlimages/curl:latest --restart=Never --rm -i \
     --namespace <namespace> \
     -- curl -sk --connect-timeout 5 \
     https://<namespace>-org1peer-peer.<ingress_domain>:7051
   # Pass condition: exit code 0 or 35 (TLS error expected — not connection refused / exit 7)
   ```

4. **Orderer gRPC endpoint is reachable** at native port 7050: same pattern as above with the orderer hostname.

5. **CA HTTPS enrollment endpoint is reachable** at port 7054:
   ```bash
   kubectl run ca-check --image=curlimages/curl:latest --restart=Never --rm -i \
     --namespace <namespace> \
     -- curl -sf -k https://<namespace>-orderingca-ca.<ingress_domain>:7054/cainfo
   # Pass condition: JSON response body containing "caName"
   ```

6. **DNS resolution of ingress FQDNs resolves to Service ClusterIP, not to nginx ClusterIP** (confirms the CoreDNS per-component rewrites from sub-task 1.4b are active):
   ```bash
   nginx_ip=$(kubectl -n ingress-nginx get svc ingress-nginx-controller -o jsonpath='{.spec.clusterIP}')
   resolved_ip=$(kubectl run dns-check --image=busybox:latest --restart=Never --rm -i \
     -- nslookup <namespace>-org1peer-peer.<ingress_domain> \
     | grep 'Address:' | tail -1 | awk '{print $2}')
   [ "$resolved_ip" != "$nginx_ip" ] || (echo "Peer FQDN still resolves to nginx" && exit 1)
   ```

Each assertion must appear in `MIGRATION-STEP-1.md` as a named todo item with the exact command, the expected output or exit-code criterion, and a sentence explaining what a failure indicates (misconfigured CoreDNS rewrite, Service not created, port mapping wrong, etc.).

## Reuse internal K8S url as ingress_domain

In the case the end user provide `ingress-domain=*.svc.cluster.local` or `ingress-domain=svc.cluster.local` or `ingress-domain=<kubernetes local domain name space>` and all `expose_*=false`, then CoreDNS rewrite should not been needed. Complete step 1 so that in such case we don't redirect at all ingress-domain URL to any ingress.

In the case the end user provide `ingress-domain=*.svc.cluster.local` or `ingress-domain=svc.cluster.local` or `ingress-domain=<kubernetes local domain name space>` and at least on `expose_*=true`, then raise an error telling it's not possible to define `ingress-domain=<kubernetes local domain name space>` if some service are intended to be exposed.

## Wildcard HTTPs certificate provisioning

The wildcard serving certificate is not currently provisioned. The HTTPS listener requires a valid *.<domain> certificate (e.g., via cert-manager). While the plan references a secret, it does not include its creation.
