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

## Provide Step 0 Plan

Document how to run CI tests in local Apple OSX environment where kind is already installed as well as ansible.

---

Improve @plan/move-ingress/MIGRATION-PREREQ-LDE.md to include [venv](https://docs.python.org/3/library/venv.html) usage and use python version 3.10 exactly.

---

When executing the test with Option A, I get following error:

```
TASK [hyperledger.fabric_ansible_collection.ordering_organization : Create certificate authority] **************************************************************************************************************************************************************************************************
fatal: [localhost]: FAILED! => {"changed": false, "msg": "Failed to access the console: Failed to get console health: HTTP status code 404: b'<html>\\r\\n<head><title>404 Not Found</title></head>\\r\\n<body>\\r\\n<center><h1>404 Not Found</h1></center>\\r\\n<hr><center>nginx</center>\\r\\n</body>\\r\\n</html>\\r\\n'"}
```

Troubleshoot & fix

---

Create a new plan @plan/move-ingress/MIGRATION-STEP-0.md which will cover the way to fix existing CI tests.

---

Review @plan/move-ingress/MIGRATION-STEP-1.md so that any task reported in @plan/move-ingress/MIGRATION-STEP-0.md are not duplicated.

---

Review @plan/move-ingress/MIGRATION-ROADMAP.md so that it reflect all the step starting from step 0.

---

## Step 1 : revert to service port exposition

The Hyperledger Operator publish CRs and many other ConfigMap where the 443 port usage is encoded everywhere. Consequently updating the Fabric Operations Console to use native port just after the component deployments will not be enough.

Instead of updating the Fabric Operation Console within step1, work on a solution where we (re)define services listening both to port 443 and native ports.

Rework the step1 (@plan/move-ingress/MIGRATION-STEP-1.md)

---

Explain a bit more how `ingress_grpc_peer_port`, `ingress_grpc_orderer_port` and `ingress_ca_port` are used to setup appropriately underlying service

---

In step1, there is no Kubernetes Gateway API to consider. these new parameters (`ingress_grpc_peer_port` ...) seems new and not sure these could be appropriately managed by the Fabric Operator which is creating the service. Can you review Fabric Operator source code (@https://github.com/hyperledger-labs/fabric-operator) and double check how the services are spawned ?

---

From what you explain, this is not possible for the Operation Console to instruct the Hyperledger Operator to create service with additional port without changing the Hyperledger Operator. Can you look on a way to update the existing service created by the operator to add that new 443 port to listen to ?

---

Rework the step1 (@plan/move-ingress/MIGRATION-STEP-1.md)

---

in @plan/move-ingress/MIGRATION-ROADMAP.md, tell that, starting Step 3, the K8S Gateway API requirement minimal version will be 1.6.

## Execute Step 0 Plan

Execute plan @plan/move-ingress/MIGRATION-STEP-0.md.

---

When running `./.github/scripts/run-tests.sh`, I get following error:

```
TASK [hyperledger.fabric_ansible_collection.endorsing_organization : Delete certificate authority] *************************************************************************************************************************************************************************************************
fatal: [localhost]: FAILED! => {"changed": false, "msg": "Failed to access the console: Failed to get console health: HTTP status code 404: b'<html>\\r\\n<head><title>404 Not Found</title></head>\\r\\n<body>\\r\\n<center><h1>404 Not Found</h1></center>\\r\\n<hr><center>nginx</center>\\r\\n</body>\\r\\n</html>\\r\\n'"}
```

Troubleshoot and fix

---

Running `export KUBECONFIG="$PWD/_cfg/k8s_context.yaml" ; .github/scripts/deploy-console.sh`, I get following error:

```
TASK [hyperledger.fabric_ansible_collection.fabric_operator_crds : Fail if architecture not specified] *********************************************************************************************************************************************************************************************
fatal: [localhost]: FAILED! => {"changed": false, "msg": "arch not specified or is not one of \"amd64\""}
```

Troubleshoot and fix

---

Running `export KUBECONFIG="$PWD/_cfg/k8s_context.yaml" ; .github/scripts/deploy-console.sh`, the script is hanging on step :

```
TASK [hyperledger.fabric_ansible_collection.fabric_console : Wait for console deployment to exist] *************************************************************************************************************************************************************************************************
FAILED - RETRYING: [localhost]: Wait for console deployment to exist (600 retries left).
ok: [localhost]

TASK [hyperledger.fabric_ansible_collection.fabric_console : Wait for console deployment to start] *************************************************************************************************************************************************************************************************
```

Troubleshoot and fix

---

You need to distinguish architecture in case we deploy pod from an image (should always be amd64) and arch where you define affinity (should match the host arch)

---

Getting following error now :

```
TASK [hyperledger.fabric_ansible_collection.fabric_operator_crds : Fail if architecture not specified] *********************************************************************************************************************************************************************************************
fatal: [localhost]: FAILED! => {"changed": false, "msg": "arch not specified or is not one of \"amd64\""}
```

Troubleshoot and fix

---

Looking state of HLF Console, I see this:

```
╰─$ kubectl get pods -A
NAMESPACE            NAME                                         READY   STATUS             RESTARTS     AGE
default              fabric-operator-ddd5b95c7-nvf9d              1/1     Running            0            18m
default              hlf-console-65cd787598-6b59c                 2/4     CrashLoopBackOff   3 (4s ago)   83s
```

Troubleshoot and fix

---

Running `.github/scripts/run-tests.sh`

I get again that error :

```
TASK [hyperledger.fabric_ansible_collection.endorsing_organization : Delete certificate authority] *************************************************************************************************************************************************************************************************
fatal: [localhost]: FAILED! => {"changed": false, "msg": "Failed to access the console: Failed to get console health: URLError: <urlopen error [Errno 51] Network is unreachable>"}
```

Troubleshoot and fix

---

Now we are getting that error :

```
TASK [hyperledger.fabric_ansible_collection.endorsing_organization : Delete certificate authority] *************************************************************************************************************************************************************************************************
fatal: [localhost]: FAILED! => {"changed": false, "msg": "Failed to access the console: Failed to get console health: HTTP status code 401: b'Unauthorized'"}
```

---

Got that error while running `.github/scripts/run-tests.sh`:

```
TASK [hyperledger.fabric_ansible_collection.ordering_organization : Create ordering service] *******************************************************************************************************************************************************************************************************
fatal: [localhost]: FAILED! => {"changed": false, "msg": "Failed to create ordering service: HTTP status code 500: {'statusCode': 500, 'msg': [{'name': 'orderingservice6ca44ccdnode1', 'crypto': {'enrollment': {'component': {'cahost': 'default-orderingorg6ca44ccdca-ca.127-0-0-1.nip.io', 'caport': '443', 'caname': 'ca', 'catls': {'cacert': ...
..., 'replicas': 1}]}"}
```

Troubleshoot and fix

---

Auth is working. Here's the summary:

Root Cause
The Fabric Operations Console uses the admin email address as the username for Basic auth — set via console_email at deploy time (admin@example.com). The api_key in the vars files and _cfg/console-env.sh was set to "admin", which is not a valid username in the console's access list, causing every authenticated API call to return HTTP 401 Unauthorized.

Changes
.github/scripts/deploy-console.sh

API_KEY in the generated _cfg/console-env.sh now uses ${CONSOLE_EMAIL} (i.e. admin@example.com) instead of the hardcoded string "admin".

.github/workflows/fvtest.yml

API_KEY exported to $GITHUB_ENV changed from admin → admin@example.com to match.

_cfg/console-env.sh updated in-place for the current running cluster.


Got that error while running `.github/scripts/run-tests.sh`:



```

TASK [hyperledger.fabric_ansible_collection.ordering_organization : Create ordering service] *******************************************************************************************************************************************************************************************************

fatal: [localhost]: FAILED! => {"changed": false, "msg": "Failed to create ordering service: HTTP status code 500: {'statusCode': 500, 'msg': [{'name': 'orderingservice6ca44ccdnode1', 'crypto': {'enrollment': {'component': {'cahost': 'default-orderingorg6ca44ccdca-ca.127-0-0-1.nip.io', 'caport': '443', 'caname': 'ca', 'catls': {'cacert': ...
..., 'replicas': 1}]}"}

```

Troubleshoot and fix

---

When executing :

```
+ ansible-playbook 02-create-endorsing-organization-components.yml

[WARNING]: No inventory was parsed, only implicit localhost is available

[WARNING]: provided hosts list is empty, only localhost is available. Note that the implicit localhost does not match 'all'
....
TASK [hyperledger.fabric_ansible_collection.endorsing_organization : Create peer] ******************************************************************************************************************************************************************************************************************
```

I see :

```
kubectl get pods -A

NAMESPACE            NAME                                            READY   STATUS             RESTARTS     AGE

default              fabric-operator-ddd5b95c7-6kt2t                 1/1     Running            0            13m

default              hlf-console-697cfcd77-rc5wf                     4/4     Running            0            13m

default              orderingorg0f5fd51cca-7464c7584b-7q9dn          1/1     Running            0            4m16s

default              orderingservice0f5fd51cnode1-86bbbbb949-76gmt   2/2     Running            0            3m21s

default              org1ca0f5fd51c-56bbcd46d8-9mxv2                 1/1     Running            0            2m31s

default              org1peer0f5fd51c-b94685fdd-bq8kz                2/3     CrashLoopBackOff   3 (5s ago)   78s
```

Troubleshoot and fix

---

For the Fabric Operation Console, you changed the required memory for its couchdb container in @role/fabric_console/templates/k8s/hlf-operations-console.yaml.j2. Can you look a way to report these changes in the tutorial ?

---

Can you look a way to remove CouchDB from the HLF Peer Pod and use GoLevelDB as the world state ?


## Wildcard HTTPs certificate provisioning

The wildcard serving certificate is not currently provisioned. The HTTPS listener requires a valid *.<domain> certificate (e.g., via cert-manager). While the plan references a secret, it does not include its creation.

## Fix step1 1.3b

As reviewed in @plan/move-ingress/REVIEW-MIGRATION-PLAN-STEP-1.md, a service port 443 cannot serve several FQDNs.

A few adjustments are needed for it to work end to end. In particular, every endpoint needs its own 443 Service. Each node advertises several endpoints on 443: API, operations, grpcweb, and admin on orderers. With your CoreDNS rewrites, -operations and the other hostnames still resolve to the same Service. There, 443 would reach the API port rather than operations (9443 on peers and CAs, 8443 on orderers), grpcweb (7443) or orderer admin (9443). That would break the console's status checks and grpcweb proxy, the collection's health waits, and joining orderers to channels. A Service port can map 443 to only one target, so this approach requires creating one Service per endpoint type, each with a matching CoreDNS rewrite. That also avoids modifying operator-managed objects.

Fix @plan/move-ingress/MIGRATION-STEP-1.md plan to create one service per endpoint type.

## Fix cluster domain discovery

As reviewed in @plan/move-ingress/REVIEW-MIGRATION-PLAN-STEP-1.md in Implementation mistakes (fixable without changing the design), we have a cluster domain URL discovery issue :

- **`cluster_domain` discovery:** `kubectl exec deployment/coredns -- awk`
  always fails (the CoreDNS image is distroless, without `awk` or a shell;
  CoreDNS pods use `dnsPolicy: Default`, so their `resolv.conf` has no cluster
  `search` line). It also requires `kubectl` and the `pods/exec` permission.
  → Read the Corefile from the `kube-system/coredns` ConfigMap via `k8s_info`,
  or keep `cluster.local` as the default with a documented override; use `""` as
  the sentinel value.

Fix in the plan @plan/move-ingress/MIGRATION-STEP-1.md to solve that problem

---

If lookup fails: it fallback to the user to define the cluster domain.

---

```
A non-empty user value always wins and is not cross-checked
against the Corefile: the override exists precisely for clusters where the
Corefile lookup is wrong or unavailable.
````

It needs to be double checks as best effort.
If it's possible to get the cluster domain and there is a gap an error should be raised.
If it's not possible to get the cluster domain then a warning is displayed telling we trust user cluster domain.

## Fix remaining `Variables and facts issues`

As reviewed in @plan/move-ingress/REVIEW-MIGRATION-PLAN-STEP-1.md in Implementation mistakes (fixable without changing the design), we need to improve the variable scopes and definitions.

```
**Variable scope:** the defaults of `fabric_operator_crds` are not visible
  from `fabric_console`, `endorsing_organization` or `ordering_organization`
  (separate playbooks). `include_tasks: set_facts.yml` called from
  `hlfsupport_console` looks for the file in its own role.
  `ingress_domain_is_cluster_local` is used in the organization roles without
  ever being defined there.
  → Defaults in each role, or a small shared role called via `include_role`.
```

We also need to harden domain definitions and double check the way it is used between Fabric Ansible Collection and Fabric Operator.

First explain how the componant URLs are built from the Fabric Ansible Collection to the Fabric Operator. Write a comprehensive summary in @plan/move-ingress/URL-MANAGEMENT.md

---

At the current stage the ingress_domain is equal to the console_domain and that definition is propagated to the underlying HLF component FQDN. However in that first step we need to decouple a bit these things.

- The ingress_domain should be renamed exposed_domain to have a naming compliant with our future move
- we should have an additional hlf_network_domain var to reflect what will be propagated to the underlying HLF component FQDN.
- `ingress_domain_is_cluster_local` should be renamed `hlf_network_domain_is_cluster_local` and should be true if hlf_network_domain=cluster_domain. In such case, no CoreDNS rewrite rules are needed else CoreDNS rewrite rules should be defined to target appropriate kuberneted services.
- the console URL and so its TLS SANs should be built based on the exposed_domain definition even though we do not request to expose the console (expose_console=false).

Rename @plan/move-ingress/URL-MANAGEMENT.md to @plan/move-ingress/EXISTING-URL-MANAGEMENT.md

Provide a proposal to improve current domain & URL management so that :
- there is clear decoupling in the definitions
- there is minimal change in Fabric Ansible Collection and no changes in Fabric Operator
- solution handle the step 1 case target where:
  - we do not expose anything in first deployment
  - HLF domain is cluster internal
  - we can subsequently manually configure an ingress or a K8S Gateway API route to the console with appropriate console URL & TLS working
- solution doesnt introduce regression with the current default architecture (all exposed through ingress)

Write a comprehensive and illustrated proposition in @plan/move-ingress/NEW-URL-MANAGEMENT.md.

---

About following decision:

```
> **Decision D1: definition of "cluster local".** The request was
> `hlf_network_domain_is_cluster_local = (hlf_network_domain == cluster_domain)`.
> That does not give "no CoreDNS rewrite needed". With
> `hlf_network_domain: cluster.local`, the operator builds
> `default-org1peer-peer.cluster.local`, but Kubernetes only serves
> `<service>.<namespace>.svc.cluster.local`. That name would still need a
> rewrite. The only value whose FQDNs are **already** Kubernetes Service
> names is `<namespace>.svc.<cluster_domain>`:
>
> ```
> default-org1peer-peer . default.svc.cluster.local
> └──── Service name ───┘ └ namespace ┘
> ```
>
> This proposal therefore defines the fact against
> `<namespace>.svc.<cluster_domain>`. Any other value inside
> `cluster_domain` (`cluster.local`, `svc.cluster.local`,
> `other-ns.svc.cluster.local`) is rejected at role entry (sub-task 1.1b).
> **To confirm.**
````

True that previous definition is not well defined. `hlf_network_domain` should be defined so that we have operator building component URLs like <service>.<namespace>.svc.<hlf_network_domain>. If (hlf_network_domain == cluster_domain) then hlf_network_domain_is_cluster_local=true and in that case no CoreDNS rewrite rules should be needed.

Rename @plan/move-ingress/EXISTING-URL-MANAGEMENT.md to @plan/move-ingress/URL-MANAGEMENT-EXISTING.md
Rename @plan/move-ingress/NEW-URL-MANAGEMENT.md to @plan/move-ingress/URL-MANAGEMENT-NEW.md
Update @plan/move-ingress/URL-MANAGEMENT-NEW.md according last decision.

--

`hlf_network_domain` should be defined so that we have operator building component URLs like <service>.<namespace>.svc.<hlf_network_domain> if (hlf_network_domain == cluster_domain) else we keep previous way of building URLs.

---

Regarding `| D4 | Node Ingress neutralization (§5.4) | proposed: opt-in, after check 3 |`, can you provide a better explanation of the proposition with example ?

---

Apply D2 to D5 propositions in @plan/move-ingress/URL-MANAGEMENT-NEW.md.

Then summarize what remains to be handled to cover STEP 1 Review `Implementation mistakes (fixable without changing the design)`/`Variables and facts`

---

Perform checks before coding (§9 in @plan/move-ingress/URL-MANAGEMENT-NEW.md)

---

Record §9 checks results in @plan/move-ingress/URL-MANAGEMENT-NEW.md. Move content of /tmp/fac-checks into @plan/move-ingress/.url_management_new_checks/.
clean up the test resources.

---

Summarize what remains to be handled to cover STEP 1 Review `Implementation mistakes (fixable without changing the design)`/`Variables and facts`

---

All three "Variables and facts" findings now have a design, and the domain mechanics behind it were confirmed on the local Kind cluster (checks 1, 2, 3, 4, 6 and 7 passed). The main remaining work is
rewriting MIGRATION-STEP-1.md, which still describes the old design.

Review finding: cluster_domain discovery (kubectl exec … awk always fails)
Status now: Fixed in the plan. Sub-task 1.1 reads the kube-system/coredns ConfigMap, checks a value you set against it, and warns or fails when it can't read it. The parsing was tested on sample
Corefiles only.
What remains: Move this logic into the shared network_domains role. Decide the -e question: a value passed with -e can't be overwritten by set_fact. Run it once against the live Kind cluster's
ConfigMap.
────────────────────────────────────────
Review finding: Variable scope (defaults invisible across playbooks; include_tasks from hlfsupport_console looks in its own role; ingress_domain_is_cluster_local undefined in the organization roles)
Status now: Designed in URL-MANAGEMENT-NEW.md §6: one network_domains role, values shared through common-vars.yml, and the V5 check on returned URLs (check 6 confirmed the rule).
What remains: MIGRATION-STEP-1.md sub-tasks 1.1, 1.1b and 1.3b still use set_facts.yml in fabric_operator_crds, include_tasks, and the old ingress_domain* names. The fabric_console role and
tutorial/00-deploy-fabric-console.yml (what CI runs) must call the new role. Per finding F1, the console role must set spec.deployer.domain when the console is created, and restart the console or
refuse if it changes later.
────────────────────────────────────────
Review finding: Cluster-local domain is not a Service FQDN
Status now: Resolved by D1 and confirmed by check 1. With hlf_network_domain == cluster_domain, the CA's URLs were real Service names: resolved with no CoreDNS change, strict TLS passed.
What remains: Rewrite 1.1b with validation rules V2 and V3, apply the CoreDNS decision tree in 1.4b, and update acceptance criterion 7. Check 5 (scenario B end to end) is blocked until the in-cluster
runner of sub-task 1.5 exists.

Three related items fall outside these findings but affect the same tasks:
- F3: a CA created as Check1 CA was stored as Check1, so a later call with the original name didn't find it. The modules find components by display name, so this needs explaining before sub-task 1.3b.
- Assumption S1 (from the review's organization-roles section): node resource names should come from the URLs the console returns, not be re-derived from the display name.
- F2: the console certificate doesn't cover its in-cluster name. Note it in the docs, or add that name to the certificate via console_tls_secret.

The next step is to apply URL-MANAGEMENT-NEW.md §7.3 to MIGRATION-STEP-1.md, which covers most of the remaining items. Execute that next step.

---

Summarize what remains to be handled to cover STEP 1 Review `Implementation mistakes (fixable without changing the design)`/`Variables and facts`

>>>
Review finding: cluster_domain discovery (kubectl exec … awk always fails)
Plan: Sub-task 1.1: read the kube-system/coredns ConfigMap, check a value you set against it, warn or fail when it can't be read
Verified: Prototype role passed 13/13 cases against the live Kind ConfigMap; the -e question is solved (computed values have their own names)
Remaining: Test the unreadable-ConfigMap case live, with a ServiceAccount lacking get configmaps (in the 1.1b todo list). It was only tested earlier on sample data.
────────────────────────────────────────
Review finding: Variable scope (defaults invisible across playbooks, include_tasks looking in the wrong role, undefined ingress_domain_is_cluster_local)
Plan: Sub-task 1.1: shared network_domains role, included with public: true by both console roles, both organization roles and tutorial/00-deploy-fabric-console.yml. Values come from common-vars.yml;
V5 checks the returned URLs.
Verified: The role was only tested standalone, not yet included from the real roles
Remaining: Implementation: create roles/network_domains/, add the includes, remove the unused ingress_domain default, move the tests into the collection. Then run run-tests.sh on the default setup to
confirm no regression.
────────────────────────────────────────
Review finding: Cluster-local domain is not a Service FQDN
Plan: Decision D1, applied in 1.1, 1.3a, 1.3b and 1.4b
Verified: Confirmed on a CA: Service FQDNs, no CoreDNS change, strict TLS passed
Remaining: Check 5: run scenario B end to end (CA, peers, orderers, channel join). It needs the in-cluster runner of sub-task 1.5; peers and orderers are confirmed only in the source code so far.

Three adjacent items affect the same tasks:
- F3: a CA created as Check1 CA was stored as Check1. Reproduce it with a clean create, because the modules find components by display name.
- S1: the plan now checks node names against the returned URLs. Adding an optional id parameter to the modules would make names deterministic, but only if the check fails in practice.
- Check 3 on a peer: needed before node Ingress neutralization can become the default.

The natural next step is implementing sub-task 1.1 for real, since everything else builds on it. Should I start?
<<<

## Check remaining review `Organization roles` and update STEP 3 review

Given the last changes, summarize what remains to be handled to cover STEP 1 Review `Implementation mistakes (fixable without changing the design)`/`Organization roles`

<<<
Two of the four "Organization roles" findings are handled in MIGRATION-STEP-1.md but not implemented. The other two are Step 3 items that Step 1 never touched. One correction first: finding F3 was my test error, not a console bug.

F3 was my command-line quoting. -e ca_display_name="Check1 CA" reaches Ansible as ca_display_name=Check1 CA. Ansible's key=value parser then keeps only Check1. I reproduced it just now: that form gives [Check1], while -e '{"ca_display_name":"Check1 CA"}' gives [Check1 CA]. So the console stored exactly the name it received. Display-name lookup is not at risk, and F3 should be closed in URL-MANAGEMENT-NEW.md §9.1 and in the 1.3b todo list.

Review finding: Kubernetes tasks add a kubeconfig and kubernetes dependency to roles that only talk to the console REST API
Status: Handled in the plan. The Kubernetes tasks run only when a component is unexposed. network_domains reads the cluster only when the cluster domain matters, so the default path needs no
kubeconfig. The review asked for an explicit guard; the expose_* flags act as that guard.
What remains: Implementation: run the default setup without a kubeconfig to prove it. Document the requirement (kubeconfig, kubernetes library, permission to create Services) for unexposed mode.
────────────────────────────────────────
Review finding: CR names: ca_name | lower | replace(' ', '-') gives org1-ca, but the operator name is org1ca; an ordering service has N nodes, not one Service
Status: Handled in the plan. 1.3b strips all non-[a-z0-9] characters, matching the CA check (Check1 CA → check1). Ordering nodes are named <name>node<i>, confirmed in the operator source. Names are
checked against the returned URLs.
What remains: Edge cases: a name already taken gets a suffix (org1peer0), and a leading digit gets an ibp prefix. The check catches both but can't fix them. Multiple peers: the role names them {{
peer_name }}{{ item }} (Org1 Peer1 → org1peer1); verify this on a cluster. Registers: the CA, peer and ordering-service module calls aren't registered today (only the org admin is), so the 1.3b and
V5 blocks need these added.
────────────────────────────────────────
Review finding: peer_api_url, ca_api_url, orderer_api_url are never defined
Status: Not handled. These are used by MIGRATION-STEP-3.md and MIGRATION-PLAN.md §5.6 (route hostnames), not by Step 1.
What remains: Step 3: derive them from the new registered module results (endorsing_organization_ca.certificate_authority.api_url, the peer results, and every entry of the ordering_service list). Step
1's registers lay the groundwork.
────────────────────────────────────────
Review finding: The certificate_authority role doesn't exist; the CA is created inside the organization roles
Status: Not handled. Step 3 still points at roles/certificate_authority/….
What remains: Step 3: move the CA route tasks into both organization roles.

So for Step 1, these findings need no more design work. The remaining work is the implementation (registers, the 1.3b blocks, and a no-kubeconfig run of the default path), one live check of multi-peer names, and closing F3. Should I record the F3 correction and fold the two Step 3 items into MIGRATION-STEP-3.md?
>>>

---

We're focusing on step 1 fixing. Move the last finding which requires changes on step3 within @plan/REVIEW-MIGRATION-PLAN-STEP-3.md.


## Check remaining review `Console`

Given the last changes, summarize what remains to be handled to cover STEP 1 Review `Implementation mistakes (fixable without changing the design)`/`Console`

<<<
All three "Console" findings are addressed in MIGRATION-STEP-1.md sub-task 1.3. What remains is implementation, plus three small loose ends.

┌─────────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────┬──────────────────────────────────────────┐
│                       Review finding                        │                                         Status                                          │               What remains               │
├─────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────┤
│                                                             │ Handled in the plan. With expose_console: false, readiness uses the console             │ Implementation only.                     │
│ uri http://<console>.<ns>.svc.cluster.local:3000 runs on    │ Deployment's Available condition through k8s_info. Nothing polls an in-cluster URL from │ console_incluster_url is used solely     │
│ the control node, which can't resolve in-cluster names      │  the control node.                                                                      │ from inside the cluster (CI Job, 1.6     │
│                                                             │                                                                                         │ assertion 2).                            │
├─────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────┤
│ Hardcoded cluster.local, http :3000 to check, inconsistent  │ Mostly handled. HTTPS on port 3000 is confirmed by check 4, and every in-cluster        │ Three loose ends, below.                 │
│ health path                                                 │ console URL in the plan is now https://. The cluster domain comes from network_domains. │                                          │
├─────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────┤
│                                                             │ Handled in the plan. Sub-task 1.3 now describes each role as it really is:              │ Implementation only. Ideally CI would    │
│ fabric_console has nothing to "split"; CI doesn't use the   │ hlfsupport_console has an Ingress wait to guard, fabric_console only waits for its      │ use the fabric_console role, but that's  │
│ role                                                        │ Deployment. The same changes apply to tutorial/00-deploy-fabric-console.yml, which is   │ outside this finding.                    │
│                                                             │ what CI runs.                                                                           │                                          │
└─────────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────┴──────────────────────────────────────────┘

