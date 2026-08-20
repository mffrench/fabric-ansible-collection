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
