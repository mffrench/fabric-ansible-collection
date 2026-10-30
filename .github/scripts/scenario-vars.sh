#!/usr/bin/env bash
# Copyright the Hyperledger Fabric contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Scenario variables of the tests (MIGRATION-STEP-1 sub-task 1.3), sourced by
# run-tests.sh and deploy-console.sh. They are written to
# tutorial/common-vars.yml, which every tutorial playbook reads (console and
# organizations), so all of them get the same values.
#
#   INGRESS_TYPE                         nginx (the only value in Step 1)
#   EXPOSE_CONSOLE, EXPOSE_CA,
#   EXPOSE_PEER, EXPOSE_ORDERER          true | false, default true
#   EXPOSE_PEER_OPERATIONS,
#   EXPOSE_ORDERER_OPERATIONS,
#   EXPOSE_GRPCWEB                       true | false, default false
#   EXPOSED_DOMAIN, HLF_NETWORK_DOMAIN,
#   CLUSTER_DOMAIN                       written only when set
#   NEUTRALIZE_NODE_INGRESSES            true | false, written only when set
#
# A variable that is not set is removed from common-vars.yml, so a value left
# by a previous run never leaks into the next one: the network_domains role
# defaults apply instead.

SCENARIO_BOOL_VARS="EXPOSE_CONSOLE:true EXPOSE_CA:true EXPOSE_PEER:true EXPOSE_ORDERER:true
EXPOSE_PEER_OPERATIONS:false EXPOSE_ORDERER_OPERATIONS:false EXPOSE_GRPCWEB:false"
SCENARIO_DOMAIN_VARS="EXPOSED_DOMAIN HLF_NETWORK_DOMAIN CLUSTER_DOMAIN"

# scenario_bool NAME VALUE: prints true or false, fails on any other value
scenario_bool() {
    case "$(echo "$2" | tr '[:upper:]' '[:lower:]')" in
        true) echo true ;;
        false) echo false ;;
        *) echo "ERROR: $1='$2': must be true or false" >&2; return 1 ;;
    esac
}

# scenario_key NAME: the vars-file key of an environment variable (lower case)
scenario_key() {
    echo "$1" | tr '[:upper:]' '[:lower:]'
}

# patch_scenario_vars FILE: writes the scenario variables to FILE (one yq call)
patch_scenario_vars() {
    local vars="$1" filter spec name value
    INGRESS_TYPE="${INGRESS_TYPE:-nginx}"
    if [[ "${INGRESS_TYPE}" != "nginx" ]]; then
        echo "ERROR: INGRESS_TYPE='${INGRESS_TYPE}': only nginx is supported in Step 1" >&2
        return 1
    fi
    filter=".ingress_type=\"${INGRESS_TYPE}\""
    for spec in ${SCENARIO_BOOL_VARS}; do
        name="${spec%%:*}"
        value="$(scenario_bool "${name}" "${!name:-${spec#*:}}")" || return 1
        filter="${filter} | .$(scenario_key "${name}")=${value}"
    done
    for name in ${SCENARIO_DOMAIN_VARS}; do
        value="${!name:-}"
        if [[ -z "${value}" ]]; then
            filter="${filter} | del(.$(scenario_key "${name}"))"
        elif [[ "${value}" =~ ^[A-Za-z0-9.-]+$ ]]; then
            filter="${filter} | .$(scenario_key "${name}")=\"${value}\""
        else
            echo "ERROR: ${name}='${value}' is not a domain name" >&2
            return 1
        fi
    done
    if [[ -n "${NEUTRALIZE_NODE_INGRESSES:-}" ]]; then
        value="$(scenario_bool NEUTRALIZE_NODE_INGRESSES "${NEUTRALIZE_NODE_INGRESSES}")" || return 1
        filter="${filter} | .neutralize_node_ingresses=${value}"
    else
        filter="${filter} | del(.neutralize_node_ingresses)"
    fi
    yq -yi "${filter}" "${vars}"
}

# print_scenario_vars FILE: prints the scenario variables as written in FILE
print_scenario_vars() {
    local vars="$1" keys="ingress_type" spec name key value
    for spec in ${SCENARIO_BOOL_VARS}; do keys="${keys} $(scenario_key "${spec%%:*}")"; done
    for name in ${SCENARIO_DOMAIN_VARS}; do keys="${keys} $(scenario_key "${name}")"; done
    keys="${keys} neutralize_node_ingresses"
    echo "==> Scenario variables in $(basename "${vars}")"
    for key in ${keys}; do
        value="$(yq -r "if .${key} == null then \"(unset)\" else .${key} end" "${vars}")"
        printf '    %-26s %s\n' "${key}" "${value}"
    done
}
