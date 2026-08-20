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

