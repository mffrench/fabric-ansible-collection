# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An Ansible collection (`hyperledger.fabric_ansible_collection`, version in `galaxy.yml`) for building Hyperledger Fabric networks. It talks to the Fabric Operations Console REST API (open-source stack: Fabric Operator + Console on Kubernetes/OpenShift, or IBM Support for Hyperledger Fabric) and to Fabric peers/orderers via the `peer`, `configtxlator` and `osnadmin` binaries.

## Commands

Setup: `pip install -Ur requirements.txt` (Python 3.9 in CI; the local-dev guide in `plan/move-ingress/MIGRATION-PREREQ-LDE.md` uses a 3.10 `.venv`). The Fabric CLI binaries (`peer`, `configtxlator`, ...) must be on `PATH`; `BlockchainModule` fails at startup without them.

```shell
just local          # build + install the collection (ansible-galaxy collection build -f && install -f)
just lint           # flake8 ., ansible-lint, shellcheck tutorial/*.sh, yamllint .  (same as CI)
just docs           # cd docs && make clean && make all  -> docs/build
flake8 plugins/modules/peer.py   # lint a single file (E501 and W504 are ignored)
ansible-lint roles/fabric_console  # lint a single role
```

Playbooks use the *installed* collection (`hyperledger.fabric_ansible_collection.*`), so re-run `just local` after changing modules/roles before running anything from `tutorial/` or `examples/`.

Testing needs a live Console; there is no mocked module test suite.
- Tutorial test (the main end-to-end check): `.github/scripts/run-tests.sh` rewrites `tutorial/*-vars.yml` with connection details (`API_ENDPOINT`, `API_KEY`, `API_SECRET`, `K8S_NAMESPACE`, ... — sourced from `_cfg/console-env.sh` if present), then runs `build_network.sh build`, `join_network.sh join`, `deploy_smart_contract.sh`, and destroys everything. Run an individual step by running its playbook directly, e.g. `cd tutorial && ansible-playbook 09-create-channel.yml`.
- Local Kind flow: `.github/scripts/kind_with_nginx.sh` (cluster + ingress-nginx + CoreDNS override, writes `_cfg/k8s_context.yaml`) → `export KUBECONFIG=$PWD/_cfg/k8s_context.yaml` → `.github/scripts/deploy-console.sh` (writes `_cfg/console-env.sh`) → `run-tests.sh`. CI equivalent is the manual-dispatch `.github/workflows/fvtest.yml`.
- Integration tests: fill in `tests/integration/integration_config.yml`, then `ansible-test integration` (targets in `tests/integration/targets/it_*`; must run from the installed collection path).

## Architecture

- `plugins/modules/*.py` — one Ansible module per Fabric resource/action (`peer`, `certificate_authority`, `ordering_service_node`, `channel_*`, `approved_chaincode`, ...). Each `main()` builds an `argument_spec`, instantiates `BlockchainModule`, then: validate input → read current state → converge → return. Module docs live in `DOCUMENTATION`/`EXAMPLES`/`RETURN` strings and are extracted into `docs/` by `ansible-doc-extractor` (template: `docs/templates/module.rst.j2`).
- `plugins/module_utils/` — shared code. `module.py` defines `BlockchainModule` (subclass of `AnsibleModule`) which verifies required Python libs and the `peer`/`configtxlator` binaries, and sets up optional JSON logging via `IBP_ANSIBLE_LOG_FILENAME`. Domain helpers (`consoles.py`, `certificate_authorities.py`, `channel_utils.py`, `msp_utils.py`, `enrolled_identities.py`, ...) wrap the Console API and Fabric tooling.
- `roles/` — infrastructure roles for deploying the stack on Kubernetes/OpenShift: `fabric_operator_crds` + `fabric_console` (open-source stack) and `hlfsupport_crds` + `hlfsupport_console` (IBM Support), plus `ordering_organization` and `endorsing_organization`. Each role dispatches on `target` (`k8s` | `openshift`) into `tasks/k8s/` or `tasks/openshift/` and on `state` (`present`|`absent`) into `create.yml`/`delete.yml`; manifests are Jinja templates under `templates/{k8s,openshift}/`. Role docs are hand-written RST in `docs/source/roles/` (not generated).
- `tutorial/` — numbered playbooks (`01-…99-…`) driven by `build_network.sh` / `join_network.sh` / `deploy_smart_contract.sh`, with per-org vars files (`ordering-org-vars.yml`, `org1-vars.yml`, `org2-vars.yml`) and shared `common-vars.yml`. This doubles as the functional test suite, so changes to modules/roles should keep the tutorial passing. Chaincode is deployed as CCaaS (peers cannot build chaincode).
- `examples/` — standalone operational playbooks (HA CA, intermediate CA, admin cert rotation, fabproxy removal, Fabric v2 capability enablement, ...).
- `bin/`, `config/`, `builders/`, `_cfg/` — gitignored local Fabric binaries/config and Kind/Console connection files; don't commit them. The root `*.tar.gz` collection build artifact is also local.

## Ongoing work: ingress migration

`plan/move-ingress/` holds the plan to move from the deprecated ingress-nginx to Kubernetes Gateway API (staged: `MIGRATION-STEP-0..3.md`, roadmap in `MIGRATION-ROADMAP.md`, `PROMPTS.md` records the framing). Key premise: the ingress controller is a **prerequisite** of the collection, not something its roles provision (the Kind/nginx script in `.github/scripts` exists only for CI/local testing). Planned new variables (`ingress_type`, `expose_*`, domain vars) are to live in a shared internal role `network_domains`. Branches `step0-fix`, `step1-*` and `moveingressfac` track this work. Read the relevant `MIGRATION-STEP-N.md` before touching ingress-related roles, CI scripts or `run-tests.sh`.

## Conventions

- Files carry an `# SPDX-License-Identifier: Apache-2.0` header; YAML files start with `---` after it (yamllint enforced, line-length and comment rules disabled).
- `ansible-lint` skips `examples`, `tutorial`, `tests`, `.github`, `meta`, and ignores `fqcn-builtins`, `risky-file-permissions`, `var-naming[no-role-prefix]`; it runs in offline mode.
- `CONTRIBUTING.md` is partly stale (references `ibm/blockchain_platform` paths and a Poetry migration); prefer `justfile` and the CI workflow in `.github/workflows/main.yml` as the source of truth.
