#!/bin/bash
#
# Copyright contributors to the Hyperledgendary Full Stack Asset Transfer project
#
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
# 	  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

set -eo pipefail
set -x

KIND_CLUSTER_NAME=kind
KIND_CLUSTER_IMAGE=${KIND_CLUSTER_IMAGE:-kindest/node:v1.25.3}        # Important! k8s v1.25.0 brings breaking changes.
KIND_API_SERVER_ADDRESS=${KIND_API_SERVER_ADDRESS:-127.0.0.1}
KIND_API_SERVER_PORT=${KIND_API_SERVER_PORT:-8888}
CONTAINER_REGISTRY_NAME=${CONTAINER_REGISTRY_NAME:-kind-registry}
CONTAINER_REGISTRY_ADDRESS=${CONTAINER_REGISTRY_ADDRESS:-127.0.0.1}
CONTAINER_REGISTRY_PORT=${CONTAINER_REGISTRY_PORT:-5000}
NAMESPACE=${NAMESPACE:-default}
CLUSTER_DOMAIN=${CLUSTER_DOMAIN:-cluster.local}
# HLF_NETWORK_DOMAIN defaults to NIP_DOMAIN (= exposed domain) inside
# apply_coredns_override

function kind_with_nginx() {

  delete_cluster

  create_cluster

  start_nginx

  apply_coredns_override

  launch_docker_registry
}

#
# Delete a kind cluster if it exists
#
function delete_cluster() {
  kind delete cluster --name $KIND_CLUSTER_NAME
}

#
# Create a local KIND cluster
#
function create_cluster() {
  cat << EOF | kind create cluster --name $KIND_CLUSTER_NAME --image $KIND_CLUSTER_IMAGE --config=-
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
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
networking:
  apiServerAddress: ${KIND_API_SERVER_ADDRESS}
  apiServerPort: ${KIND_API_SERVER_PORT}

# create a cluster with the local registry enabled in containerd
containerdConfigPatches:
- |-
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors."localhost:${CONTAINER_REGISTRY_PORT}"]
    endpoint = ["http://${CONTAINER_REGISTRY_NAME}:${CONTAINER_REGISTRY_PORT}"]
EOF

  #
  # Work around a bug in KIND where DNS is not always resolved correctly on machines with IPv6
  #
  for node in $(kind get nodes);
  do
      docker exec "$node" sysctl net.ipv4.conf.all.route_localnet=1;
  done
}

#
# Install an Nginx ingress controller bound to port 80 and 443.
# ssl_passthrough mode is enabled for TLS termination at the Fabric node enpdoints.
#
function start_nginx() {
  kubectl apply -k https://github.com/hyperledger-labs/fabric-operator.git/config/ingress/kind

  sleep 10

  kubectl wait --namespace ingress-nginx \
      --for=condition=ready pod \
      --selector=app.kubernetes.io/component=controller \
      --timeout=3m
}

# coredns_endpoint_rewrites NAMESPACE HLF_NETWORK_DOMAIN CLUSTER_DOMAIN
# One rewrite per endpoint type: <ns>-<cr>-<endpoint>.<domain> -> per-endpoint
# Service <ns>-<cr>-<endpoint>.<ns>.svc.<cluster_domain> (MIGRATION-STEP-1 1.6).
coredns_endpoint_rewrites() {
  local ns="$1" domain="$2" cluster_domain="$3"
  local domain_re="${domain//./\\.}"
  local cluster_domain_re="${cluster_domain//./\\.}"
  local endpoint
  for endpoint in ca peer orderer operations grpcweb admin; do
    printf '        rewrite stop {\n'
    printf '            name regex ^(%s-[a-z0-9]+-%s)\\.%s\\.$ {1}.%s.svc.%s\n' \
      "${ns}" "${endpoint}" "${domain_re}" "${ns}" "${cluster_domain}"
    printf '            answer name ^(%s-[a-z0-9]+-%s)\\.%s\\.svc\\.%s\\.$ {1}.%s\n' \
      "${ns}" "${endpoint}" "${ns}" "${cluster_domain_re}" "${domain}"
    printf '        }\n'
  done
}

