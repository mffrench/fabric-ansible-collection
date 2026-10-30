# Review of the `move-ingress` plan

**Date:** 2026-10-12
**Scope:** every document in `plan/move-ingress/`, checked against the repository code (`.github/`, `roles/`, `tutorial/`, `plugins/`) and the official Envoy Gateway / Gateway API compatibility matrices.

This review is split by step. This document is the overview and index;
per-step detail (blocking issues, implementation mistakes, documentation
inconsistencies, decisions) lives in:

- [`REVIEW-MIGRATION-PLAN-STEP-0.md`](./REVIEW-MIGRATION-PLAN-STEP-0.md) — CI / LDE baseline (B4, B6)
- [`REVIEW-MIGRATION-PLAN-STEP-1.md`](./REVIEW-MIGRATION-PLAN-STEP-1.md) — `ingress_type` / `expose_*`, nginx expose-none (B2, B3)
- [`REVIEW-MIGRATION-PLAN-STEP-2.md`](./REVIEW-MIGRATION-PLAN-STEP-2.md) — Gateway API, console `HTTPRoute` (B5)
- [`REVIEW-MIGRATION-PLAN-STEP-3.md`](./REVIEW-MIGRATION-PLAN-STEP-3.md) — Gateway API, all components `TLSRoute` + native ports (B1)

---

## 1. Summary of the plan

| Document | Purpose |
|---|---|
| [`PRE-ANALYSIS.md`](./PRE-ANALYSIS.md) | Why move away from ingress-nginx, Fabric networking requirements (TLS passthrough, SNI, gRPC-Web), Gateway API vs Istio → **Gateway API** selected |
| [`GATEWAY-API-IMPLEMENTATIONS.md`](./GATEWAY-API-IMPLEMENTATIONS.md) | Comparison of Gateway API implementations → **Envoy Gateway** selected for CI / PoC |
| [`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) | Monolithic plan in 7 workstreams (W1 to W7) with code snippets |
| [`MIGRATION-ROADMAP.md`](./MIGRATION-ROADMAP.md) | Split into 4 independently shippable deliverables (Step 0 → 3) |
| [`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md) | Fix CI and local test execution — complete: B4 and B6 fixed 2026-10-21; `TEST_RUN_ID`, CI and LDE doc moved to [`REMAINING_TODO.md`](./REMAINING_TODO.md) — review: [Step 0](./REVIEW-MIGRATION-PLAN-STEP-0.md) |
| [`MIGRATION-STEP-1.md`](./MIGRATION-STEP-1.md) | `ingress_type` / `expose_*` variables, nginx "expose-none" scenario (port 443 added to Services, CoreDNS rewrites, in-cluster Ansible Job) — review: [Step 1](./REVIEW-MIGRATION-PLAN-STEP-1.md) |
| [`MIGRATION-STEP-2.md`](./MIGRATION-STEP-2.md) | First Gateway API implementation: console `HTTPRoute` only — review: [Step 2](./REVIEW-MIGRATION-PLAN-STEP-2.md) |
| [`MIGRATION-STEP-3.md`](./MIGRATION-STEP-3.md) | CA / peer / orderer `TLSRoute`s, 7054 / 7050 / 7051 listeners, `api_url` port changes — review: [Step 3](./REVIEW-MIGRATION-PLAN-STEP-3.md) |
| [`MIGRATION-PREREQ-LDE.md`](./MIGRATION-PREREQ-LDE.md) | Local development environment setup (macOS, Python 3.10 venv) |
| [`PROMPTS.md`](./PROMPTS.md) | History of the prompts that produced these documents |

### Step sequence

```
Step 0: CI + LDE fixed (nginx baseline)
  └─► Step 1: expose_* / ingress_type variables, nginx expose-none scenario
        └─► Step 2: Gateway API — console only (HTTPRoute)
              └─► Step 3: Gateway API — all components (TLSRoute) + native ports
```

### Overall assessment

**Strengths:** incremental approach, the nginx path is never broken, explicit
acceptance criteria per step, solid upfront analysis of Fabric's TLS
requirements.

**Weaknesses:** **5 issues genuinely block progress**. Three of them call
the design of Steps 1 and 3 into question; the other two are blocking but easy
to fix. Everything else is either an implementation mistake or a
documentation inconsistency that can be fixed along the way without changing
the architecture — see the per-step reviews linked above.

