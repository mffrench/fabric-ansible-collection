#
# SPDX-License-Identifier: Apache-2.0
#
# Local Development Environment — shell setup.
#
# SOURCE this file (do not execute it) from the repository root or anywhere else:
#
#     source .github/scripts/lde-env.sh
#
# It is host-agnostic: works under bash and zsh, on macOS and Linux, and is
# idempotent. It sets up everything the tutorial playbooks and test scripts
# expect, each guarded so that a missing piece degrades to a warning rather
# than a hard failure (CI provides some of these by other means):
#
#   * activates .venv            — ansible-core + kubernetes SDK + python-yq
#   * PATH += <repo>/bin         — Fabric CLI binaries (peer, configtxlator, ...)
#   * FABRIC_CFG_PATH            — core.yaml for the peer CLI
#   * KUBECONFIG                 — written by kind_with_nginx.sh
#   * ANSIBLE_PYTHON_INTERPRETER — see note below
#
# Run `lde_preflight` afterwards to check the environment before a test run.

# ---- Locate the repository root, under bash or zsh ---------------------------
# zsh has no BASH_SOURCE; its equivalent is ${(%):-%x}, which bash cannot parse.
# eval defers parsing so that each shell only ever reads its own syntax.
if [ -n "${ZSH_VERSION:-}" ]; then
    _lde_src=$(eval 'echo ${(%):-%x}')
else
    _lde_src="${BASH_SOURCE[0]}"
fi

if [ -z "${_lde_src}" ]; then
    echo "lde-env.sh: source this file, do not execute it" >&2
    return 1 2>/dev/null || exit 1
fi

# `cd && pwd` rather than readlink -f / realpath: neither is present by default
# on macOS.
LDE_REPO_ROOT=$(cd "$(dirname "${_lde_src}")/../.." && pwd)
export LDE_REPO_ROOT
unset _lde_src

# ---- Python virtualenv -------------------------------------------------------
if [ -f "${LDE_REPO_ROOT}/.venv/bin/activate" ]; then
    # Re-activating the same venv is harmless; activating a different one first
    # deactivates it, so guard on the path to stay idempotent.
    if [ "${VIRTUAL_ENV:-}" != "${LDE_REPO_ROOT}/.venv" ]; then
        # shellcheck source=/dev/null
        . "${LDE_REPO_ROOT}/.venv/bin/activate"
    fi
else
    echo "lde-env.sh: no .venv found — see MIGRATION-PREREQ-LDE.md section 2" >&2
fi

# ---- Fabric CLI binaries -----------------------------------------------------
# BlockchainModule verifies `peer` and `configtxlator` at module start-up, so
# these must be on PATH before any playbook runs.
if [ -d "${LDE_REPO_ROOT}/bin" ]; then
    case ":${PATH}:" in
        *":${LDE_REPO_ROOT}/bin:"*) ;;
        *) PATH="${LDE_REPO_ROOT}/bin:${PATH}"; export PATH ;;
    esac
else
    echo "lde-env.sh: no bin/ found — see MIGRATION-PREREQ-LDE.md section 4" >&2
fi

# The peer CLI needs core.yaml. The modules set FABRIC_CFG_PATH for their own
# subprocesses, but not for the `peer version` start-up check.
if [ -d "${LDE_REPO_ROOT}/config" ]; then
    FABRIC_CFG_PATH="${LDE_REPO_ROOT}/config"
    export FABRIC_CFG_PATH
fi

# ---- Kubernetes --------------------------------------------------------------
if [ -f "${LDE_REPO_ROOT}/_cfg/k8s_context.yaml" ]; then
    KUBECONFIG="${LDE_REPO_ROOT}/_cfg/k8s_context.yaml"
    export KUBECONFIG
fi

# ---- Ansible interpreter -----------------------------------------------------
# Ansible only equates the target interpreter with the one running
# ansible-playbook for the *implicit* localhost. deploy-console.sh passes
# `-i localhost,`, which puts localhost in the inventory and hands the choice to
# interpreter discovery — on macOS that finds Homebrew's python3, which has no
# kubernetes SDK. Pinning it here fixes every entry point at once.
if [ -n "${VIRTUAL_ENV:-}" ]; then
    ANSIBLE_PYTHON_INTERPRETER="${VIRTUAL_ENV}/bin/python"
    export ANSIBLE_PYTHON_INTERPRETER
fi

# ---- Portable helpers --------------------------------------------------------
# shasum is standard on macOS; Linux ships sha1sum. Used to stamp test run IDs.
lde_sha1() {
    if command -v shasum >/dev/null 2>&1; then
        shasum | awk '{print $1}'
    else
        sha1sum | awk '{print $1}'
    fi
}

# Which process, if any, holds a local TCP port. lsof is present on macOS and
# most Linux distributions; ss is the modern Linux fallback.
lde_port_owner() {
    _p="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"${_p}" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1" (pid "$2")"}'
    elif command -v ss >/dev/null 2>&1; then
        ss -ltnp 2>/dev/null | awk -v p=":${_p}\$" '$4 ~ p {print $NF; exit}'
    fi
    unset _p
}

# ---- Preflight ---------------------------------------------------------------
# Verifies everything the tutorial run depends on. Returns non-zero on the first
# hard failure so it can gate a test run.
lde_preflight() {
    _rc=0

    for _c in ansible-playbook peer configtxlator kubectl yq jq; do
        if command -v "${_c}" >/dev/null 2>&1; then
            printf '  ok      %-16s %s\n' "${_c}" "$(command -v "${_c}")"
        else
            printf '  MISSING %-16s\n' "${_c}"
            _rc=1
        fi
    done

    # python-yq (kislyuk) understands `-yi`; the Go yq (mikefarah) does not.
    # Every test script writes YAML in place with `yq -yi`.
    if command -v yq >/dev/null 2>&1; then
        if yq --help 2>&1 | grep -q -- '-y.*--yaml-output\|--yaml-output'; then
            printf '  ok      %-16s python-yq (supports -yi)\n' "yq flavour"
        else
            printf '  WRONG   %-16s Go yq detected; scripts need python-yq (pip install yq)\n' "yq flavour"
            _rc=1
        fi
    fi

    if [ -n "${KUBECONFIG:-}" ] && command -v kubectl >/dev/null 2>&1; then
        if kubectl cluster-info >/dev/null 2>&1; then
            printf '  ok      %-16s %s\n' "cluster" "$(kubectl config current-context 2>/dev/null)"
        else
            printf '  MISSING %-16s cluster unreachable via %s\n' "cluster" "${KUBECONFIG}"
            _rc=1
        fi
    fi

    # The Kind node publishes hostPort 80/443. Anything else holding them means
    # the ingress is unreachable from the host, which surfaces much later as an
    # unexplained 404 from a foreign ingress controller.
    for _p in 80 443; do
        _owner=$(lde_port_owner "${_p}")
        if [ -n "${_owner}" ]; then
            printf '  check   %-16s held by %s\n' "port ${_p}" "${_owner}"
        fi
    done
    unset _p _owner

    if [ -f "${LDE_REPO_ROOT}/_cfg/console-env.sh" ]; then
        printf '  ok      %-16s _cfg/console-env.sh\n' "console env"
    else
        printf '  note    %-16s not deployed yet (run deploy-console.sh)\n' "console env"
    fi

    return ${_rc}
}

echo "LDE ready: ${LDE_REPO_ROOT}"
echo "           run 'lde_preflight' to verify the environment"
