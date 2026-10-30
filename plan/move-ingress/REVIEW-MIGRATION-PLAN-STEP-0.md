# Review of the `move-ingress` plan — Step 0

**Date:** 2026-10-12 (updated 2026-10-21: B4 and B6 fixed on branch `step0-fix`, full local run `exit=0`)
**Scope:** [`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md), checked against `.github/scripts/`, `.github/workflows/`, `tutorial/`, and [`MIGRATION-PREREQ-LDE.md`](./MIGRATION-PREREQ-LDE.md).
**See also:** [overview](./REVIEW-MIGRATION-PLAN.md)

---

## Blockers that are easy to fix 🔴

### B4 — `run-tests.sh` crashes — **fixed**

`run-tests.sh` contained `wait "${PATCH_BG_PID}"`, a variable that is never
defined. With `set -u` the script stopped right after `build_network.sh build`,
the cleanup trap destroyed everything, and `join_network.sh join` /
`deploy_smart_contract.sh` never ran. Confirmed on a local run on 2026-10-12:
`build_network.sh` completed successfully (playbooks 01 → 11), then
`PATCH_BG_PID: unbound variable`.

**Fix applied (2026-10-21, branch `step0-fix`):** the earlier fix had never
reached the repository: the line was still at `run-tests.sh:42` on `f2826ea`.
It is now removed from [`run-tests.sh`](../../.github/scripts/run-tests.sh)
(`bash -n` passes), and a full local run passes with B6 fixed: `exit=0`,
playbooks 01 → 23 then the teardown 97 → 99.

### B6 — the tutorial chaincode cannot be installed — **fixed**

Once B4 was fixed, playbook 19 failed:

```
could not build chaincode: docker build failed: docker build is disabled
```

`tutorial/fabcar@1.0.0.tgz` is a `node` package: the peer has to build it.
The console created by `tutorial/00-deploy-fabric-console.yml` lists no
`versions`, so it creates its default peer, `hyperledger/fabric-peer:2.5.8`
(checked on the KIND node). The operator's peer `core.yaml` (`v25`) declares
three external builders, `ibp-builder`, `k8s_builder` and `ccaas-builder`, but
the image only contains `/opt/hyperledger/ccaas_builder`. No builder accepts a
`node` package, so the peer falls back to its Docker build, which is
disabled. Changing `peer_version` does not help as long as the package is a
`node` package.

**Fix applied (2026-10-21, branch `step0-fix`):** the tutorial runs its
chaincode as a service (CCaaS), which the peer's `ccaas_builder` installs:

- `tutorial/ccaas/Dockerfile` builds the chaincode server from
  `fabcar@1.0.0.tgz` itself (its `fabric-shim` 2.2 has the `server` mode);
- `tutorial/deploy_chaincode_server.sh deploy` builds the image, pushes it to
  the KIND registry (`localhost:5000`), writes the CCaaS package
  `fabcar-ccaas@1.0.0.tgz` (`smart_contract_package` in `common-vars.yml`) and
  runs the server (Deployment and Service `fabcar-ccaas`, `CHAINCODE_ID` = the
  package ID);
- `deploy_smart_contract.sh` calls it before playbook 19, and
  `join_network.sh destroy` removes the server.

To validate with the team: the tutorial now builds an image, so the CI runner
must be able to push to the KIND registry that `kind_with_nginx.sh` creates.

Step 0 is marked complete. The items below that are still open, starting
with the `TEST_RUN_ID` stamping, are tracked in
[`REMAINING_TODO.md`](./REMAINING_TODO.md).

---

## Implementation mistakes (fixable without changing the design) 🟠

- `TEST_RUN_ID` / `SHORT_TEST_RUN_ID` stamping (sub-task 0.2) is not implemented.
- Diverging versions: CI used Python **3.9** while the LDE requires "exactly
  3.10" (**fixed 2026-10-22**: `fvtest.yml` uses 3.10, full local run with a
  fresh 3.10 venv `exit=0`); CI installs Fabric **2.4.7** while the LDE
  downloads **2.5.15** under a "Fabric 2.4.7" heading.
- `fvtest.yml` only triggers on `workflow_dispatch`; Step 1 refers to running
  "on every push".
- Sub-task 0.1 (inline playbook calling `fabric_console`) does not match the
  implementation (`tutorial/00-deploy-fabric-console.yml` with an inline `IBPConsole`).
- The LDE doc does not mention two prerequisites found during the local run:
  - the collection must be rebuilt and reinstalled from the repository
    (`ansible-galaxy collection build -f && ansible-galaxy collection install … -f`),
    otherwise an outdated copy in `~/.ansible/collections` is used (it rejected
    `arch: arm64`);
  - `ANSIBLE_PYTHON_INTERPRETER` must point to `.venv/bin/python`, otherwise
    Ansible discovers a system Python without the `kubernetes` library.
- The LDE doc suggests `brew install yq`, which installs mikefarah's `yq` — not
  compatible with the `yq -yi` syntax used by the scripts. Only the Python `yq`
  from `requirements.txt` works.
- `kind_with_nginx.sh` checked the registry with an undefined `${reg_name}`.
  When `kind-registry` already exists, the script tried to create it again,
  failed with exit code 125 and stopped before writing
  `_cfg/k8s_context.yaml`. **Fixed 2026-10-21** (`${CONTAINER_REGISTRY_NAME}`).
- Two runs at the same time against the same console break each other. Seen on
  2026-10-21: one run failed at playbook 06 (`requires that key [Group]
  /Channel/Consortiums/SampleConsortium be at version 0, but it is currently at
  version 1`), the other at playbook 09 (`No such file or directory: 'Org1
  Admin.json'`). Both use the same names and the same identity files in
  `tutorial/`. `TEST_RUN_ID` fixes the names, not the shared files: run one
  test at a time on a workstation.
- `ansible-galaxy collection build -f` from the repository root packs the
  untracked `.venv/`, `bin/`, `builders/` and `config/` directories
  (`galaxy.yml` has no `build_ignore`): the tarball reached 188 MB. Add a
  `build_ignore` list.

---

## Recommended order of action for this step

| Order | Action | Unblocks |
|---|---|---|
| 1 | ~~Fix `PATCH_BG_PID` in `run-tests.sh`~~ and ~~run the tutorial chaincode as a service~~ (done 2026-10-21, full local run `exit=0`) | B4, B6 |
| 2 | Implement `TEST_RUN_ID` stamping | Repeat and parallel runs |
| 3 | Run `fvtest.yml` on GitHub Actions (the runner must push the chaincode image to the KIND registry) | CI baseline |
| 4 | Align the versions and the LDE doc (Python, Fabric, `yq`, `ANSIBLE_PYTHON_INTERPRETER`, health path, `build_ignore`) | Clean local setup |

Items 2 to 4 are tracked in [`REMAINING_TODO.md`](./REMAINING_TODO.md).

See the [overview](./REVIEW-MIGRATION-PLAN.md#7-recommended-order-of-action) for the full cross-step sequencing.
