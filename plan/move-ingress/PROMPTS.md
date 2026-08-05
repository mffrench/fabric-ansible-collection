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

TODO