#
# Override Core DNS with a wildcard matcher for the "*.localho.st" domain, binding to the
# IP address of the Nginx ingress controller on the kubernetes internal network.  Effectively this
# "steals" the domain name for *.localho.st, directing traffic to the Nginx load balancer, rather
# than to the loopback interface at 127.0.0.1.
#
function apply_coredns_override() {
  CLUSTER_IP=$(kubectl -n ingress-nginx get svc ingress-nginx-controller -o json | jq -r .spec.clusterIP)

  # Derive the nip.io domain from the API server address so that wildcard DNS
  # for that domain is also routed to the nginx ingress inside the cluster.
  # Without this, pods resolve *.nip.io via upstream DNS which returns 127.0.0.1
  # (the pod's own loopback) instead of the nginx cluster IP.
  NIP_DOMAIN=$(echo "${KIND_API_SERVER_ADDRESS:-127.0.0.1}" | tr -s '.' '-').nip.io

  # Scenario C (CA, peer and orderer unexposed, HLF network domain not
  # cluster-local): send each endpoint name to its per-endpoint Service, not to
  # nginx. These rules come before the wildcards: the first matching rewrite
  # wins, and the console name matches none of them.
  # Every regex ends with \.$ (CoreDNS names end with a dot): with ndots:5 a
  # pod first asks <name>.<search domain>, e.g. <name>.default.svc.cluster.local.
  # An unanchored rule answers that query too, under another name, and glibc
  # (getaddrinfo) drops the answer and stops: "Name or service not known".
  HLF_NETWORK_DOMAIN=${HLF_NETWORK_DOMAIN:-${NIP_DOMAIN}}
  ENDPOINT_REWRITES=""
  if [[ "${EXPOSE_CA:-true}" == "false" \
     && "${EXPOSE_PEER:-true}" == "false" \
     && "${EXPOSE_ORDERER:-true}" == "false" \
     && "${HLF_NETWORK_DOMAIN}" != "${CLUSTER_DOMAIN}" ]]; then
    ENDPOINT_REWRITES=$(coredns_endpoint_rewrites \
      "${NAMESPACE}" "${HLF_NETWORK_DOMAIN}" "${CLUSTER_DOMAIN}")
  fi

  cat << EOF | kubectl apply -f -
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
        health {
           lameduck 5s
        }
        ready
${ENDPOINT_REWRITES}
        rewrite name regex (.*)\.localho\.st\.$ host.ingress.internal
        rewrite name regex (.*)\.${NIP_DOMAIN}\.$ host.ingress.internal
        hosts {
          ${CLUSTER_IP} host.ingress.internal
          fallthrough
        }
        kubernetes ${CLUSTER_DOMAIN} in-addr.arpa ip6.arpa {
           pods insecure
           fallthrough in-addr.arpa ip6.arpa
           ttl 30
        }
        prometheus :9153
        forward . /etc/resolv.conf {
           max_concurrent 1000
        }
        cache 30
        loop
        reload
        loadbalance
    }
EOF

  kubectl -n kube-system rollout restart deployment/coredns
  kubectl rollout status deployment/coredns -n kube-system --timeout=60s
}

function launch_docker_registry() {
  
  # create registry container unless it already exists
  running="$(docker inspect -f '{{.State.Running}}' "${CONTAINER_REGISTRY_NAME}" 2>/dev/null || true)"
  if [ "${running}" != 'true' ]; then
    docker run  \
      --detach  \
      --restart always \
      --name    "${CONTAINER_REGISTRY_NAME}" \
      --publish "${CONTAINER_REGISTRY_ADDRESS}:${CONTAINER_REGISTRY_PORT}:${CONTAINER_REGISTRY_PORT}" \
      registry:2
  fi

  # connect the registry to the cluster network
  # (the network may already be connected)
  docker network connect "kind" "${CONTAINER_REGISTRY_NAME}" || true

  # Document the local registry
  # https://github.com/kubernetes/enhancements/tree/master/keps/sig-cluster-lifecycle/generic/1755-communicating-a-local-registry
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

kind_with_nginx

mkdir -p _cfg
# Use 'kind get kubeconfig' rather than 'kubectl config view --raw' so the
# cluster context is read directly from Kind's state regardless of whether
# ~/.kube/config has been populated.
kind get kubeconfig --name "${KIND_CLUSTER_NAME}" > _cfg/k8s_context.yaml