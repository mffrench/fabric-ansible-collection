#!/usr/bin/env bash
# Copyright the Hyperledger Fabric contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Deprovision the Fabric Operations Console and Operator CRDs from the active
# Kubernetes/Kind cluster, and clean up generated connection env files.
#
# Usage:
#   export KUBECONFIG="$PWD/_cfg/k8s_context.yaml"
#   .github/scripts/undeploy-console.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Activate virtual environment if present
if [[ -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
    # shellcheck source=/dev/null
    source "${REPO_ROOT}/.venv/bin/activate"
fi

# ---- Configuration -----------------------------------------------------------
CONSOLE_NAMESPACE="${CONSOLE_NAMESPACE:-default}"
CONSOLE_NAME="${CONSOLE_NAME:-hlf-console}"

echo "==> Deprovisioning Fabric Operations Console and CRDs"
echo "    namespace : ${CONSOLE_NAMESPACE}"
echo "    name      : ${CONSOLE_NAME}"
echo ""

# ---- Deprovision via ansible-playbook -----------------------------------------
ansible-playbook -i localhost, -c local \
  -e k8s_target=k8s \
  -e k8s_namespace="${CONSOLE_NAMESPACE}" \
  -e hlf_console_name="${CONSOLE_NAME}" \
  -e wait_timeout=300 \
  "${REPO_ROOT}/tutorial/00-delete-fabric-console.yml"

# ---- Clean up generated env file ---------------------------------------------
if [[ -f "${REPO_ROOT}/_cfg/console-env.sh" ]]; then
    echo "==> Removing ${REPO_ROOT}/_cfg/console-env.sh"
    rm -f "${REPO_ROOT}/_cfg/console-env.sh"
fi

echo ""
echo "==> Fabric Console and CRDs deprovisioned successfully."