| # | Issue | Step | Nature | Effort | Status | Detail |
|---|---|---|---|---|---|---|
| B1 | Native ports cannot work without changing the operator | 3 (and 2) | Design | High | Open | [Step 3](./REVIEW-MIGRATION-PLAN-STEP-3.md#b1---native-ports-7051--7050--7054-cannot-work) |
| B2 | "Nothing exposed" is impossible on nginx as specified | 1 | Decision | — | **Decided** 2026-10-16 — planned, not implemented | [Step 1](./REVIEW-MIGRATION-PLAN-STEP-1.md#b2---nothing-exposed-through-nginx-is-impossible-as-specified) |
| B3 | A Service port 443 cannot serve several FQDNs | 1 | Design | Medium | **Planned** 2026-10-16 (per-endpoint Services) — not implemented | [Step 1](./REVIEW-MIGRATION-PLAN-STEP-1.md#b3---a-service-port-443-cannot-serve-several-fqdns) |
| B4 | `run-tests.sh` crashes (`PATCH_BG_PID`) | 0 | Bug | Trivial | **Fixed** 2026-10-21 (branch `step0-fix`) — full local run `exit=0` | [Step 0](./REVIEW-MIGRATION-PLAN-STEP-0.md#b4--run-testssh-crashes--fixed) |
| B5 | Gateway API CI cannot run (versions, KIND exposure) | 2 | Configuration | Low | Open | [Step 2](./REVIEW-MIGRATION-PLAN-STEP-2.md#b5---the-gateway-api-ci-cannot-run-as-written) |
| B6 | Tutorial chaincode cannot be installed (`docker build is disabled`) | 0 | Bug | Low | **Fixed** 2026-10-21 (branch `step0-fix`, chaincode as a service) — to validate with the team | [Step 0](./REVIEW-MIGRATION-PLAN-STEP-0.md#b6--the-tutorial-chaincode-cannot-be-installed--fixed) |

---

## 2. Documentation inconsistencies (general) 🟡

Step-specific documentation inconsistencies are listed in the corresponding
per-step review. The items below don't belong to a single step:

- "v1.3 = the version that promotes HTTPRoute to GA" is wrong: GA since v1.0.
- Outdated deprecation timeline: `galaxy.yml` is already at **2.1.3**; removing
  nginx is a breaking change → **3.0** (semver).
- `GATEWAY-API-IMPLEMENTATIONS.md`: "EG v1.3 — TLSRoute GA" is wrong; Istio
  1.22 and Contour 1.28 are outdated; the GKE row needs rechecking.

---

## 3. Structural improvements 🟢

1. **Single source of truth.** The steps point to `MIGRATION-PLAN §5.x`
   snippets that are now outdated (EG v1.3.0, `COREDNS_HOOK`,
   `kubectl config view`). Either make the steps self-contained and mark the
   PLAN as historical, or resynchronise it.
2. **"Decisions" section (ADR):** semantics of `expose_*`, port topology,
   target versions, single domain.
3. **Two spikes before coding Step 1:**
   - (a) `fabric-operator` reconciliation behaviour on a patched Service and on
     a deleted Ingress (drives B2 and B3, see [Step 1](./REVIEW-MIGRATION-PLAN-STEP-1.md));
   - (b) Envoy Gateway on KIND with TLS passthrough on 443, console included
     (validates B1 and B5, see [Step 2](./REVIEW-MIGRATION-PLAN-STEP-2.md) / [Step 3](./REVIEW-MIGRATION-PLAN-STEP-3.md)).
4. **Dynamically generated tests** based on the resources actually created.

---

## 4. Recommended order of action

| Order | Action | Unblocks |
|---|---|---|
| 1 | ~~Fix `PATCH_BG_PID` in `run-tests.sh`~~ and ~~run the tutorial chaincode as a service~~ (done 2026-10-21, full local run `exit=0`); the rest of Step 0 is in [`REMAINING_TODO.md`](./REMAINING_TODO.md) | B4, B6 — [Step 0](./REVIEW-MIGRATION-PLAN-STEP-0.md) |
| 2 | Decide the semantics of `expose_*: false` on nginx | B2 — [Step 1](./REVIEW-MIGRATION-PLAN-STEP-1.md) |
| 3 | Spikes (a) operator and (b) Envoy Gateway passthrough on 443 | B1, B3, B5 — [Step 1](./REVIEW-MIGRATION-PLAN-STEP-1.md), [Step 2](./REVIEW-MIGRATION-PLAN-STEP-2.md), [Step 3](./REVIEW-MIGRATION-PLAN-STEP-3.md) |
| 4 | Rewrite Step 1 around collection-owned Services | B3 — [Step 1](./REVIEW-MIGRATION-PLAN-STEP-1.md) |
| 5 | Realign Steps 2–3: EG v1.9 / Gateway API v1.6, KIND ≥ 1.33, `EnvoyProxy`, passthrough-443 topology | B1, B5 — [Step 2](./REVIEW-MIGRATION-PLAN-STEP-2.md), [Step 3](./REVIEW-MIGRATION-PLAN-STEP-3.md) |
| 6 | Fix the implementation-mistake items while implementing each step | — |
| 7 | Update `MIGRATION-PLAN.md`, `GATEWAY-API-IMPLEMENTATIONS.md` and the roadmap (§2) | — |