The three loose ends:
1. The health path is still inconsistent, and the paths aren't equivalent. I just tested both on the live console:
   - /health returns 200 without credentials, but it's the UI's HTML page, so it proves nothing about the API.
   - /ak/api/v3/health returns 401 without credentials and 200 with them, with a real OPTOOLS/OS health payload.

   Step 1 uses /ak/api/v3/health, but MIGRATION-STEP-0.md:123 and MIGRATION-PREREQ-LDE.md:195-198 still say /health. Those two files should be aligned, with credentials.
2. One hardcoded cluster.local remains. In the prototype network_domains role (tasks/main.yml:124), console_incluster_url falls back to cluster.local when the cluster domain wasn't resolved, which happens in the default all-exposed case. It should stay empty instead, since nothing uses it then. The same fallback appears in the 1.6 assertion 2 command (${CLUSTER_DOMAIN:-cluster.local}), where it's harmless because CI sets CLUSTER_DOMAIN.
3. The console certificate doesn't cover its in-cluster name (finding F2). This is documented in 1.3a: the collection never verifies certificates, so it isn't affected. Nothing more to do in Step 1 unless strict in-cluster clients are wanted.

None of these needs a design change. Should I align the health path in Step 0 and the setup guide, and remove the cluster.local fallback from the prototype?
>>>

