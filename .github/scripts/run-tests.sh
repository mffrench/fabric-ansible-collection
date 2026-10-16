#!/usr/bin/env bash
# Copyright the Hyperledger Fabric contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

# For local development: source connection details written by deploy-console.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
if [[ -f "${REPO_ROOT}/_cfg/console-env.sh" ]]; then
    # shellcheck source=/dev/null
    source "${REPO_ROOT}/_cfg/console-env.sh"
fi

# Connection defaults — overridden by environment when running in CI
API_ENDPOINT="${API_ENDPOINT:-https://127.0.0.1.nip.io:443}"
API_AUTHTYPE="${API_AUTHTYPE:-basic}"
API_KEY="${API_KEY:-admin}"
API_SECRET="${API_SECRET:-password}"
K8S_NAMESPACE="${K8S_NAMESPACE:-default}"

cd tutorial

# Inject live connection parameters into every org vars file
for VARS in ordering-org-vars.yml org1-vars.yml org2-vars.yml; do
    yq -yi ".api_endpoint=\"${API_ENDPOINT}\""   "${VARS}"
    yq -yi ".api_authtype=\"${API_AUTHTYPE}\""   "${VARS}"
    yq -yi ".api_key=\"${API_KEY}\""             "${VARS}"
    yq -yi ".api_secret=\"${API_SECRET}\""       "${VARS}"
    yq -yi ".api_timeout=300"                    "${VARS}"
    yq -yi ".k8s_namespace=\"${K8S_NAMESPACE}\"" "${VARS}"
    yq -yi ".wait_timeout=1800"                  "${VARS}"
done

function cleanup {
    ./join_network.sh destroy || true
}
trap cleanup EXIT

./build_network.sh build

# Ensure the background patcher has exited before continuing
wait "${PATCH_BG_PID}" || true
./join_network.sh join
./deploy_smart_contract.sh

trap - EXIT
./join_network.sh destroy
