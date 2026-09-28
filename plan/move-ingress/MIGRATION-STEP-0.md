# Step 0 — Fix Existing CI & Local Test Harness

**Roadmap reference:** Pre-requisite step for [`MIGRATION-STEP-1.md`](./MIGRATION-STEP-1.md)  
**Plan reference:** [`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) — §5.3, [`PRE-ANALYSIS.md`](./PRE-ANALYSIS.md) — §2.5  
**Status:** `[ ] pending`

---

## Overview

The current Functional Verification (FV) test setup in `.github/workflows/fvtest.yml` and `.github/scripts/run-tests.sh` cannot execute successfully because:
1. **Infrastructure components (Fabric Operator & Console) are never provisioned** before calling the network build playbooks.
2. **`run-tests.sh` contains fatal bugs**:
   - Immediate crash under `set -euo pipefail` when invoked without arguments (`$1`, `$2` unbound variables).
   - No injection of connection parameters (`api_endpoint`, `api_key`, `api_secret`, `k8s_namespace`) into `tutorial/*-vars.yml`.
   - Fixed resource names colliding on repeat or parallel runs (no dynamic test run ID stamping).

The goal of **Step 0** is to repair the baseline CI workflow and test scripts so that the entire tutorial test suite runs and passes cleanly against a local Kind cluster and on GitHub Actions, establishing a functional baseline before introducing Gateway API changes.

---

## Sub-task 0.1 — Deploy Infrastructure (Operator & Console) in CI Workflow

**Intent:** Ensure the Fabric Operator and Fabric Console are installed and fully healthy before executing the tutorial playbooks.

**Changes required in `.github/workflows/fvtest.yml`:**
- Add an explicit step after Kind cluster creation and collection installation to deploy `roles/fabric_operator_crds` and `roles/fabric_console`.
- Configure `console_domain` using the host/runner IP address with `nip.io`.
- Export environment variables required by the test runner (`API_ENDPOINT`, `API_KEY`, `API_SECRET`, `K8S_NAMESPACE`, `KUBECONFIG`).

```yaml
      - name: Deploy Fabric Operator and Console
        run: |
          ansible-playbook -i localhost, -c local <(cat << 'EOF'
          - name: Deploy Fabric Infrastructure
            hosts: localhost
            vars:
              state: present
              target: k8s
              namespace: default
              wait_timeout: 600
              console_name: hlf-console
              console_domain: ${{ env.TEST_NETWORK_INGRESS_DOMAIN }}
              console_email: admin@example.com
              console_default_password: password
              console_storage_class: standard
            roles:
              - hyperledger.fabric_ansible_collection.fabric_operator_crds
              - hyperledger.fabric_ansible_collection.fabric_console
          EOF
          )
```

---

## Sub-task 0.2 — Rewrite `.github/scripts/run-tests.sh`

**Intent:** Fix parameter parsing, test isolation, and dynamic variable injection.

**Implementation details for `.github/scripts/run-tests.sh`:**
1. Handle unbound positional parameters safely (defaulting `$TYPE` and `$TARGET` or reading from environment variables).
2. Generate a unique `TEST_RUN_ID` and `SHORT_TEST_RUN_ID` using `shasum`.
3. Patch `common-vars.yml`, `ordering-org-vars.yml`, `org1-vars.yml`, and `org2-vars.yml` with `yq` using the active `$API_ENDPOINT`, credentials, and unique organization names/MSPs.
4. Run `build_network.sh build`, `join_network.sh join`, `deploy_smart_contract.sh`, and ensure proper cleanup traps on exit.

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Stamping unique run ID
TEST_RUN_ID=$(dd if=/dev/urandom bs=4096 count=1 2>/dev/null | shasum | awk '{print $1}')
SHORT_TEST_RUN_ID=$(echo "${TEST_RUN_ID}" | awk '{print substr($1,1,8)}')

API_ENDPOINT="${API_ENDPOINT:-https://127.0.0.1.nip.io:443}"
API_AUTHTYPE="${API_AUTHTYPE:-basic}"
API_KEY="${API_KEY:-admin}"
API_SECRET="${API_SECRET:-password}"
K8S_NAMESPACE="${K8S_NAMESPACE:-default}"

cd tutorial

# 2. Patch tutorial common variables
yq -yi ".ordering_org_name=\"Ordering Org ${SHORT_TEST_RUN_ID}\"" common-vars.yml
yq -yi ".ordering_service_name=\"Ordering Service ${SHORT_TEST_RUN_ID}\"" common-vars.yml
yq -yi ".org1_name=\"Org1 ${SHORT_TEST_RUN_ID}\"" common-vars.yml
yq -yi ".org1_msp_id=\"Org1${SHORT_TEST_RUN_ID}MSP\"" common-vars.yml
yq -yi ".org2_name=\"Org2 ${SHORT_TEST_RUN_ID}\"" common-vars.yml
yq -yi ".org2_msp_id=\"Org2${SHORT_TEST_RUN_ID}MSP\"" common-vars.yml

# 3. Patch connection settings across all org vars
for VARS in ordering-org-vars.yml org1-vars.yml org2-vars.yml; do
    yq -yi ".api_endpoint=\"${API_ENDPOINT}\"" "${VARS}"
    yq -yi ".api_authtype=\"${API_AUTHTYPE}\"" "${VARS}"
    yq -yi ".api_key=\"${API_KEY}\"" "${VARS}"
    yq -yi ".api_secret=\"${API_SECRET}\"" "${VARS}"
    yq -yi ".k8s_namespace=\"${K8S_NAMESPACE}\"" "${VARS}"
    yq -yi ".wait_timeout=1800" "${VARS}"
done

# 4. Execute test phases with cleanup trap
function cleanup {
    ./join_network.sh destroy || true
}
trap cleanup EXIT

./build_network.sh build
./join_network.sh join
./deploy_smart_contract.sh

trap - EXIT
./join_network.sh destroy
```

---

## Sub-task 0.3 — Local Test Environment Validation (LDE)

**Intent:** Verify that developer workstations running macOS or Linux can execute the tests end-to-end without CI-specific workarounds.

**Validation Checklist:**
- [ ] Kind cluster boots and NGINX Ingress controller becomes `Ready`.
- [ ] Operator CRDs and Console deploy without error.
- [ ] Console `/health` endpoint responds with HTTP 200 via `https://<namespace>-<console>-console.<domain>/health`.
- [ ] Tutorial playbooks (01 to 23) complete successfully.
- [ ] Network teardown plays (97, 98, 99) cleanly delete all created resources.
- [ ] Documented in [`plan/move-ingress/MIGRATION-PREREQ-LDE.md`](./MIGRATION-PREREQ-LDE.md).

---

## Deliverables & Acceptance Criteria

1. **`.github/workflows/fvtest.yml`**: Provisions Fabric Operator & Console and exports correct environment variables.
2. **`.github/scripts/run-tests.sh`**: Runs without positional arguments, updates variable configs dynamically with `yq`, and executes build/join/deploy lifecycle.
3. **CI Pass**: GitHub Actions workflow passes cleanly on the `nginx` baseline.