## Check & fix remaining review `Expose-none CI`

Given the last changes, summarize what remains to be handled to cover STEP 1 Review `Implementation mistakes (fixable without changing the design)`/`Expose-none CI`

<<<
Of the five "Expose-none CI" findings, three are fully resolved in MIGRATION-STEP-1.md. Two (the Job's ConfigMap mount and its RBAC) are covered but still need choices before the Job manifest can be written. No CI change is implemented yet.

┌───────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────┐
│                Review finding                 │                                         Status                                         │                      What remains                       │
├───────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤
│ Hardcoded values (fabricinfra, localho.st,    │ Handled. Assertions 3–6 find endpoints from the labelled per-endpoint Services, so no  │                                                         │
│ org1peer…) where CI uses default,             │ node name is hardcoded and Org2 is covered. Assertions 1–2 use $NS, $CONSOLE_NAME and  │ Implementation only.                                    │
│ <ip>.nip.io, random names; Org2 missing       │ $CONSOLE_URL from the CI environment. The domain comes from HLF_NETWORK_DOMAIN /       │                                                         │
│                                               │ EXPOSED_DOMAIN.                                                                        │                                                         │
├───────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤
│ Rewrites applied after the playbook, though   │ Handled. In scenario C the rules are pattern-based and written by kind_with_nginx.sh   │ Implementation only. The CI must export the EXPOSE_*,   │
│ build_network.sh needs them during its run    │ at cluster bootstrap. In scenario B there are no rewrites at all.                      │ HLF_NETWORK_DOMAIN and CLUSTER_DOMAIN variables before  │
│                                               │                                                                                        │ the bootstrap (in the 1.4b and 1.5 todo lists).         │
├───────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤
│ Proposed Corefile drops the hosts block and   │ Handled. 1.4b keeps the existing Corefile and inserts the endpoint rules before the    │ Implementation, then the planned local check of the     │
│ the nip.io rewrite, so the console no longer  │ wildcards.                                                                             │ CoreDNS ConfigMap after bootstrap.                      │
│ resolves                                      │                                                                                        │                                                         │
├───────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤
│ Assertions test :7051/:7050/:7054 though      │ Handled. Assertions 3–5 go through :443 and check each Service's target port. Expected │                                                         │
│ traffic uses :443; exit_code=$? never reached │  failures use rc=0; cmd || rc=$? under set -euo pipefail.                              │ Implementation only.                                    │
│  under set -e                                 │                                                                                        │                                                         │
├───────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤
│ In-cluster Job: read-only ConfigMap mount,    │ Covered, but not settled. 1.5 lists the permissions needed (services, configmaps in    │                                                         │
│ flattened tree, 1 MiB limit, no               │ kube-system, node CRs for neutralization). It also flags the ConfigMap limits and      │ Three gaps, below.                                      │
│ ServiceAccount/RBAC                           │ offers two fixes: copy to an emptyDir, or build the tutorial into the runner image.    │                                                         │
└───────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────┘

The Job gaps:
1. Choose how the tutorial reaches the Job. tutorial/ is 436 KB, flat and about 80 files, so a ConfigMap fits under 1 MiB today. But the playbooks write *.json and *.bin files into it, and fabcar@1.0.0.tgz is a binary. So copying to an emptyDir works but is fragile. Building the tutorial into the runner image is simpler, since the image is built in the same CI run anyway. The plan still lists both and still shows kubectl create configmap tutorial-files as a step.
2. Write the ServiceAccount, Role and RoleBinding. 1.5 says which permissions are needed, but there's no manifest or todo item for them yet.
3. The Job doesn't apply the domain and run-ID settings. It runs build_network.sh etc. directly, not run-tests.sh. So the yq patching of sub-task 1.4 (api_endpoint set to console_incluster_url, domains, expose_*, unique run names) doesn't happen inside the Job. Either run run-tests.sh inside the Job, or have the image build step patch common-vars.yml first.

Two prerequisites from earlier steps also affect this leg:
- Step 0's run-ID stamping: it's still missing, and run-tests.sh:42 still has the PATCH_BG_PID crash.
- Check 5: the first scenario B run end to end, which this leg is supposed to provide.

Should I settle the three Job gaps in sub-task 1.5?
>>>

---

Settle the three Job gaps in sub-task 1.5

<<<
I settled the three Job gaps in sub-task 1.5 of MIGRATION-STEP-1.md, and tried the image and permissions on the local Kind cluster. A full network run inside the Job has not been done yet.

┌──────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│           Gap            │                                                                                Decision                                                                                │
├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ How the tutorial reaches │ It's copied into the runner image, in a writable /workspace. No ConfigMap, so no read-only mount, no flattened tree and no size limit. The playbooks can write their   │
│  the Job                 │ JSON and binary files next to themselves.                                                                                                                              │
├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ServiceAccount and       │ A dedicated ansible-runner ServiceAccount. A Role in default covers what the playbooks need: per-endpoint Services, patching node resources, reading Ingresses. A      │
│ permissions              │ second Role in kube-system allows reading only the coredns ConfigMap. The full manifests are in the plan.                                                              │
├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Variable injection       │ The Job runs run-tests.sh, so it gets the same patching as the runner leg. Its inputs come from a ConfigMap and a Secret created by the CI step. API_ENDPOINT is the   │
│                          │ in-cluster HTTPS console URL.                                                                                                                                          │
└──────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

Teardown: the 1.6 assertions need the network alive, so the Job runs with KEEP_NETWORK=true. After the assertions, a second Job runs with RUN_TESTS_MODE=destroy. Both Jobs share one TEST_RUN_ID from the CI step, so the destroy finds the same randomised names. I added those three options to sub-task 1.4's todo list for run-tests.sh.

Runner image: it builds on the collection image the repo already publishes (root Dockerfile), which has Ansible, the collection, kubernetes.core and peer/osnadmin/configtxlator. My first version failed because that image has no pip, jq or shasum. The fixed Dockerfile installs them; it's in the plan and in .url_management_new_checks/job/.

Tried on 2026-10-16:
- Images: both build.
- Tools: the runner has yq with a working -yi, jq, shasum, peer 2.5.9 and ansible-playbook.
- Writable workspace: /workspace can be written, also under a random user ID with group 0 (OpenShift-style).
- Permissions: checked with kubectl auth can-i. The ServiceAccount can do exactly what it needs and is denied everything else: other kube-system ConfigMaps, creating peers or Deployments, reading Secrets.
- Manifests: both pass kubectl apply --dry-run=server.
- Probe pod: a pod with that ServiceAccount read the CoreDNS ConfigMap with no kubeconfig, and got HTTP 200 from the in-cluster console URL.

Still open:
- Full run: a complete run-tests.sh inside the Job (check 5). It's blocked on the Step 0 run-tests.sh fixes: the PATCH_BG_PID crash and the missing run-ID stamping.
- Fabric versions: the image has peer 2.5.9 but the runner leg installs 2.4.7. That's already a Step 0 review item.

The test resources are removed from the cluster. The images stay in the local Docker store and on the Kind node.
>>>

## Check & fix remaining review `Documentation inconsistencies`

Given the last changes, summarize what remains to be handled to cover STEP 1 Review `Documentation inconsistencies`

<<<
Of the three "Documentation inconsistencies", one is resolved, one is gone because the text it referred to was rewritten, and one is still open. That last one is worse than the review described: it's a real bug, not a wording issue.

┌─────────────────────────────────────┬────────────────────────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────┐
│             Review item             │                                 Status                                 │                                    What remains                                    │
├─────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────┤
│ RBAC (sub-task 1.2): the operator   │ Noted, not decided. 1.2 now carries the review note and says "keep     │ One decision: drop 1.2 from Step 1 or move it to Step 2. Since Step 1 adds no      │
│ doesn't create the routes, so       │ only if Step 2 confirms the operator reads Gateway API objects;        │ Gateway API objects, dropping it is consistent with acceptance criterion 9 ("no    │
│ extending its ClusterRole is        │ otherwise drop it". It's still listed as a Step 1 sub-task with its    │ Gateway API … introduced"). Its only Step 1 content, the CoreDNS-read permission,  │
│ unnecessary                         │ todo items.                                                            │ is already covered by the 1.5 RBAC.                                                │
├─────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────┤
│ Sub-task 1.3 says "five-task block" │ Gone. 1.3 was rewritten (guard the existing Ingress tasks, add the     │                                                                                    │
│  but lists six                      │ Deployment-readiness and notice tasks) and no longer refers to that    │ Nothing.                                                                           │
│                                     │ block.                                                                 │                                                                                    │
├─────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────┤
│ IBPConsole read as v1alpha2 but     │ Open, and it's a functional bug.                                       │ Explained below.                                                                   │
│ created as v1beta1                  │                                                                        │                                                                                    │
└─────────────────────────────────────┴────────────────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────┘

