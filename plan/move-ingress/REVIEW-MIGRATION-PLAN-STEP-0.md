# Review of the `move-ingress` plan — Step 0

**Date:** 2026-10-12
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

**Fix applied:** the line was removed from
[`run-tests.sh`](../../.github/scripts/run-tests.sh) (`bash -n` passes). A full
re-run (`exit=0`, playbooks 17 and 19–23 executed) is still needed to close
this item.

Step 0 is still marked `complete` although the `TEST_RUN_ID` stamping (below)
is not implemented.

---

## Implementation mistakes (fixable without changing the design) 🟠

- `TEST_RUN_ID` / `SHORT_TEST_RUN_ID` stamping (sub-task 0.2) is not implemented.
- Diverging versions: CI uses Python **3.9** while the LDE requires "exactly
  3.10"; CI installs Fabric **2.4.7** while the LDE downloads **2.5.15** under a
  "Fabric 2.4.7" heading.
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

---

## Recommended order of action for this step

| Order | Action | Unblocks |
|---|---|---|
| 1 | ~~Fix `PATCH_BG_PID` in `run-tests.sh`~~ (done) — re-run the full test suite, then implement `TEST_RUN_ID` stamping | B4 — actual completion of Step 0 |

See the [overview](./REVIEW-MIGRATION-PLAN.md#7-recommended-order-of-action) for the full cross-step sequencing.
