#!/usr/bin/env bash
#
# SPDX-License-Identifier: Apache-2.0
#
# Rule tests of the network_domains role (MIGRATION-STEP-1 sub-task 1.2).
# Needs the collection installed and KUBECONFIG pointing at a KIND cluster.
#
#   tests/network_domains/run.sh
#
set -euo pipefail
cd "$(dirname "$0")"

ansible-playbook -i localhost, -c local test.yml

ansible-playbook -i localhost, -c local test_extra_vars.yml \
  -e exposed_domain=example.com -e hlf_network_domain=cluster.local \
  -e cluster_domain= -e expose_ca=false -e expose_peer=false -e expose_orderer=false