Why the apiVersion mismatch matters: on the live Kind cluster, the operator's IBPConsole CRD serves only v1beta1, and the node CRDs likewise. I queried the running console with kubernetes.core.k8s_info both ways:
- api_version: ibp.com/v1alpha2 returns 0 resources, api_found=False, and no error;
- api_version: ibp.com/v1beta1 finds the console.

So Determine if console exists (roles/fabric_console/tasks/k8s/create.yml:20, roles/hlfsupport_console/tasks/k8s/create.yml:89, and the OpenShift variants) always concludes there is no console. It fails silently.

That matters for Step 1: sub-task 1.3a's "domain changed on an existing console → restart" relies on reading the live console, and would never trigger. Also, hlfsupport_console uses that result to decide whether to delete and recreate the console on upgrade (create.yml:113,122).

The delete.yml files pick v1alpha2 or v1alpha1 by product_version and never v1beta1. The deletes themselves still work, because the tutorial delete playbook uses v1beta1.

Fix for Step 1:
- Use ibp.com/v1beta1 in every IBPConsole read and delete in both console roles, matching the templates and the tutorial.
- Add a todo item in 1.3a.
- Correct the review entry: it's a bug, not a documentation issue.

Should I record the apiVersion fix in 1.3a and drop sub-task 1.2?
>>>

---

Record the apiVersion fix in 1.3a and move sub-task 1.2 to step 2

## Double check plan STEP0 and STEP1 given the last changes

Given the last changes, double check review of STEP0 and STEP1 and summarize what remains to be handled

<<<
I've now cross-checked every item in both reviews. Step 1's plan covers all its findings; four small text fixes are left. Step 0 is still not done, although it's marked complete, and its crash bug also blocks Step 1's in-cluster test run.

Step 0 — not complete (MIGRATION-STEP-0.md says [x] complete)

┌──────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────┐
│         Review item          │                                             Current state                                             │                           To do                            │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ B4: run-tests.sh crash       │ The review says it's fixed, but run-tests.sh:42 still has wait "${PATCH_BG_PID}" || true. Under set   │ Delete line 42, then do a full run (exit=0).               │
│                              │ -u the script stops after build_network.sh, so join and deploy never run.                             │                                                            │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ TEST_RUN_ID stamping         │ Not in run-tests.sh.                                                                                  │ Implement it, taking an existing TEST_RUN_ID from the      │
│                              │                                                                                                       │ environment (needed by Step 1.5's two Jobs).               │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Python version               │ CI uses 3.9; the setup guide says "exactly 3.10".                                                     │ Align them.                                                │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Fabric version               │ CI installs 2.4.7; the setup guide downloads 2.5.15 under a "2.4.7" heading; the runner image has     │ Pick one version for all three.                            │
│                              │ 2.5.9.                                                                                                │                                                            │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ CI trigger                   │ fvtest.yml runs only on workflow_dispatch. Step 1 expects it on every push.                           │ Add push / pull_request, or reword Step 1.                 │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Sub-task 0.1 vs              │ 0.1 describes an inline playbook using fabric_console; CI actually runs                               │ Update 0.1 to match.                                       │
│ implementation               │ tutorial/00-deploy-fabric-console.yml.                                                                │                                                            │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Setup guide prerequisites    │ It doesn't mention reinstalling the collection with -f or setting ANSIBLE_PYTHON_INTERPRETER, and it  │ Update MIGRATION-PREREQ-LDE.md §1–§3.                      │
│                              │ still suggests brew install yq, which installs the wrong yq.                                          │                                                            │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Health path (from the Step 1 │ Step 0 and the setup guide use /health, which returns the UI's HTML page without credentials and      │ Use /ak/api/v3/health with credentials.                    │
│  Console review)             │ proves nothing about the API.                                                                         │                                                            │
└──────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────┘

Step 1 — plan complete; four text fixes

All findings are covered in MIGRATION-STEP-1.md:
- B2 (operator Ingresses): combines review options (a) and (b). The operator's Ingresses stay, the console Ingress is made unserved, and node Ingresses can be neutralized as an opt-in (1.3c, checked on a CA).
- B3 (one port 443 can't serve several hostnames): solved by one Service per endpoint (1.3b).
- Variables and facts: the network_domains role (1.1); its prototype passes 13/13 test cases.
- Organization roles: the guarded Kubernetes dependency and the node names (1.3b). The Step 3 items moved to the Step 3 review.
- Console: sub-tasks 1.3 and 1.3a, including the apiVersion bug.
- Expose-none CI: sub-tasks 1.4b, 1.5 and 1.6; the Job image and permissions were tried on Kind.
- Documentation inconsistencies: RBAC moved to Step 2; the "five-task" text is gone; the apiVersion fix is in 1.3a.

The four text fixes:
1. F3 is still listed as open. MIGRATION-STEP-1.md:512 and the :762 todo item, plus URL-MANAGEMENT-NEW.md §9.1, still call it an unexplained console behaviour. It was my command-line quoting: -e name="Check1 CA" is cut at the space. Close it in all three places.
2. The prototype still hardcodes cluster.local for console_incluster_url when the cluster domain isn't resolved (network_domains/tasks/main.yml:124). It should be empty in that case.
3. The Step 1 review's "Recommended order of action" is out of date. All three actions are done: B2 decided, operator check run on 2026-10-16, Step 1 rewritten around per-endpoint Services. Mark them done, as the Step 0 review does for its item.
4. The Step 1 review entries carry no status. Unlike the Step 0 review's B4 "fixed" marker, nothing shows which findings are handled. Add a status line per section pointing to the covering sub-task.

Blocked until implementation

These only happen once the plan is coded:
- Check 5: scenario B end to end. It needs the Step 1.5 Job, which runs run-tests.sh, so it's blocked on the Step 0 crash fix.
- Check 3 on a peer: needed before node Ingress neutralization can be on by default.
- Upgrade run after the apiVersion fix: hlfsupport_console will then see the existing console in its upgrade path.
- Multi-peer name check: confirm org1peer1, org1peer2… on a real run.

Step 0 is the critical path: B4 alone blocks both the baseline and Step 1's end-to-end check. Should I fix run-tests.sh and the Step 0 docs first, or do the four Step 1 text fixes first?
>>>

---

Do the four Step 1 text fixes first

---

Given the last changes, double check review of STEP0 and STEP1 and summarize what remains to be handled

<<<
Step 1's review is fully covered by the plan, and the four text fixes are in place. Step 0 is unchanged: none of its items have been handled. One inconsistency remains between the two summaries of B4.

Step 1: plan complete

Re-checked against the current files:
- Status lines: all 8 sections of the Step 1 review carry one, each pointing to the covering sub-task.
- F3: closed everywhere; no "open" mention is left outside the PROMPTS.md log.
- Prototype: no cluster.local fallback remains; 13/13 tests pass.
- No stale design left in MIGRATION-STEP-1.md:
  - the old design (set_facts.yml, ingress_domain*) appears only where the text explains what was replaced;
  - v1alpha2 appears only in the description of the apiVersion bug;
  - there is no fabricinfra, COREDNS_HOOK or sub-task 1.2 any more.
- Overview review: REVIEW-MIGRATION-PLAN.md shows B2 decided and B3 planned.

What's left for Step 1 is the implementation, plus four checks that need it: scenario B end to end (check 5), check 3 on a peer, an upgrade run after the apiVersion fix, and multi-peer names.

Step 0: nothing handled yet

┌───────────────────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│         Item          │                                                                          State                                                                           │
├───────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ B4 PATCH_BG_PID crash │ Still at run-tests.sh:42. Without it, join and deploy never run.                                                                                         │
├───────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ TEST_RUN_ID stamping  │ Not implemented. Step 1.5 also needs it to accept an ID from the environment.                                                                            │
├───────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Status                │ MIGRATION-STEP-0.md still says [x] complete.                                                                                                             │
├───────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Python version        │ CI uses 3.9; MIGRATION-PREREQ-LDE.md says "exactly 3.10".                                                                                                │
├───────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Fabric version        │ CI 2.4.7; the setup guide downloads 2.5.15 under a "2.4.7" heading; the runner image has 2.5.9.                                                          │
├───────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ CI trigger            │ workflow_dispatch only. No Step 1 file says "every push" any more, so this is now a choice, not a contradiction.                                         │
├───────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Sub-task 0.1          │ Still describes an inline playbook with fabric_console; CI runs tutorial/00-deploy-fabric-console.yml.                                                   │
├───────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Setup guide           │ Still brew install yq (the wrong yq); no ANSIBLE_PYTHON_INTERPRETER. It does show collection install … -f, but doesn't explain why reinstalling matters. │
├───────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Health path           │ /health in MIGRATION-STEP-0.md:123 and MIGRATION-PREREQ-LDE.md:195,198; it returns the UI page, not API health.                                          │
└───────────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

The inconsistency: the overview now says B4 is Open, but REVIEW-MIGRATION-PLAN-STEP-0.md still says "fixed" and "the line was removed". That's wrong: the line is in the file. Either the fix was never saved or it was reverted. The Step 0 review should read "Open" until the line is gone and a full run passes.

Fixing run-tests.sh (B4 and the run-ID stamping) unblocks both the Step 0 baseline and Step 1's end-to-end check. The doc items can follow in the same pass. Should I start?
>>>