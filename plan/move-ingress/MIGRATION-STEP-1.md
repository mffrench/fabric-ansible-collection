# Step 1 — Expose Options with NGINX Ingress Controller

**Roadmap reference:** [`MIGRATION-ROADMAP.md`](./MIGRATION-ROADMAP.md) — Step 1
**Plan reference:** [`MIGRATION-PLAN.md`](./MIGRATION-PLAN.md) — W1, partial W5, partial W3, partial W7 (W4 moved to Step 2)
**Prerequisite:** [`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md) (Baseline CI & Test Runner Fixes)
**Diagrams:** [`SCENARIOS-MERMAID.md`](./SCENARIOS-MERMAID.md) (scenarios A, B, C)
**Status:** `[ ] pending`

---

## Overview

This deliverable builds on the working baseline established in **Step 0** ([`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md)). It introduces all new Ansible variables (`ingress_type`, `expose_*`) and makes the collection's console wait-logic aware of the `expose_console` flag, while the **nginx ingress controller remains the only supported and tested ingress backend**. No Gateway API resources, templates, or CRDs are introduced yet.

The primary goals of this step are:
1. Establish the stable variable schema that Steps 2 and 3 will build on.
2. Prove there is no regression in the working nginx-backed test suite (the all-exposed baseline from Step 0).
3. Validate the extreme opposite scenario: a deployment where nothing is exposed
   through the NGINX ingress controller (`expose_console: false`,
   `expose_ca: false`, `expose_peer: false`, `expose_orderer: false`).

**Domain and URL design.** This step follows
[`URL-MANAGEMENT-NEW.md`](./URL-MANAGEMENT-NEW.md) (decisions D1–D5, checks
of 2026-10-16). How URLs are built today is in
[`URL-MANAGEMENT-EXISTING.md`](./URL-MANAGEMENT-EXISTING.md). In short:
`exposed_domain` (formerly `console_domain`) builds the console URL;
`hlf_network_domain` builds the node FQDNs; when it equals the cluster
domain, node FQDNs are Kubernetes Service FQDNs and need no CoreDNS rewrite.
The three scenarios this step handles are recalled just below, each with
its diagram.

---

<a id="scenarios"></a>
## Scenarios handled in Step 1

Step 1 implements and tests three scenarios of
[`URL-MANAGEMENT-NEW.md`](./URL-MANAGEMENT-NEW.md) §4. Each one has a diagram
in [`SCENARIOS-MERMAID.md`](./SCENARIOS-MERMAID.md).

| Scenario | In one sentence | Variables | CI leg | Diagram |
|---|---|---|---|---|
| **A** — everything exposed, non-Kubernetes FQDNs (default) | Today's behaviour. Step 1 must not change it. | none | `expose-all` | [Scenario A](./SCENARIOS-MERMAID.md#scenario-a) |
| **B** — nothing exposed, cluster-local HLF domain | **The Step 1 target.** Node FQDNs are Kubernetes Service FQDNs, CoreDNS is not touched, the console keeps its public name but is not served. | `hlf_network_domain: cluster.local`, every `expose_*: false` (`exposed_domain` free) | `expose-none-internal` | [Scenario B](./SCENARIOS-MERMAID.md#scenario-b) |
| **C** — nothing exposed, non-Kubernetes FQDNs | Compatibility: node FQDNs are not Kubernetes names (the same names as A); they are reached without nginx through one CoreDNS rewrite per endpoint type. | every `expose_*: false` | `expose-none` | [Scenario C](./SCENARIOS-MERMAID.md#scenario-c) |

Out of scope: **D** (nodes exposed under their own domain) is Step 3, and
partial exposure (some components exposed, others not) has no CI leg.

Each sub-task below starts with the scenarios it touches.

> PRE-ANALYSIS.md §2.4.1 also uses the letters A, B, C, for another question:
> where the Ansible control machine runs. In this file the letters always
> mean the scenarios above.

---

<a id="how-to-check"></a>
## How to implement and check Step 1

**One sub-task = one PR.** Each sub-task has its  own pull
request, which contains only that sub-task. Sub-tasks are numbered in
implementation order (see the [sub-task map](#sub-task-map)). A sub-task is
done, and its PR can be merged, when:

1. every item of its **Todo list** is ticked;
2. its automatic checks pass (`ansible-lint`, `yamllint`, `bash -n`, tests);
3. a person has run its **✋ check** on the local KIND cluster, and every
   step gives the expected result.

A sub-task starts once the sub-tasks in its "Needs" column are merged.
Sub-tasks that don't need each other and don't touch the same files can be
worked on in parallel, in separate PRs: see
[`MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md`](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md)
(dependencies, files changed by each sub-task, merge-conflict risk, waves).
When a check fails, fix it inside the same sub-task, then rerun the **whole**
check, not only the line that failed. Each  check gives the commands, the expected result,
and, where it matters, a **negative check**: something broken on purpose that
must make the check fail.

### Before you start

- The local environment of [`MIGRATION-PREREQ-LDE.md`](./MIGRATION-PREREQ-LDE.md)
  works: `.github/scripts/run-tests.sh` exits 0 on a fresh KIND cluster
  (Step 0 acceptance).
- **One test run at a time** on the cluster. Two runs at once share the
  same organization names and break each other (Step 0 finding).
- `run-tests.sh` patches `tutorial/common-vars.yml` and the org vars files in
  place. Before each commit, read `git diff tutorial/` and keep only the
  intended changes.

### Check environment

Every  check runs from the repository root, in a shell prepared like
this:

```bash
source .venv/bin/activate
export KUBECONFIG="$PWD/_cfg/k8s_context.yaml"
export ANSIBLE_PYTHON_INTERPRETER="$(command -v python)"
export PATH="$PWD/bin:$PATH"            # Fabric CLI (peer, osnadmin), used by the modules
source _cfg/console-env.sh              # API_ENDPOINT, API_KEY, API_SECRET: never echo them
NS=default
DOMAIN_A="$(sh .github/scripts/get-host-ip.sh | tr -s '.' '-').nip.io"    # e.g. 127-0-0-1.nip.io
SEL=app.kubernetes.io/managed-by=fabric-ansible-collection                # Services of sub-task 1.6
BASE=origin/move-ingress-plan  #changer si besoin la branche target
# Run a command in a throwaway pod: in-cluster DNS, Services, no nginx
incluster() {
  kubectl run "chk-$RANDOM" -n "$NS" --image=curlimages/curl:8.10.1 \
    --restart=Never --rm -i --quiet --command -- "$@"
}
# Same with busybox, for DNS lookups
indns() {
  kubectl run "dns-$RANDOM" -n "$NS" --image=busybox:1.36.1 \
    --restart=Never --rm -i --quiet --command -- nslookup "$@"
}
```

Commands the checks refer to by name:

| Name | Command | Expected |
|---|---|---|
| **Rebuild** (after any change under `roles/` or `plugins/`) | `ansible-galaxy collection build -f --output-path /tmp/fac && ansible-galaxy collection install -f /tmp/fac/hyperledger-fabric_ansible_collection-*.tar.gz` | `... was installed successfully` |
| **Regression run** (scenario A) | `.github/scripts/run-tests.sh` | exit 0, as at the end of Step 0 |
| **Scenario C run** (from 1.3) | `EXPOSED_DOMAIN="$DOMAIN_A" EXPOSE_CA=false EXPOSE_PEER=false EXPOSE_ORDERER=false KEEP_NETWORK=true .github/scripts/run-tests.sh` | exit 0, network kept for inspection |
| **Destroy** (from 1.3) | `RUN_TESTS_MODE=destroy .github/scripts/run-tests.sh`, with the same `EXPOSE_*` as the run | exit 0; `kubectl get ibpca,ibppeer,ibporderer -n "$NS"` finds nothing |
| **Fresh console** | `.github/scripts/undeploy-console.sh && .github/scripts/deploy-console.sh` | the console URL is printed |

**What a laptop can run.** The laptop reaches the cluster only through nginx
(KIND host port 443).
- Scenario B organization playbooks cannot run from the laptop: node names
  under `default.svc.cluster.local` don't resolve there (finding F4). B runs
  end to end for the first time in 1.9, inside the cluster.
- Scenario C runs from the laptop as long as the console and the node
  Ingresses are still served by nginx. So, before 1.9, the checks use C
  with `EXPOSE_CONSOLE` left at `true`. They test the new Services from
  inside the cluster, through the very names scenario B uses.

### Sub-task map

| # | Sub-task | Scenarios | Needs |
|---|---|---|---|
| [1.1](#subtask-1-1) | Shared role `network_domains` | A B C | — |
| [1.2](#subtask-1-2) | Validation tests for the domain rules | A B C | 1.1 |
| [1.3](#subtask-1-3) | `run-tests.sh` / `deploy-console.sh` variable injection | A B C | 1.1 |
| [1.4](#subtask-1-4) | Console wait without its Ingress | B C (A unchanged) | 1.3 |
| [1.5](#subtask-1-5) | `IBPConsole` fields | B C (A unchanged) | 1.4 |
| [1.6](#subtask-1-6) | One Service per endpoint | B C (A unchanged) | 1.3 |
| [1.7](#subtask-1-7) | Opt-in node Ingress neutralization | B C | 1.6 |
| [1.8](#subtask-1-8) | CoreDNS endpoint rewrites | C (A, B unchanged) | 1.6 |
| [1.9](#subtask-1-9) | CI legs and in-cluster Job | A B C | 1.3 to 1.8 |
| [1.10](#subtask-1-10) | Reachability assertions | B C | 1.9 |
| [1.11](#subtask-1-11) | Tutorial: everything exposed | A | 1.1 |
| [1.12](#subtask-1-12) | Tutorial: nothing exposed | B | 1.9 |


---

<a id="subtask-1-1"></a>
## Sub-task 1.1 — Shared role `network_domains` (variables, domains, facts)

**Scenarios:** [A](./SCENARIOS-MERMAID.md#scenario-a), [B](./SCENARIOS-MERMAID.md#scenario-b), [C](./SCENARIOS-MERMAID.md#scenario-c).

**Design reference:** [`URL-MANAGEMENT-NEW.md`](./URL-MANAGEMENT-NEW.md)
§3 (variables), §6 (scope), §10 (decisions D1–D5). How URLs are built today:
[`URL-MANAGEMENT-EXISTING.md`](./URL-MANAGEMENT-EXISTING.md).

**Intent:** Introduce every new variable with safe defaults, so all existing
playbooks keep working unchanged, and compute the domain facts **once**, in
one place reachable from every role. This replaces the earlier
`fabric_operator_crds/tasks/k8s/set_facts.yml` design, which could not work
(REVIEW-MIGRATION-PLAN-STEP-1.md, "Variables and facts"):

- defaults of `fabric_operator_crds` are not visible from `fabric_console`,
  `endorsing_organization` or `ordering_organization` (separate playbooks);
- `include_tasks: set_facts.yml` from `hlfsupport_console` looks for the file
  in its own role;
- `ingress_domain_is_cluster_local` was used in the organization roles
  without ever being defined there;
- `cluster_domain` discovery through `kubectl exec deployment/coredns -- awk`
  always fails (distroless image, `dnsPolicy: Default`, needs `pods/exec`).

The logic therefore lives in a new internal role, `network_domains`, that
every role calls with `include_role` (`public: true`).

**Variables** (defaults in `roles/network_domains/defaults/main.yml`):

| Variable | Meaning | Default |
|---|---|---|
| `ingress_type` | Ingress backend; only `nginx` in Step 1 | `nginx` |
| `expose_console`, `expose_ca`, `expose_peer`, `expose_orderer` | Component reachable from outside the cluster | `true` |
| `expose_peer_operations`, `expose_orderer_operations`, `expose_grpcweb` | Sub-flags, consumed in Step 3 | `false` |
| `exposed_domain` | Domain users see: console URL and console TLS SAN, even when not exposed. **Replaces `ingress_domain`**, which no task or template ever used. | `""` → `console_domain` |
| `console_domain` | **Deprecated alias** of `exposed_domain` (D5), still mandatory-or-`exposed_domain` | — |
| `hlf_network_domain` | Domain of the HLF nodes. `= cluster_domain`: node FQDNs are Kubernetes Service FQDNs. Otherwise: previous flat FQDNs. | `""` → `exposed_domain` (D2) |
| `cluster_domain` | Kubernetes cluster DNS zone | `""` → read from `kube-system/coredns` |
| `unexposed_ingress_class` | Ingress class no controller serves (D3) | `none` |
| `neutralize_node_ingresses` | Also apply it to unexposed node CRs (D4, sub-task 1.7) | `false` |
| `gateway_class_name`, `ingress_ca_port`, `ingress_grpc_orderer_port`, `ingress_grpc_peer_port` | Gateway API settings, inert until Step 2 | `fabric-envoy-gateway`, 7054, 7050, 7051 |

Caller-provided: `network_domains_namespace` (namespace of the console and of
every node), `network_domains_console_name`.

**Facts** (computed; names distinct from the inputs, so an input passed with
`-e` never hides a computed value):

| Fact | Value |
|---|---|
| `network_domains_exposed_domain` | `exposed_domain` or `console_domain`, lowercased, no trailing dot |
| `network_domains_hlf_network_domain` | `hlf_network_domain` or the exposed domain |
| `network_domains_cluster_domain` | resolved cluster domain (`""` when not needed, see below) |
| `hlf_network_domain_is_cluster_local` | `hlf_network_domain == cluster_domain` (D1) |
| `hlf_node_domain` | `<namespace>.svc.<cluster_domain>` if cluster-local, else the HLF network domain. It is the value of the node CRs' `spec.domain`. |
| `console_url` | `https://<namespace>-<console_name>-console.<exposed_domain>` |
| `console_incluster_url` | `https://<console_name>.<namespace>.svc.<cluster_domain>:3000` |

**Validation (fail fast):**

| # | Rule |
|---|---|
| — | `exposed_domain` and `console_domain`, when both set, are equal; at least one is set |
| V1 | `exposed_domain` is neither the cluster domain nor inside it |
| V2 | `hlf_network_domain` is the cluster domain or outside it; a sub-zone (`default.svc.cluster.local`) is rejected, naming the cluster domain as the value to use |
| V3 | cluster-local `hlf_network_domain` ⇒ `expose_ca`, `expose_peer`, `expose_orderer` all `false` (`expose_console` free) |
| V4 | `<namespace>-<console_name>-console` ≤ 63 characters |
| V5 | after each node module call, every returned URL host ends with `.` + `hlf_node_domain` (`tasks_from: verify_urls`, sub-task 1.6) |

**Resolution of `cluster_domain`.** The cluster domain is read from the
Corefile in the `kube-system/coredns` ConfigMap, the source of truth CoreDNS
itself uses. Its `kubernetes` plugin line lists the cluster domain, then the
reverse zones:

```
kubernetes cluster.local in-addr.arpa ip6.arpa {
```

This only needs `get` on one ConfigMap through `kubernetes.core.k8s_info`. It
runs only when the cluster domain matters: a component is unexposed, the HLF
network domain differs from the exposed one, `cluster_domain` is set, or the
caller asks for it (`network_domains_resolve_cluster_domain`). With the
defaults (everything exposed, one domain) the role needs **no cluster
access**, so the REST-only path of the organization roles is unchanged.

| Lookup result | `cluster_domain` set by the user | Outcome |
|---|---|---|
| discovered `D` | empty (default) | `D` |
| discovered `D` | `D` | `D` (double-checked) |
| discovered `D` | `X ≠ D` | **fail**: names both values |
| not discoverable | `X` | **warning**: could not verify, trusting `X` |
| not discoverable | empty | **fail**: asks the user to set `cluster_domain` |

"Not discoverable" covers an absent or unreadable ConfigMap, or one without a
`kubernetes` line: GKE with kube-dns, OpenShift (`openshift-dns/dns-default`),
CoreDNS under another name, restricted RBAC. Comparisons are
case-insensitive and ignore a trailing dot. The role never guesses
`cluster.local`.

**Prototype.** The full role is in
[`.url_management_new_checks/network_domains/roles/network_domains/`](./.url_management_new_checks/network_domains/roles/network_domains/)
(`defaults/main.yml`, `tasks/main.yml`, `tasks/cluster_domain.yml`,
`tasks/verify_urls.yml`). On 2026-10-16 it passed `yamllint` and
`ansible-lint` (production profile), and all 13 cases of
`test.yml` against the live KIND CoreDNS ConfigMap (scenarios A, B, C, D;
alias and its conflict; V1, V2, V3; cluster-domain match, mismatch, and
case/trailing dot), plus `test_extra_vars.yml` with an empty
`-e cluster_domain=`. Core of `tasks/main.yml`:

```yaml
- name: Set the HLF network facts
  ansible.builtin.set_fact:
    hlf_network_domain_is_cluster_local: >-
      {{ network_domains_cluster_domain != ''
         and network_domains_hlf_network_domain == network_domains_cluster_domain }}

- name: Set the HLF node domain
  ansible.builtin.set_fact:
    hlf_node_domain: >-
      {{ (network_domains_namespace ~ '.svc.' ~ network_domains_cluster_domain)
         if hlf_network_domain_is_cluster_local | bool
         else network_domains_hlf_network_domain }}
```

**Calls** (each role, at the top of `tasks/create.yml` and `tasks/delete.yml`,
before any task that branches on `expose_*` or a domain fact):

```yaml
- name: Compute the network domains
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.network_domains
    public: true
  vars:
    network_domains_namespace: "{{ project | default(namespace) }}"  # organization roles: "{{ k8s_namespace | default('') }}"
    network_domains_console_name: "{{ console_name }}"               # console in hlfsupport_console; omitted in the organization roles
```

| Caller | Uses |
|---|---|
| `fabric_console`, `hlfsupport_console` (+ `tutorial/00-deploy-fabric-console.yml`, what CI runs) | `exposed_domain`, `hlf_node_domain`, `console_url`, `console_incluster_url` (sub-tasks 1.4, 1.5) |
| `endorsing_organization`, `ordering_organization` | `hlf_node_domain`, `hlf_network_domain_is_cluster_local`, `verify_urls` (sub-task 1.6) |
| `fabric_operator_crds` | nothing in Step 1. Its unused `ingress_domain` default is removed. |

**Expected outcomes:**
- `roles/network_domains/` exists, with the variables and facts above.
- Every role listed above includes it; no role reads another role's
  defaults.
- With no new variable set, a console role computes `hlf_node_domain =
  console_domain`, prints the `console_domain` deprecation notice, and reads
  nothing from the cluster.
- With no new variable set, an organization role does not fail: it knows
  neither `console_domain` (a console variable) nor, outside the tutorial,
  `k8s_namespace`. The domain facts stay empty and nothing is read from the
  cluster. With unexposed components it needs `k8s_namespace`, and
  `exposed_domain` (scenario C) or `hlf_network_domain` (scenario B).
- `ansible-lint` and `yamllint` pass on all modified files.
- All existing tests pass without setting any new variable.

**Todo list:**
- [ ] Copy the prototype into `roles/network_domains/` and add
  `meta/main.yml` (internal role, no dependencies).
- [ ] Include it in `roles/fabric_console/tasks/create.yml`,
  `roles/hlfsupport_console/tasks/create.yml`, both organization roles'
  `create.yml` and `delete.yml`, and `tutorial/00-deploy-fabric-console.yml`.
- [ ] Replace the `console_domain not specified` checks in
  `roles/fabric_console/tasks/create.yml:10-13` and
  `roles/hlfsupport_console/tasks/create.yml:10-13` by the role's own check.
- [ ] Remove `ingress_domain: localho.st` from
  `roles/fabric_operator_crds/defaults/main.yml:46`.
- [ ] Add `exposed_domain` and `hlf_network_domain` to
  `tutorial/common-vars.yml`, commented out, with their defaults.
- [ ] Run `ansible-lint` and `yamllint` on all modified and new files.

**Relevant context:**
- The defaults file holds no logic; all logic is in the tasks.
- An organization role does not pass `network_domains_console_name`: the
  role then requires the exposed domain and the namespace only when they
  are used (unexposed components, or a domain variable set). Otherwise an
  existing user of `endorsing_organization` or `ordering_organization`,
  who never sets `console_domain` or `k8s_namespace`, would fail.
- `public: true` exposes the role's defaults to the caller, so a caller can
  use `expose_*` directly after the include.
- In ansible-core 2.18, a templated `set_fact: "{{ dict }}"` is a silent
  no-op (found while testing). The role never uses that form.
- Port variables `ingress_*_port` are Gateway API listener ports for Step 2,
  **not** the native target ports of sub-task 1.6.
- The identity that runs the playbooks needs `get` on
  `kube-system/configmaps/coredns` for the `cluster_domain` lookup. Without
  it, `cluster_domain` must be set by hand. The in-cluster CI Job gets it
  through its own Role (sub-task 1.9).
- The Gateway API RBAC rules (`gateway.networking.k8s.io`), sub-task 1.2
  in the numbering before 2026-10-21, moved to
  [`MIGRATION-STEP-2.md`](./MIGRATION-STEP-2.md) sub-task 2.0 on 2026-10-16:
  Step 1 introduces no Gateway API object (acceptance criterion 9).

### ✋  check 1.1

**Proves:** the role computes the right facts in A, B and C, reads the
cluster only when it has to, and stops on a bad combination.

1. `ansible-lint roles/network_domains && yamllint roles/network_domains`:
   no error. Then **Rebuild**.
2. Write a throwaway playbook that prints the facts:
   ```bash
   mkdir -p /tmp/check11
   cat > /tmp/check11/nd-check.yml <<'EOF'
   - hosts: localhost
     gather_facts: false
     tasks:
       - ansible.builtin.include_role:
           name: hyperledger.fabric_ansible_collection.network_domains
           public: true
         vars:
           network_domains_namespace: "{{ nd_ns | default('default') }}"
           network_domains_console_name: "{{ nd_console | default('hlf-console') }}"
       - ansible.builtin.debug:
           msg:
             cluster_local: "{{ hlf_network_domain_is_cluster_local }}"
             cluster_domain: "{{ network_domains_cluster_domain }}"
             hlf_node_domain: "{{ hlf_node_domain }}"
             console_url: "{{ console_url | default('') }}"
             console_incluster_url: "{{ console_incluster_url | default('') }}"
   EOF
   nd() { ansible-playbook -i localhost, -c local /tmp/check11/nd-check.yml "$@"; }
   ```
3. Scenario A, **with no cluster at all**:
   ```bash
   KUBECONFIG=/dev/null nd -e console_domain=127-0-0-1.nip.io
   ```
   Expected: success even without a kubeconfig (so nothing is read from the
   cluster); the `console_domain` deprecation notice; `cluster_local: false`,
   `cluster_domain: ""`, `hlf_node_domain: 127-0-0-1.nip.io`,
   `console_url: https://default-hlf-console-console.127-0-0-1.nip.io`.
4. Scenario B:
   ```bash
   nd -e exposed_domain=example.com -e hlf_network_domain=cluster.local \
      -e expose_console=false -e expose_ca=false -e expose_peer=false -e expose_orderer=false
   ```
   Expected: `cluster_local: true`, `cluster_domain: cluster.local`,
   `hlf_node_domain: default.svc.cluster.local`,
   `console_url: https://default-hlf-console-console.example.com`,
   `console_incluster_url: https://hlf-console.default.svc.cluster.local:3000`.
5. Scenario C:
   ```bash
   nd -e console_domain=127-0-0-1.nip.io -e expose_ca=false -e expose_peer=false -e expose_orderer=false
   ```
   Expected: `cluster_local: false`, `cluster_domain: cluster.local` (read
   this time, because nodes are unexposed), `hlf_node_domain: 127-0-0-1.nip.io`.
6. The cluster domain is the one CoreDNS really serves:
   ```bash
   kubectl -n kube-system get cm coredns -o jsonpath='{.data.Corefile}' | grep -E '^\s*kubernetes '
   ```
   Expected: `kubernetes cluster.local in-addr.arpa ip6.arpa {`, the same
   value as `cluster_domain` in steps 4 and 5.
7. Negative checks. Each one must **fail** with the role's own message, not a
   template error:
   - step 4 plus `-e expose_peer=true`: V3, naming `expose_peer`;
   - step 4 with `-e hlf_network_domain=default.svc.cluster.local`: V2,
     naming `cluster.local` as the value to use;
   - `-e exposed_domain=a.example.com -e console_domain=b.example.com`: alias
     conflict;
   - step 5 plus `-e cluster_domain=corp.internal`: mismatch, naming both
     values;
   - `KUBECONFIG=/dev/null nd`: no domain for a console role.
8. Organization roles (`-e nd_console=`: no console name, as in
   `endorsing_organization` and `ordering_organization`):
   - `KUBECONFIG=/dev/null nd -e nd_console= -e nd_ns=`: **passes**, every
     domain fact empty, no cluster read (scenario A, no new variable);
   - `nd -e nd_console= -e hlf_network_domain=cluster.local -e expose_ca=false -e expose_peer=false -e expose_orderer=false`:
     passes, `hlf_node_domain: default.svc.cluster.local` (scenario B);
   - `nd -e nd_console= -e expose_ca=false -e expose_peer=false -e expose_orderer=false`:
     **fails**, asking for `exposed_domain` or `hlf_network_domain`;
   - the scenario B line with `-e nd_ns=`: **fails**, asking for `k8s_namespace`.
9. **Regression run**: exit 0.
10. **Changed files vs the merge-conflict analysis.**
    ```bash
    git fetch origin && git diff --name-only "$BASE"...HEAD
    ```
    Expected: only the files of the 1.1 row of the
    [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
    No other sub-task runs in wave 1, so a file that is not listed
    conflicts with nothing: add it to the 1.1 row of the table.


---

<a id="subtask-1-2"></a>
## Sub-task 1.2 — Validation tests for the domain rules

**Scenarios:** [A](./SCENARIOS-MERMAID.md#scenario-a), [B](./SCENARIOS-MERMAID.md#scenario-b), [C](./SCENARIOS-MERMAID.md#scenario-c).

**Intent:** Freeze the behaviour of `network_domains` with automated tests,
so the rules of sub-task 1.1 (alias, V1–V4, cluster-domain reconciliation,
D1) cannot regress. The rules themselves live in the role; this sub-task only
adds the tests and their CI hook.

| `exposed_domain` | `hlf_network_domain` | `expose_ca/peer/orderer` | Expected |
|---|---|---|---|
| `127-0-0-1.nip.io` (or via `console_domain`) | unset | `true` | pass: `hlf_node_domain = 127-0-0-1.nip.io`, no cluster read (scenario A) |
| `example.com` | `cluster.local` | `false` | pass: `hlf_node_domain = default.svc.cluster.local`, cluster-local, **no CoreDNS rewrite** (scenario B) |
| `example.com` | `cluster.local` | `false`, console exposed | pass (console may be exposed) |
| `example.com` | `cluster.local` | any `true` | **fail** V3, naming the flags |
| `example.com` | `default.svc.cluster.local` | any | **fail** V2, naming `cluster.local` |
| `svc.cluster.local` | any | any | **fail** V1 |
| `127-0-0-1.nip.io` | unset | `false` | pass: previous flat FQDNs, rewrites needed (scenario C) |
| `example.com` | `fabric.example.com` | `true` | pass: `hlf_node_domain = fabric.example.com` (scenario D) |
| `a.example.com` + `console_domain: b.example.com` | — | — | **fail**: alias conflict |
| — | — | `cluster_domain: corp.internal` on a `cluster.local` cluster | **fail**: mismatch |

**Expected outcomes:**
- The table above runs as one test playbook against a KIND cluster (it needs
  the real `kube-system/coredns` ConfigMap) and in CI (`expose-all` leg, no
  extra cluster).
- Each failing case fails with the role's message, not a template error.

**Todo list:**
- [ ] Port the prototype tests (`test.yml`, `test_case.yml`,
  `test_extra_vars.yml`; 13 cases, 2026-10-16: all pass) to the collection's
  test tree: `tests/network_domains/`, run by `tests/network_domains/run.sh`.
  The playbook fails when a case fails, checks the role's message of each
  failing case, and also covers V4 and the organization-role cases of
  sub-task 1.1.
- [ ] Add a "network_domains rules" step to `fvtest.yml`, before
  `run-tests.sh`.
- [ ] Add a case with the ConfigMap unreadable (a ServiceAccount without
  `get configmaps` in `kube-system`): set `cluster_domain` → warning; unset →
  failure.

**Relevant context:**
- `expose_peer_operations`, `expose_orderer_operations` and `expose_grpcweb`
  are sub-flags of `expose_peer` / `expose_orderer` and are not checked by V3.

### ✋  check 1.2

**Proves:** the rule tests run, cover every case of the table, and catch a
broken rule.

1. **Rebuild**, then run the tests:
   ```bash
   tests/network_domains/run.sh
   ```
   Expected: 20 `PASS` lines (every row of the table above, V4, the four
   organization-role cases of 1.1, the two unreadable-ConfigMap cases), then
   `All 20 cases passed.` and `-e inputs did not hide the computed facts.`;
   `failed=0`, exit 0. The unreadable-ConfigMap failure shows `403`
   (`Forbidden`): the test really ran with the restricted ServiceAccount.
   `kubectl get sa network-domains-test-noread -n default` then finds
   nothing (the test deletes it).
2. Break a rule on purpose: comment out the V3 assertion in
   `roles/network_domains/tasks/main.yml`, **Rebuild**, rerun step 1.
   Expected: the V3 case fails, every other case still passes, and
   `run.sh` exits non-zero (`1 case(s) failed: V3, ...`). Undo the edit
   (`git diff roles/` empty), **Rebuild**, rerun: all pass again.
3. The CI hook is in place:
   ```bash
   grep -n -B2 -A4 'network_domains rules' .github/workflows/fvtest.yml
   ```
   Expected: the step runs before `run-tests.sh`.
4. **Changed files vs the merge-conflict analysis.**
   ```bash
   git fetch origin && git diff --name-only "$BASE"...HEAD
   ```
   Expected: only the files of the 1.2 row of the
   [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
   If a file is not listed, check that it is not changed by the
   sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 2: 1.3, 1.11.
   Look at their row of the table and at their open PR
   (`gh pr diff <PR number> --name-only`). If one of them changes it,
   raise a warning in the PR description: 1.2 must be merged before
   or after that sub-task (for example 1.3), not at the same time.
   In both cases, add the file to the 1.2 row of the table.


---

<a id="subtask-1-3"></a>
## Sub-task 1.3 — `run-tests.sh` variable injection for Step 1 flags

**Scenarios:** [A](./SCENARIOS-MERMAID.md#scenario-a), [B](./SCENARIOS-MERMAID.md#scenario-b), [C](./SCENARIOS-MERMAID.md#scenario-c) (it selects the scenario of every later check).

**Intent:** Extend the stabilized `run-tests.sh` (fixed in Step 0) to inject the newly introduced `INGRESS_TYPE` and `EXPOSE_*` variables into `tutorial/common-vars.yml`.

It comes right after the shared role because every later  check uses it
to pick a scenario: `EXPOSE_*=false .github/scripts/run-tests.sh` instead of
editing vars files by hand.

*(Note: Baseline fixes for positional argument crashes, `TEST_RUN_ID` stamping, and connection variable injection are implemented in [`MIGRATION-STEP-0.md`](./MIGRATION-STEP-0.md) Sub-task 0.2).*

**Expected outcomes:**
- `run-tests.sh` reads `INGRESS_TYPE` (default: `nginx`) and all `EXPOSE_*` flags from the environment (defaulting to safe values).
- `ingress_type` and `expose_*` flags are patched into `common-vars.yml` via `yq` prior to playbook execution.
- It also patches `exposed_domain`, `hlf_network_domain` and `cluster_domain`
  from `EXPOSED_DOMAIN`, `HLF_NETWORK_DOMAIN` and `CLUSTER_DOMAIN`, **only
  when set**. Unset, the `network_domains` defaults apply (`console_domain`
  alias, no cluster read), so the `expose-all` leg is unchanged.
  `NEUTRALIZE_NODE_INGRESSES` (sub-task 1.7) follows the same rule.
- These go to `common-vars.yml`, not `-e`: every playbook (console and
  organizations) then reads the same values (URL-MANAGEMENT-NEW.md §6.3).
- `deploy-console.sh` applies the same patching, so
  `EXPOSE_CONSOLE=false .github/scripts/deploy-console.sh` works. When
  `EXPOSED_DOMAIN` is set, it is also the console domain the script passes to
  the playbook (`hlf_console_domain`): otherwise the console would get two
  different domains and the role would fail with an alias conflict.
- The patching lives in one helper, `.github/scripts/scenario-vars.sh`,
  sourced by both scripts. A variable that is not set is **removed** from
  `common-vars.yml`, so a value left by a previous run never leaks into the
  next one. Invalid values (`EXPOSE_CA=maybe`, an `INGRESS_TYPE` other than
  `nginx`, a domain with other characters than letters, digits, dots and
  dashes) stop the script with an error.
- In `tutorial/00-deploy-fabric-console.yml`, the `network_domains` include
  runs in `pre_tasks`, before the `fabric_operator_crds` role: a bad domain
  combination fails before any change to the cluster.
- Run modes: `KEEP_NETWORK=true` keeps the network after the tests,
  `RUN_TESTS_MODE=destroy` only destroys it, `RUN_TESTS_MODE=patch` only
  patches the vars files (to run one tutorial playbook by hand).

**Todo list:**
- [ ] Update `.github/scripts/run-tests.sh` to include `yq` patching for `ingress_type` and the six `expose_*` boolean variables into `common-vars.yml`.
- [ ] Patch `exposed_domain`, `hlf_network_domain`, `cluster_domain` and
  `neutralize_node_ingresses` when their environment variables are
  non-empty. Booleans are written as YAML booleans, not strings.
- [ ] Make `deploy-console.sh` read `common-vars.yml` the same way (one
  shared patching function for both scripts), so the console gets the same
  `expose_console` and `hlf_network_domain` as the organizations (it renders
  `spec.deployer.domain`, sub-task 1.5).
- [ ] Print the injected values (never the credentials) at the start of both
  scripts, so a log shows which scenario ran.
- [ ] `RUN_TESTS_MODE=patch`: patch the vars files, then exit without
  running any playbook.
- [ ] For the in-cluster Job (sub-task 1.9):
  - take `TEST_RUN_ID` from the environment when set, instead of generating
    it (Step 0 stamping), so two runs can target the same network. **Not
    done:** the Step 0 stamping does not exist (REMAINING_TODO.md item 2).
    Until it does, the names are fixed, so the destroy Job of 1.9 finds the
    network of the first Job without it;
  - `KEEP_NETWORK=true`: skip the final `join_network.sh destroy` and the
    cleanup trap;
  - `RUN_TESTS_MODE=destroy`: patch the vars files, then only run
    `join_network.sh destroy`;
  - skip the `.venv` activation and `_cfg/console-env.sh` sourcing when they
    don't exist (already the case for `console-env.sh`).
- [ ] Confirm that `INGRESS_TYPE`, `EXPOSE_CA`, `EXPOSE_PEER`, `EXPOSE_ORDERER`,
  `EXPOSE_PEER_OPERATIONS`, `EXPOSE_ORDERER_OPERATIONS`, and `EXPOSE_GRPCWEB`
  all default to safe values when not explicitly set.
- [ ] Verify `bash -n .github/scripts/run-tests.sh` passes syntax validation.

**Relevant context:**
- Baseline script: `.github/scripts/run-tests.sh` (as delivered in Step 0)
- Reference implementation: MIGRATION-PLAN.md §5.3.3
- Variable injection rationale (why `common-vars.yml` instead of `-e @file`):
  MIGRATION-PLAN.md §5.3.1 and the note following §5.3.3

### ✋  check 1.3

**Proves:** environment values reach `common-vars.yml` (and only when set),
`deploy-console.sh` uses the same values, and the three run modes work.
Every later check relies on this sub-task.

1. `bash -n .github/scripts/run-tests.sh && bash -n .github/scripts/deploy-console.sh`:
   no output.
2. Patch only, nothing set:
   ```bash
   RUN_TESTS_MODE=patch .github/scripts/run-tests.sh
   yq '{ingress_type, expose_console, expose_ca, expose_peer, expose_orderer, exposed_domain, hlf_network_domain, cluster_domain, neutralize_node_ingresses}' tutorial/common-vars.yml
   ```
   Expected: no playbook ran; the printed values show `nginx`, every
   `expose_*` `true`; the domains and `neutralize_node_ingresses` are `null`
   (not written).
3. Patch only, scenario B values:
   ```bash
   EXPOSE_CONSOLE=false EXPOSE_CA=false EXPOSE_PEER=false EXPOSE_ORDERER=false \
   EXPOSED_DOMAIN=example.com HLF_NETWORK_DOMAIN=cluster.local NEUTRALIZE_NODE_INGRESSES=true \
   RUN_TESTS_MODE=patch .github/scripts/run-tests.sh
   ```
   Expected, with the same `yq` query: these values, booleans written as
   `false` / `true` (not `"false"`). The script's banner shows them too, and
   no credential. Then restore the vars files (`git diff tutorial/`).
4. The console script gets the same values: `HLF_NETWORK_DOMAIN=cluster.local .github/scripts/deploy-console.sh`.
   Expected: the play **fails at once** with V3 (CA, peer and orderer are
   still exposed). That proves the value reached the console playbook; the
   failure happens before any change to the cluster. Restore the vars files.
5. Keep and destroy: **Regression run** with `KEEP_NETWORK=true`.
   Expected: exit 0, and `kubectl get ibppeer -n "$NS"` still lists the
   peers. Then **Destroy**: exit 0, no node left.
6. If Step 0's `TEST_RUN_ID` stamping is in: with `TEST_RUN_ID=check13` set,
   step 2 stamps the names with it (`grep -l check13 tutorial/*-vars.yml`).
7. **Changed files vs the merge-conflict analysis.**
   ```bash
   git fetch origin && git diff --name-only "$BASE"...HEAD
   ```
   Expected: only the files of the 1.3 row of the
   [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
   If a file is not listed, check that it is not changed by the
   sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 2: 1.2, 1.11.
   Look at their row of the table and at their open PR
   (`gh pr diff <PR number> --name-only`). If one of them changes it,
   raise a warning in the PR description: 1.3 must be merged before
   or after that sub-task (for example 1.2), not at the same time.
   In both cases, add the file to the 1.3 row of the table.


---

<a id="subtask-1-4"></a>
## Sub-task 1.4 — Console wait-logic for `expose_console` flag

**Scenarios:** [B](./SCENARIOS-MERMAID.md#scenario-b), [C](./SCENARIOS-MERMAID.md#scenario-c); [A](./SCENARIOS-MERMAID.md#scenario-a) unchanged.

**Intent:** Make the console wait and the printed URL independent of whether
the console is exposed. The console URL is always `console_url`, built from
`exposed_domain` (sub-task 1.1); only how the collection **reaches** the
console changes.

**What exists today** (the "split" is not the same in both roles):
- `roles/hlfsupport_console/tasks/k8s/create.yml:146-173` waits for the
  console Ingress, reads `console_url` from its host, polls it, prints it.
- `roles/fabric_console/tasks/k8s/create.yml:40-59` only waits for the
  Deployment and prints a URL it builds itself. There is no Ingress wait to
  split.
- CI uses neither role: `tutorial/00-deploy-fabric-console.yml` creates an
  inline `IBPConsole` and waits for the Deployment. It must get the same
  changes, or CI never exercises them.

**Expected outcomes:**
- `expose_console: true` (default): unchanged behaviour. `hlfsupport_console`
  still waits for its Ingress and polls `console_url`.
- `expose_console: false`:
  - no Ingress wait;
  - readiness is the console Deployment's `Available` condition
    (`kubernetes.core.k8s_info`), because the Ansible control node cannot
    resolve `console_incluster_url` when it runs outside the cluster;
  - a notice prints `console_url` (not served yet), `console_incluster_url`
    and how to expose it later (URL-MANAGEMENT-NEW.md §5.1).
- The console serves **HTTPS** on port 3000 (athena terminates TLS,
  URL-MANAGEMENT-NEW.md §5.3; checked 2026-10-16, check 4). Every in-cluster
  console URL in this plan is `https://<console>.<ns>.svc.<cluster_domain>:3000`,
  never `http://`.

**Todo list:**
- [ ] `roles/hlfsupport_console/tasks/k8s/create.yml`: guard the existing
  "Wait for console ingress to exist", "Set console URL from console
  ingress" and "Wait for console ingress to start" tasks with
  `expose_console | bool`.
- [ ] Add, guarded by `not expose_console | bool`:
  - `Wait for console Deployment to be Available` (`k8s_info`, `until`
    the `Available` condition is `True`);
  - `Print console exposition notice` (`console_url`, `console_incluster_url`,
    pointer to the manual exposure examples).
- [ ] `roles/fabric_console/tasks/k8s/create.yml:57-59` and
  `tutorial/00-deploy-fabric-console.yml:143-145`: print `console_url`, and
  the same notice when `expose_console: false`.
- [ ] The wait on the `Available` condition and the notice are written once,
  in `roles/network_domains/tasks/console_not_exposed.yml`: the three callers
  (`hlfsupport_console`, `fabric_console`, `tutorial/00-deploy-fabric-console.yml`)
  include it with `tasks_from` when `expose_console` is false, so they behave
  the same.
- [ ] Do **not** add any Gateway API (`ingress_type == 'gateway-api'`) branch
  yet; it belongs in Step 2.
- [ ] Run `ansible-lint` on the modified files.

**Relevant context:**
- MIGRATION-PLAN.md §5.5 has a first draft of these tasks; it predates the
  `exposed_domain` / `console_url` design and uses `http://`. Follow this
  sub-task instead.
- Only the `k8s` task files change. The OpenShift files (`tasks/openshift/`)
  wait for a Route and are not part of Step 1.
- Health path: the CI checks use `/ak/api/v3/health` with Basic auth (it
  returns 401 without credentials). Use the same path everywhere.

### ✋  check 1.4

**Proves:** with `expose_console: false` the console deploys without
waiting for its Ingress, answers in-cluster over HTTPS, and the user is told
how to reach it; the default path is unchanged.

1. `ansible-lint` on the modified files; **Rebuild**.
2. Default path: `.github/scripts/deploy-console.sh`.
   Expected: the same tasks and output as before this sub-task, ending with
   the console URL, and
   `curl -sk -o /dev/null -w '%{http_code}\n' -u "$API_KEY:$API_SECRET" "$API_ENDPOINT/ak/api/v3/health"`
   prints `200`.
3. Unexposed console: `EXPOSE_CONSOLE=false .github/scripts/deploy-console.sh`.
   Expected in the output: `Wait for console Deployment to be Available`
   `ok`; no Ingress wait; the notice with
   `console_url: https://default-hlf-console-console.<DOMAIN_A>` and
   `console_incluster_url: https://hlf-console.default.svc.cluster.local:3000`
   (HTTPS, port 3000), and the pointer to the exposure examples.
4. In-cluster, over HTTPS, without credentials:
   ```bash
   incluster curl -sk -o /dev/null -w '%{http_code}\n' https://hlf-console.default.svc.cluster.local:3000/ak/api/v3/health
   ```
   Expected: `401` (the console answered; no credentials were sent). `000`
   or a TLS error means a wrong URL or scheme.
5. Expected at this point: nginx **still** serves the console (step 2's
   `curl` still prints `200`). The Ingress class changes in 1.5.
6. `hlfsupport_console` cannot run here (it needs the licensed images):
   review its diff instead. The three Ingress tasks carry
   `when: expose_console | bool`.
7. Restore: `.github/scripts/deploy-console.sh`.
8. **Changed files vs the merge-conflict analysis.**
   ```bash
   git fetch origin && git diff --name-only "$BASE"...HEAD
   ```
   Expected: only the files of the 1.4 row of the
   [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
   If a file is not listed, check that it is not changed by the
   sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 3: 1.6, 1.11.
   Look at their row of the table and at their open PR
   (`gh pr diff <PR number> --name-only`). If one of them changes it,
   raise a warning in the PR description: 1.4 must be merged before
   or after that sub-task (for example 1.6), not at the same time.
   In both cases, add the file to the 1.4 row of the table.


---

<a id="subtask-1-5"></a>
## Sub-task 1.5 — `IBPConsole`: exposed domain, HLF node domain, unexposed Ingress

**Scenarios:** [B](./SCENARIOS-MERMAID.md#scenario-b), [C](./SCENARIOS-MERMAID.md#scenario-c); [A](./SCENARIOS-MERMAID.md#scenario-a) unchanged.

**Design reference:** URL-MANAGEMENT-NEW.md §2, §5.2, §7.1 (C2, C3, C6).

**Intent:** Render the three console fields that decouple the domains,
without changing the CR in the default case. All three fields already exist
in the operator's `IBPConsole` CRD (G2: no operator change).

| Field | Value | Rendered when |
|---|---|---|
| `spec.networkinfo.domain` | `network_domains_exposed_domain` | always (as today, from `console_domain`) |
| `spec.deployer.domain` | `hlf_node_domain` | `hlf_node_domain != network_domains_exposed_domain` |
| `spec.ingress.class` | `unexposed_ingress_class` (`none`) | `not expose_console` |

Scenario B (`exposed_domain: example.com`, `hlf_network_domain: cluster.local`,
nothing exposed, namespace `default`) renders:

```yaml
spec:
  networkinfo:
    domain: "example.com"                  # console URL + console TLS SAN
  deployer:
    domain: "default.svc.cluster.local"    # every CA / peer / orderer FQDN
  ingress:
    class: "none"                          # console Ingress kept, not served
```

**Checked on 2026-10-16** (URL-MANAGEMENT-NEW.md §9): `deployer.domain`
reaches the node CRs and their URLs and TLS SANs (check 1); nginx stops
serving an Ingress of class `none` and serves it again when set back to
`nginx` (check 2); the console certificate names only the `exposed_domain`
host (check 4).

**Finding F1: the deployer reads its domain only at startup.** Patching
`spec.deployer.domain` on a running console updates the deployer ConfigMap,
but nodes created afterwards keep the old domain until the console pod
restarts. Hence:
- The field is rendered when the console is **created**: the normal path.
- On an existing console, the role compares the live
  `spec.deployer.domain` with `hlf_node_domain`. If they differ, it restarts
  the console Deployment after the CR update (`kubectl rollout restart`
  equivalent: patch the pod template annotation
  `kubectl.kubernetes.io/restartedAt`) and prints a warning: nodes created
  before keep their old domain and certificates (URL-MANAGEMENT-NEW.md §4.4).

**Expected outcomes:**
- Default variables: the rendered `IBPConsole` is the same as today, minus
  the duplicate `networkinfo:` key of the `fabric_console` templates (YAML
  kept the last copy; both held the same value).
- Scenario B: the three fields above are rendered; the console Ingress is
  unserved.
- Changing `hlf_network_domain` on an existing console restarts it and warns.

**Todo list:**
- [ ] `roles/fabric_console/templates/{k8s,openshift}/hlf-operations-console.yaml.j2`:
  `networkinfo.domain: "{{ network_domains_exposed_domain }}"`; remove the
  second `networkinfo:` block (`:34-35`); add the conditional `deployer:`
  and `ingress:` blocks.
- [ ] `roles/hlfsupport_console/templates/{k8s,openshift}/console.yml.j2`:
  same.
- [ ] `tutorial/00-deploy-fabric-console.yml`: same, on the inline CR
  (`hlf_console_domain` stays the input of `exposed_domain`).
- [ ] **Fix the `IBPConsole` `apiVersion` in every read and delete** (review,
  "Documentation inconsistencies" — it is a bug, not only a wording issue).
  The operator's CRDs serve **only `ibp.com/v1beta1`** (checked 2026-10-16 on
  KIND: `ibpconsoles.ibp.com` and `ibppeers.ibp.com` list a single version,
  `v1beta1`). Querying the running console with `kubernetes.core.k8s_info`:
  `api_version: ibp.com/v1alpha2` returns **0 resources and no error**
  (`api_found: false`); `ibp.com/v1beta1` finds it. So today "Determine if
  console exists" always concludes there is no console. Change to
  `ibp.com/v1beta1`:
  - `roles/fabric_console/tasks/k8s/create.yml:20`,
    `roles/fabric_console/tasks/openshift/create.yml:8`;
  - `roles/hlfsupport_console/tasks/k8s/create.yml:89`,
    `roles/hlfsupport_console/tasks/openshift/create.yml:85`;
  - `roles/hlfsupport_console/tasks/{k8s,openshift}/delete.yml:28`;
  - `roles/fabric_console/tasks/{k8s,openshift}/delete.yml:28`, which pick
    `v1alpha2` / `v1alpha1` from `product_version` and never `v1beta1`.
  The templates and `tutorial/00-{deploy,delete}-fabric-console.yml` already
  use `v1beta1`.
- [ ] Add the "domain changed on an existing console" detection and restart.
  It reads the live `IBPConsole`, so it depends on the `apiVersion` fix above.
  Written once, in `roles/network_domains/tasks/console_domain_change.yml`,
  and included right after the CR update by the four create paths of the
  console roles and by `tutorial/00-deploy-fabric-console.yml` (which now
  reads the live console too). The running console's node domain is
  `spec.deployer.domain`, or `spec.networkinfo.domain` without it.
- [x] ~~When `spec.deployer.domain` or `spec.ingress.class` is no longer
  rendered, remove it explicitly.~~ **Not needed** (checked 2026-10-27): the
  three create paths use `kubernetes.core.k8s` with `apply: true`
  (`kubectl apply` semantics), which removes the fields of the last applied
  configuration that the template no longer renders. Going back from B to A
  in place left neither `deployer` nor `ingress` on the CR.
- [ ] Render the templates for scenarios A and B with `ansible-playbook
  --check --diff` and compare with the examples above.

**Relevant context:**
- With the wrong `apiVersion`, `hlfsupport_console` also never sees an
  existing console in its upgrade path
  (`roles/hlfsupport_console/tasks/k8s/create.yml:113,122`: delete and
  recreate on `operator_upgrade`), so the fix changes upgrade behaviour too.
  Test an upgrade run (console already present) after the fix.
- The console's own Service is named after the CR (`hlf-console`, port
  `optools` 3000): that is `console_incluster_url`.
- The console certificate does not name `console_incluster_url`'s host
  (finding F2). The collection never verifies certificates
  (`validate_certs=False`), so it is unaffected; a strict in-cluster client
  needs `console_tls_secret` with that name as an extra SAN.

### ✋  check 1.5

**Proves:** the CR is unchanged in A, gets the three fields in B, nginx stops
serving the console, the `apiVersion` fix finds the existing console, and a
domain change restarts the console with a warning.

1. **Before writing any code**, save today's console spec (scenario A):
   ```bash
   kubectl get ibpconsole hlf-console -n "$NS" -o json | jq -S '.spec | del(.connectionString, .password)' > /tmp/console-spec-before.json
   ```
   `connectionString` (CouchDB credentials, generated anew for every console)
   and `password` (removed by the operator once a new console is set up) are
   managed by the operator, not by the template: they are left out, which
   also keeps credentials off the screen.
2. After the change: `ansible-lint`, **Rebuild**, **Fresh console**, then:
   ```bash
   kubectl get ibpconsole hlf-console -n "$NS" -o json | jq -S '.spec | del(.connectionString, .password)' | diff /tmp/console-spec-before.json -
   ```
   Expected: no difference.
3. `apiVersion` fix: `.github/scripts/deploy-console.sh` once more.
   Expected: "Determine if console exists" finds the console; the console pod
   is **not** recreated (same name and age in `kubectl get pods -n "$NS"`).
4. Scenario B, console only (no node yet):
   ```bash
   .github/scripts/undeploy-console.sh
   EXPOSE_CONSOLE=false EXPOSE_CA=false EXPOSE_PEER=false EXPOSE_ORDERER=false \
   EXPOSED_DOMAIN=example.com HLF_NETWORK_DOMAIN=cluster.local .github/scripts/deploy-console.sh
   kubectl get ibpconsole hlf-console -n "$NS" -o json | jq '.spec | {networkinfo, deployer, ingress}'
   kubectl get ingress -n "$NS"
   ```
   Expected: `networkinfo.domain: example.com`,
   `deployer.domain: default.svc.cluster.local`, `ingress.class: none`; the
   console Ingress shows `CLASS none`.
5. nginx no longer serves it; its Service does:
   ```bash
   curl -sk -o /dev/null -w '%{http_code}\n' \
     --resolve default-hlf-console-console.example.com:443:127.0.0.1 \
     https://default-hlf-console-console.example.com/ak/api/v3/health          # expected: 404
   incluster curl -sk -o /dev/null -w '%{http_code}\n' \
     https://hlf-console.default.svc.cluster.local:3000/ak/api/v3/health        # expected: 401
   ```
6. Finding F1, domain change on a running console: rerun step 4's deploy
   with `HLF_NETWORK_DOMAIN=fabric.example.com` instead of `cluster.local`.
   Expected: a warning that the HLF node domain changed (nodes created before
   keep their names and certificates); the console Deployment restarts
   (`kubectl get deploy hlf-console -n "$NS" -o jsonpath='{.spec.template.metadata.annotations}'`
   shows `kubectl.kubernetes.io/restartedAt`); `deployer.domain` is now
   `fabric.example.com`.
7. Back to A, first **in place** (`.github/scripts/deploy-console.sh` with no
   variable, without undeploying): the F1 warning shows again, and step 2's
   `diff` is empty (no `deployer` or `ingress` field left behind). Then with a
   **Fresh console**: step 2's `diff` is empty again.
8. **Regression run**: exit 0.
9. **Changed files vs the merge-conflict analysis.**
   ```bash
   git fetch origin && git diff --name-only "$BASE"...HEAD
   ```
   Expected: only the files of the 1.5 row of the
   [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
   If a file is not listed, check that it is not changed by the
   sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 3 (it may last into wave 4): 1.6, 1.7, 1.8, 1.11.
   Look at their row of the table and at their open PR
   (`gh pr diff <PR number> --name-only`). If one of them changes it,
   raise a warning in the PR description: 1.5 must be merged before
   or after that sub-task (for example 1.6), not at the same time.
   In both cases, add the file to the 1.5 row of the table.


---

<a id="subtask-1-6"></a>
## Sub-task 1.6 — One collection-owned ClusterIP Service per endpoint (`expose-none` compatibility)

**Scenarios:** [B](./SCENARIOS-MERMAID.md#scenario-b), [C](./SCENARIOS-MERMAID.md#scenario-c); [A](./SCENARIOS-MERMAID.md#scenario-a) unchanged.

**Intent:** The Fabric Operator encodes `<fqdn>:443` for **every** endpoint of
every node in Custom Resources, ConfigMaps, connection profiles and console
registry entries (`api_url`, `operations_url`, `grpcwp_url`, `osnadmin_url`).
When `expose_*: false`, those FQDNs must still reach the right container port
in-cluster, without nginx.

A single Service per node cannot do this: each node advertises **several**
endpoints on `:443`, and a Service port maps `443` to exactly **one**
`targetPort`. Adding `443 → 7051` to the operator's peer Service would send
`-operations:443` to the gRPC port. That would break the console's status
checks and its grpcweb proxy, the collection's `/healthz` waits, and
`osnadmin` channel joins
(see [REVIEW-MIGRATION-PLAN-STEP-1.md](./REVIEW-MIGRATION-PLAN-STEP-1.md) B3).

The collection therefore creates **its own ClusterIP Service per endpoint**
(per node × endpoint type), each mapping `443` to that endpoint's native
port. Each Service is paired with one CoreDNS rewrite per endpoint type
(sub-task 1.8). The operator's own Services are **never modified**, so
operator reconciliation cannot revert anything.

**Endpoint → Service mapping** (one row = one Service per node):

| Component | Endpoint type (FQDN suffix) | Console URL field | `port` | `targetPort` |
|---|---|---|---|---|
| CA      | `ca`         | `api_url`        | 443 | 7054 |
| CA      | `operations` | `operations_url` | 443 | 9443 |
| Peer    | `peer`       | `api_url`        | 443 | 7051 |
| Peer    | `operations` | `operations_url` | 443 | 9443 |
| Peer    | `grpcweb`    | `grpcwp_url`     | 443 | 7443 |
| Orderer | `orderer`    | `api_url`        | 443 | 7050 |
| Orderer | `admin`      | `osnadmin_url`   | 443 | 9443 |
| Orderer | `operations` | `operations_url` | 443 | 8443 |
| Orderer | `grpcweb`    | `grpcwp_url`     | 443 | 7443 |

**Naming rule.** The operator builds each FQDN as
`<namespace>-<cr_name>-<endpoint>.<hlf_node_domain>` (`hlf_node_domain`
from sub-task 1.1, i.e. the node CRs' `spec.domain`). The collection names
each Service after the **first DNS label** of that FQDN:

```
Service name:  <namespace>-<cr_name>-<endpoint>        e.g. default-org1peer-operations
Service FQDN:  <namespace>-<cr_name>-<endpoint>.<namespace>.svc.<cluster_domain>
```

As a result:
- **Cluster-local HLF domain** (`hlf_network_domain_is_cluster_local`,
  scenario B): `hlf_node_domain` is `<namespace>.svc.<cluster_domain>`, so
  the operator's FQDNs **are** these Service FQDNs. No CoreDNS rewrite at all
  (checked 2026-10-16 on a CA: URL-MANAGEMENT-NEW.md §9 check 1).
- **Otherwise** (scenario C): CoreDNS needs **one** regex rewrite per
  endpoint type (`<ns>-*-<endpoint>.<hlf_node_domain>` → `<same
  label>.<ns>.svc.<cluster_domain>`, sub-task 1.8), not one per node. The
  rules can be written before any node exists, which matters because each
  create module polls `operations_url/healthz` **inside** its own task (see
  `wait_for()` in `plugins/module_utils/ordering_services.py`). The Service
  and the rewrite must therefore exist before the module call returns.
- Each Service name is a valid DNS-1035 label (≤ 63 chars, starts with a
  letter) because it is also the first label of an FQDN the operator already
  generates. An `assert` still enforces this.

**Lifecycle.** The Services are created **before** the corresponding
`certificate_authority` / `peer` / `ordering_service` module call. Until the
operator starts the pods, a Service has no endpoints, which is harmless. The
module's own health wait then succeeds through the new Service. After the
module returns, two checks run:
1. **V5** (`network_domains`, `tasks_from: verify_urls`): every returned URL
   host ends with `.` + `hlf_node_domain`. It catches a console deployed
   with another domain, or a `k8s_namespace` different from the console
   namespace.
2. **Service match** (`k8s_endpoint_services`, `tasks_from: verify`): every
   returned URL (`api_url`, `operations_url`, `grpcwp_url`, `osnadmin_url`)
   has a created Service. It catches a wrong CR name (S1) or a missing
   endpoint type the health wait does not exercise (grpcweb, admin).

**How the CR name is known before the module call (S1).** The console, not
the operator, derives the CR name from the display name
(URL-MANAGEMENT-EXISTING.md §3): lowercase, characters outside
`[a-zA-Z0-9-_]` removed, prefix `ibp` if it starts with a digit, truncated
to 64, **a suffix added when the name is taken**, then `-` and `_` removed.
"Lowercase and remove non-`[a-z0-9]`" is right only for a fresh, letter-first
name. So:
- The pre-call name follows the simple rule and is **checked** against the
  first label of the returned URLs (check 2 above). A mismatch fails with a
  message naming the actual CR name.
- On reruns, the CR name is read from the returned URLs, not re-derived.
- A deterministic alternative is to send the CR name as the API `id` field,
  which athena uses verbatim (*athena* `libs/comp_formatting_lib.js:538,
  719-726`). The modules don't expose it today; adding an optional `id`
  parameter is a small plugin change, out of scope unless the check above
  fails in practice.

**Finding F3 — closed** (URL-MANAGEMENT-NEW.md §9.1): a test CA meant to be
`Check1 CA` was stored as `Check1`. This was a test-harness error, not a
console behaviour: `-e ca_display_name="Check1 CA"` reaches Ansible as
`ca_display_name=Check1 CA`, and the key=value parser keeps only `Check1`.
The console stored exactly the name it received. Display-name lookups are
not at risk.

**Assumptions** (encoded as role defaults, so that a wrong guess means a
default change, not a redesign):

| # | Assumption | Default encoding | Status |
|---|---|---|---|
| S1 | Fresh CR name = display name lowercased, every non-`[a-z0-9]` removed (`Org1 CA` → `org1ca`) | `k8s_endpoint_services_cr_name_regex: '[^a-z0-9]'` | **Partly true**: see above; checked after each call |
| S2 | Ordering node CR names are `<ordering service cr_name>node<i>`, `i` = 1..N | `k8s_endpoint_services_orderer_node_suffix: 'node'` | **Confirmed in source** (*operator* `pkg/offering/base/orderer/orderer.go:428`, `override/orderernode.go:59`) |
| S3 | Operator pods carry the label `app: <cr_name>` | `k8s_endpoint_services_selector_key: app` | **Confirmed on a CA** (2026-10-16: Service selector `app: check1`, per-endpoint Services got ready backends) |
| S4 | Node TLS certificates carry every endpoint FQDN as a SAN | — | **Confirmed**: in source for peer/orderer/CA (URL-MANAGEMENT-EXISTING.md §4.2), and on a CA with `hlf_node_domain = default.svc.cluster.local` (strict TLS passed) |

### New internal role `k8s_endpoint_services`

The three organization roles are separate playbooks and cannot share task
files, so the logic lives in a small role called via `include_role`. Its
Kubernetes dependency (`kubernetes.core`, a kubeconfig) is pulled in **only**
when a component is not exposed. The REST-only path of the organization roles
stays unchanged.

`roles/k8s_endpoint_services/defaults/main.yml`:

```yaml
# Namespace of the console and the nodes, passed by the caller.
k8s_endpoint_services_namespace: ""
# Kind of component the Services are created for: ca | peer | orderer.
k8s_endpoint_services_component: ""
# Operator CR names, one per node (see S1/S2 in MIGRATION-STEP-1.md).
k8s_endpoint_services_cr_names: []
k8s_endpoint_services_cr_name_regex: '[^a-z0-9]'
k8s_endpoint_services_orderer_node_suffix: node
k8s_endpoint_services_selector_key: app
# Endpoint types per component and the native container port each maps to.
k8s_endpoint_services_endpoints:
  ca:
    - { endpoint: ca, target_port: 7054 }
    - { endpoint: operations, target_port: 9443 }
  peer:
    - { endpoint: peer, target_port: 7051 }
    - { endpoint: operations, target_port: 9443 }
    - { endpoint: grpcweb, target_port: 7443 }
  orderer:
    - { endpoint: orderer, target_port: 7050 }
    - { endpoint: admin, target_port: 9443 }
    - { endpoint: operations, target_port: 8443 }
    - { endpoint: grpcweb, target_port: 7443 }
# Console URLs to verify after the module call (tasks_from: verify).
k8s_endpoint_services_urls: []
```

`roles/k8s_endpoint_services/tasks/main.yml` (create):

```yaml
- name: Check every Service name is a valid DNS-1035 label
  ansible.builtin.assert:
    that:
      - _svc_name is match('^[a-z]([-a-z0-9]*[a-z0-9])?$')
      - _svc_name | length <= 63
    fail_msg: >-
      Service name '{{ _svc_name }}' is not a valid DNS-1035 label. Shorten the
      namespace or the component display name.
    quiet: true
  loop: "{{ k8s_endpoint_services_cr_names | product(k8s_endpoint_services_endpoints[k8s_endpoint_services_component]) | list }}"
  vars:
    _svc_name: "{{ k8s_endpoint_services_namespace }}-{{ item.0 }}-{{ item.1.endpoint }}"

- name: Create one ClusterIP Service per endpoint
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: v1
      kind: Service
      metadata:
        name: "{{ _svc_name }}"
        namespace: "{{ k8s_endpoint_services_namespace }}"
        labels:
          app.kubernetes.io/managed-by: fabric-ansible-collection
          fabric-ansible-collection/component: "{{ k8s_endpoint_services_component }}"
          fabric-ansible-collection/instance: "{{ item.0 }}"
          fabric-ansible-collection/endpoint: "{{ item.1.endpoint }}"
      spec:
        type: ClusterIP
        selector: "{{ {k8s_endpoint_services_selector_key: item.0} }}"
        ports:
          - name: https
            port: 443
            # Must stay an int: a string targetPort is a *named* port.
            targetPort: "{{ item.1.target_port | int }}"
            protocol: TCP
  loop: "{{ k8s_endpoint_services_cr_names | product(k8s_endpoint_services_endpoints[k8s_endpoint_services_component]) | list }}"
  loop_control:
    label: "{{ _svc_name }}"
  vars:
    _svc_name: "{{ k8s_endpoint_services_namespace }}-{{ item.0 }}-{{ item.1.endpoint }}"
```

`roles/k8s_endpoint_services/tasks/verify.yml`:

```yaml
- name: Assert every console endpoint URL has a matching per-endpoint Service
  ansible.builtin.assert:
    that:
      - (item | urlsplit('hostname')).split('.') | first in _expected_names
    fail_msg: >-
      The console advertises '{{ item }}' but no Service named
      '{{ (item | urlsplit('hostname')).split('.') | first }}' was created.
      The CR name derived from the display name was wrong (assumption S1 of
      MIGRATION-STEP-1.md sub-task 1.6); the console's CR name is the part
      between '{{ k8s_endpoint_services_namespace }}-' and the endpoint suffix.
    quiet: true
  loop: "{{ k8s_endpoint_services_urls | select | list }}"
  vars:
    _expected_names: >-
      {{ k8s_endpoint_services_cr_names
         | product(k8s_endpoint_services_endpoints[k8s_endpoint_services_component] | map(attribute='endpoint'))
         | map('join', '-')
         | map('regex_replace', '^', k8s_endpoint_services_namespace ~ '-')
         | list }}
```

`roles/k8s_endpoint_services/tasks/delete.yml`:

```yaml
- name: Delete the per-endpoint Services of the given instances
  kubernetes.core.k8s:
    state: absent
    kind: Service
    namespace: "{{ k8s_endpoint_services_namespace }}"
    label_selectors:
      - app.kubernetes.io/managed-by=fabric-ansible-collection
      - fabric-ansible-collection/instance={{ item }}
  loop: "{{ k8s_endpoint_services_cr_names }}"
```

### Calls from the organization roles

`roles/endorsing_organization/tasks/create.yml` (after the
`network_domains` include of sub-task 1.1, which makes `expose_*` and
`hlf_node_domain` available):

```yaml
- name: Create per-endpoint Services for the CA (unexposed)
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.k8s_endpoint_services
  vars:
    k8s_endpoint_services_namespace: "{{ k8s_namespace }}"
    k8s_endpoint_services_component: ca
    k8s_endpoint_services_cr_names:
      - "{{ ca_name | lower | regex_replace('[^a-z0-9]', '') }}"   # S1, checked below
  when: not expose_ca | bool

- name: Create certificate authority          # existing task, add `register`
  hyperledger.fabric_ansible_collection.certificate_authority: ...
  register: endorsing_organization_ca

- name: Check the CA URLs use the HLF node domain (V5)
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.network_domains
    tasks_from: verify_urls
  vars:
    network_domains_urls:
      - "{{ endorsing_organization_ca.certificate_authority.api_url }}"
      - "{{ endorsing_organization_ca.certificate_authority.operations_url }}"

- name: Verify per-endpoint Services for the CA (unexposed)
  ansible.builtin.include_role:
    name: hyperledger.fabric_ansible_collection.k8s_endpoint_services
    tasks_from: verify
  vars:
    k8s_endpoint_services_namespace: "{{ k8s_namespace }}"
    k8s_endpoint_services_component: ca
    k8s_endpoint_services_cr_names:
      - "{{ ca_name | lower | regex_replace('[^a-z0-9]', '') }}"
    k8s_endpoint_services_urls:
      - "{{ endorsing_organization_ca.certificate_authority.api_url }}"
      - "{{ endorsing_organization_ca.certificate_authority.operations_url }}"
  when: not expose_ca | bool
```

V5 runs in **every** scenario (it holds today too, URL-MANAGEMENT-NEW.md
§8). The Service blocks run only for unexposed components.

Same pattern for the peers (before *Create peer* / *Create multiple peers*):

```yaml
    k8s_endpoint_services_component: peer
    k8s_endpoint_services_cr_names: >-
      {{ ([peer_name] if peers == 1
          else range(1, peers + 1) | map('string')
               | map('regex_replace', '^', peer_name) | list)
         | map('lower') | map('regex_replace', '[^a-z0-9]', '') | list }}
```

Verify with `api_url`, `operations_url` and `grpcwp_url` of each registered
peer. For *Create multiple peers*, use the `results` list.

`roles/ordering_organization/tasks/create.yml`: the same CA block, plus,
before *Create ordering service*:

```yaml
    k8s_endpoint_services_component: orderer
    k8s_endpoint_services_cr_names: >-
      {{ range(1, ordering_service_nodes + 1) | map('string')
         | map('regex_replace', '^', (ordering_service_name | lower
               | regex_replace('[^a-z0-9]', '')) ~ 'node')
         | list }}
```

After the module call, run V5 and the verify step with `api_url`,
`operations_url`, `grpcwp_url` and `osnadmin_url` of every element of the
registered `ordering_service` list. `osnadmin_url` is empty on Fabric < 2.4.1,
and `select` drops empty values (checked by V5 case 5, 2026-10-16).

The `delete.yml` of each organization role calls
`tasks_from: delete` with the same `cr_names`, guarded by the same `when`.

**Expected outcomes:**
- With `expose_ca/peer/orderer: false`, the namespace contains one Service per
  row of the mapping table for every node, each listening on `443` only.
- The operator's own Services are byte-for-byte unchanged.
- From an in-cluster pod,
  `curl -k https://<ns>-<peer>-operations.<hlf_node_domain>/healthz` returns
  `{"status":"OK"}` (port 9443 reached, not 7051). Reproduced on a CA,
  scenario B, 2026-10-16.
- The module health waits pass without nginx in the path, when the
  playbooks run in-cluster (sub-task 1.9). From outside the cluster they
  cannot resolve cluster-local names (finding F4).
- V5 fails when a returned URL is not under `hlf_node_domain`; the verify
  step fails when a returned URL has no matching Service, naming the actual
  CR name.
- `ansible-lint` passes on the new role and all modified task files.

**Todo list:**
- [ ] Create `roles/k8s_endpoint_services/` (`defaults/main.yml`,
  `tasks/main.yml`, `tasks/verify.yml`, `tasks/delete.yml`, `meta/main.yml`)
  with the content above. `k8s_endpoint_services_namespace` is passed by the
  caller (no `k8s_namespace` default inside the role).
- [ ] Add the create / V5 / verify blocks around the CA and peer module calls
  in `roles/endorsing_organization/tasks/create.yml`, and register the module
  outputs (`endorsing_organization_ca`, `endorsing_organization_peer`,
  `endorsing_organization_peers`).
- [ ] Add the create / V5 / verify blocks around the CA and ordering-service
  module calls in `roles/ordering_organization/tasks/create.yml`, and
  register the module outputs.
- [ ] Add the delete calls to both organization roles' `delete.yml`.
- [ ] Make the verify step's failure message print the CR name read from the
  returned URL, so an S1 mismatch is fixable at once.
- [ ] Document the new role in `docs/source/roles/` (internal, but its
  defaults are user-overridable).
- [ ] Run `ansible-lint` on the new role and all modified task files.

**Relevant context:**
- Sub-task 1.6 runs whenever the component is not exposed, **including**
  when `hlf_network_domain_is_cluster_local`. Only the CoreDNS rewrites
  (1.8) are skipped in that case.
- Organization roles: `expose_ca`, `expose_peer`, `expose_orderer` and
  `hlf_node_domain` come from the `network_domains` include (sub-task 1.1),
  not from another role's defaults.
- Adding `kubernetes.core.k8s` tasks to these roles introduces a dependency
  on a kubeconfig and the `kubernetes` Python library, which their REST-only
  path does not have today. It is pulled in **only** when a component is
  unexposed (review, "Organization roles").
- Partial exposure (e.g. `expose_peer: false`, `expose_ca: true`) works on
  the Service side. The CI per-endpoint-type rewrites of sub-task 1.8,
  however, assume CA, peer and orderer are **all** unexposed, because the
  `-operations` suffix is shared by all three components. Mixed modes need
  exact per-FQDN rewrites and are out of scope for Step 1 CI.
- The port variables `ingress_grpc_peer_port`, `ingress_grpc_orderer_port`
  and `ingress_ca_port` from sub-task 1.1 remain Gateway-API listener ports
  for Step 2. They are **not** the native target ports above.

### ✋  check 1.6

**Proves:** every unexposed node gets one Service per endpoint, with the
right port and a ready backend; the operator's Services are untouched; the
checks after each module call catch a wrong URL or CR name; scenario A
creates nothing.

This check uses scenario C with the console exposed (see "What a laptop can
run" above). It tests the Services from inside the cluster through their
Service FQDNs: the names scenario B uses.

1. `ansible-lint` on the new role and the organization roles; **Rebuild**.
2. **Scenario C run**. Expected: exit 0; in the log, the V5 task and
   "Verify per-endpoint Services" are `ok` after every CA, peer and ordering
   service call.
3. One Service per endpoint, port 443 to the native port:
   ```bash
   kubectl get svc -n "$NS" -l "$SEL" \
     -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.ports[*].port}{" -> "}{.spec.ports[*].targetPort}{"\n"}{end}'
   ```
   Expected, and nothing else: per CA `-ca 443 -> 7054`,
   `-operations 443 -> 9443`; per peer `-peer -> 7051`, `-operations -> 9443`,
   `-grpcweb -> 7443`; per orderer node `-orderer -> 7050`, `-admin -> 9443`,
   `-operations -> 8443`, `-grpcweb -> 7443`.
4. Every Service has a ready backend:
   ```bash
   for s in $(kubectl get svc -n "$NS" -l "$SEL" -o name); do
     echo "${s#service/} $(kubectl get endpoints -n "$NS" "${s#service/}" -o jsonpath='{.subsets[*].addresses[*].ip}')"
   done
   ```
   Expected: an IP on every line.
5. The operator's Services are untouched: none of them listens on 443.
   ```bash
   kubectl get svc -n "$NS" -l "app.kubernetes.io/managed-by!=fabric-ansible-collection" \
     -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.ports[*].port}{"\n"}{end}'
   ```
   Expected: native ports only (7054, 9443, 7051, ...), no `443` on a CA,
   peer or orderer Service.
6. The Service names reach the right port, from inside the cluster:
   ```bash
   PEER_OPS=$(kubectl get svc -n "$NS" -l "$SEL,fabric-ansible-collection/component=peer,fabric-ansible-collection/endpoint=operations" -o jsonpath='{.items[0].metadata.name}')
   CA_OPS=$(kubectl get svc -n "$NS" -l "$SEL,fabric-ansible-collection/component=ca,fabric-ansible-collection/endpoint=operations" -o jsonpath='{.items[0].metadata.name}')
   incluster curl -sk "https://$PEER_OPS.$NS.svc.cluster.local/healthz"               # {"status":"OK"}
   incluster curl -sk "https://${CA_OPS%-operations}-ca.$NS.svc.cluster.local/cainfo"  # JSON with "CAName"
   ```
7. Negative checks on the two post-call checks, with a throwaway playbook
   (no cluster change):
   ```bash
   cat > /tmp/verify-check.yml <<'EOF'
   - hosts: localhost
     gather_facts: false
     tasks:
       - name: V5 with a URL outside hlf_node_domain (must fail)
         ansible.builtin.include_role:
           name: hyperledger.fabric_ansible_collection.network_domains
           tasks_from: verify_urls
         vars:
           hlf_node_domain: "{{ domain }}"
           network_domains_urls: ["https://default-org1ca-ca.other.example:443"]
         when: check == 'v5'
       - name: Service match with a wrong CR name (must fail)
         ansible.builtin.include_role:
           name: hyperledger.fabric_ansible_collection.k8s_endpoint_services
           tasks_from: verify
         vars:
           k8s_endpoint_services_namespace: default
           k8s_endpoint_services_component: peer
           k8s_endpoint_services_cr_names: [wrongname]
           k8s_endpoint_services_urls: ["https://{{ peer_ops }}.{{ domain }}:443"]
         when: check == 'verify'
   EOF
   ansible-playbook -i localhost, -c local /tmp/verify-check.yml -e check=v5 -e domain="$DOMAIN_A"
   ansible-playbook -i localhost, -c local /tmp/verify-check.yml -e check=verify -e domain="$DOMAIN_A" -e peer_ops="$PEER_OPS"
   ```
   Expected: both fail. V5 names the URL and `hlf_node_domain`; the verify
   message names `$PEER_OPS` and tells where the real CR name is in it.
8. **Destroy** (with the same `EXPOSE_*`). Expected: exit 0, and
   `kubectl get svc -n "$NS" -l "$SEL"` finds nothing: the delete path
   removed the Services.
9. Scenario A creates nothing: **Regression run** with `KEEP_NETWORK=true`,
   then `kubectl get svc -n "$NS" -l "$SEL"` finds nothing. **Destroy**.
10. **Changed files vs the merge-conflict analysis.**
    ```bash
    git fetch origin && git diff --name-only "$BASE"...HEAD
    ```
    Expected: only the files of the 1.6 row of the
    [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
    If a file is not listed, check that it is not changed by the
    sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 3: 1.4, 1.5, 1.11.
    Look at their row of the table and at their open PR
    (`gh pr diff <PR number> --name-only`). If one of them changes it,
    raise a warning in the PR description: 1.6 must be merged before
    or after that sub-task (for example 1.4), not at the same time.
    In both cases, add the file to the 1.6 row of the table.


---

<a id="subtask-1-7"></a>
## Sub-task 1.7 — Opt-in neutralization of node Ingress objects

**Scenarios:** [B](./SCENARIOS-MERMAID.md#scenario-b), [C](./SCENARIOS-MERMAID.md#scenario-c), opt-in.

**Design reference:** URL-MANAGEMENT-NEW.md §5.4 (decision D4).

**Intent:** The operator creates an nginx Ingress for every CA, peer and
orderer node, with no setting to turn it off (review B2). In scenario B its
hosts are cluster-local, so they don't resolve outside the cluster, but nginx
still forwards a client that sends the right SNI. With
`neutralize_node_ingresses: true`, the organization roles set
`spec.ingress.class: <unexposed_ingress_class>` on the CR of each unexposed
node after its module call. The Ingress is kept but no longer served.

**Checked on 2026-10-16** on a CA (URL-MANAGEMENT-NEW.md §9 checks 2, 3, 7):
- nginx stops serving the Ingress (`/cainfo` through nginx: 200 → 404);
- a later update through the console keeps `spec.ingress.class`;
- the CR patch does not restart the node pod (same UID, 0 restarts); the
  Ingress class changes within ~4 s.

**Expected outcomes:**
- Default (`false`): nothing changes.
- `true`: after each node module call, the node CR has
  `spec.ingress.class: none`, the Ingress `ingressClassName: none`, and nginx
  answers 404 for every endpoint host of that node.
- Per component: only unexposed components are patched.

**Todo list:**
- [ ] In both organization roles, after each node module call (and after
  V5), patch `IBPCA` / `IBPPeer` / `IBPOrderer` (one per ordering node) with
  `spec.ingress.class: "{{ unexposed_ingress_class }}"` when
  `neutralize_node_ingresses | bool and not expose_<component> | bool`.
  The CR names come from the returned URLs (sub-task 1.6).
- [ ] Wait until each Ingress shows `ingressClassName == unexposed_ingress_class`.
- [ ] Repeat check 3 on a **peer** update before considering a `true`
  default (D4).

**Relevant context:**
- The neutralized case is checked by assertion 1 of sub-task 1.10, in that
  PR: this one doesn't touch the assertions.
- The class must be set on the **CR**, not the Ingress: the operator rebuilds
  the Ingress from the CR on every spec change.
- Exposure window: between CR creation and the patch (the module blocks until
  the node is healthy), the endpoints are reachable through nginx. Closing it
  needs an operator change, out of scope.

### ✋  check 1.7

**Proves:** by default nothing changes; with `neutralize_node_ingresses:
true` every unexposed node CR gets class `none`, nginx stops serving it, and
no pod restarts.

Once node Ingresses are unserved the laptop cannot reach the nodes, so a
full run from the laptop would fail at the channel steps. This check
creates the ordering organization only (CA and orderer). The full run with
neutralization is in  check 1.9.

1. `ansible-lint`; **Rebuild**.
2. Default, ordering organization only:
   ```bash
   EXPOSE_CA=false EXPOSE_PEER=false EXPOSE_ORDERER=false RUN_TESTS_MODE=patch .github/scripts/run-tests.sh
   (cd tutorial && ansible-playbook 01-create-ordering-organization-components.yml)
   kubectl get ibpca,ibporderer -n "$NS" -o custom-columns='NAME:.metadata.name,CLASS:.spec.ingress.class'
   kubectl get ingress -n "$NS"
   CA_HOST=$(kubectl get ingress -n "$NS" -o jsonpath='{range .items[*].spec.rules[*]}{.host}{"\n"}{end}' | grep -- '-ca\.' | head -1)
   curl -sk -o /dev/null -w '%{http_code}\n' --resolve "$CA_HOST:443:127.0.0.1" "https://$CA_HOST/cainfo"
   ```
   Expected: CR class `<none>` (not set), Ingress class `nginx`, `200`.
   Then delete: `(cd tutorial && ansible-playbook 99-delete-ordering-organization-components.yml)`.
3. Neutralized, same organization:
   ```bash
   EXPOSE_CA=false EXPOSE_PEER=false EXPOSE_ORDERER=false NEUTRALIZE_NODE_INGRESSES=true \
     RUN_TESTS_MODE=patch .github/scripts/run-tests.sh
   (cd tutorial && ansible-playbook 01-create-ordering-organization-components.yml)
   ```
   Expected: the play ends `ok`, with one patch task per CA and orderer node,
   and a wait for the Ingress class.
4. Rerun step 2's `kubectl get` and `curl` lines. Expected: CR class `none`,
   Ingress class `none` for the CA and every orderer node, the console
   Ingress still `nginx`; the `curl` now prints `404`.
5. No restart:
   ```bash
   CA_CR=$(kubectl get ibpca -n "$NS" -o jsonpath='{.items[0].metadata.name}')
   kubectl get ibpca "$CA_CR" -n "$NS" -o json \
     | jq -r '.metadata.managedFields[] | select(.fieldsV1["f:spec"]["f:ingress"]["f:class"] != null) | "class set at \(.time)"'
   kubectl get pods -n "$NS" -l app="$CA_CR" \
     -o jsonpath='{.items[0].metadata.creationTimestamp}{"  restarts="}{.items[0].status.containerStatuses[0].restartCount}{"\n"}'
   ```
   Expected: the pod was created **before** the class was set, with
   `restarts=0`.
6. Clean up: `(cd tutorial && ansible-playbook 99-delete-ordering-organization-components.yml)`,
   then restore the vars files.
7. **Changed files vs the merge-conflict analysis.**
   ```bash
   git fetch origin && git diff --name-only "$BASE"...HEAD
   ```
   Expected: only the files of the 1.7 row of the
   [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
   If a file is not listed, check that it is not changed by the
   sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 4: 1.8, 1.5, 1.11.
   Look at their row of the table and at their open PR
   (`gh pr diff <PR number> --name-only`). If one of them changes it,
   raise a warning in the PR description: 1.7 must be merged before
   or after that sub-task (for example 1.8), not at the same time.
   In both cases, add the file to the 1.7 row of the table.


---

<a id="subtask-1-8"></a>
## Sub-task 1.8 — CoreDNS per-endpoint-type rewrites for the `expose-none` CI leg

**Scenarios:** [C](./SCENARIOS-MERMAID.md#scenario-c) only; [A](./SCENARIOS-MERMAID.md#scenario-a) and [B](./SCENARIOS-MERMAID.md#scenario-b) unchanged.

**Intent:** When `expose_*: false` and the node FQDNs are **not**
cluster-local (scenario C: `hlf_network_domain` left at `exposed_domain`, in
CI `<ip>.nip.io` or `localho.st`), the existing CoreDNS wildcard rewrites
(`rewrite name regex (.*)\.<domain> host.ingress.internal`) send every
component FQDN to the nginx ClusterIP, which silently routes traffic through
nginx when the intent is to bypass it. This sub-task adds **one rewrite rule
per endpoint type** (`ca`, `peer`, `orderer`, `operations`, `grpcweb`,
`admin`). Each rule maps
`<ns>-<cr>-<endpoint>.<hlf_network_domain>` to the per-endpoint Service
`<ns>-<cr>-<endpoint>.<ns>.svc.<cluster_domain>` created by sub-task 1.6.
Every endpoint therefore lands on its own native port: `-operations` reaches
9443/8443, `-grpcweb` reaches 7443 and `-admin` reaches 9443, never the API
port.

The dialled hostname stays the original FQDN, so TLS SANs remain valid and no
`csr_hosts` change or re-enrollment is needed.

**Decision tree** (URL-MANAGEMENT-NEW.md §4.5, decision D1):

| CA, peer and orderer all unexposed? | `hlf_network_domain == cluster_domain`? | CoreDNS |
|---|---|---|
| no | — | no endpoint rewrite (nodes go through nginx) |
| yes | yes (scenario B) | **no rewrite**: node FQDNs are `<service>.<ns>.svc.<cluster_domain>`, real Service FQDNs. Checked 2026-10-16 on a CA (URL-MANAGEMENT-NEW.md §9 check 1). |
| yes | no (scenario C) | one rewrite per endpoint type (this sub-task) |

**Design constraints:**
- The rules are applied by the CI bootstrap script
  (`.github/scripts/kind_with_nginx.sh`), **not by any Ansible role task**,
  consistent with MIGRATION-PLAN.md §1.1.
- They are written in `apply_coredns_override` at **cluster bootstrap,
  before any playbook runs**. The rules are patterns, so they do not depend
  on node names, and the console and the module health waits need them
  during `build_network.sh`.
- The existing `Corefile` content (the `localho.st` / nip.io wildcards to
  `host.ingress.internal`, the `hosts` block, the `kubernetes` plugin) is
  **kept**. The endpoint rules are inserted **before** the wildcards. With
  rewrite's default `stop` behaviour, the first matching rule wins, so
  endpoint FQDNs never reach the wildcard, while the console FQDN
  (`-console`, `-proxy`, matching no endpoint rule) still goes to nginx.
- `CLUSTER_DOMAIN` is not discovered: this function writes the `kubernetes`
  plugin line itself, so it uses the same `CLUSTER_DOMAIN` variable
  (default `cluster.local`) in both places.
- Each `name regex` rule has a matching `answer name` rule so that clients
  receive an answer for the name they asked for.

**Generated rule (one per endpoint type).** Example for namespace `default`,
HLF network domain `127-0-0-1.nip.io` and endpoint type `operations`:

```
rewrite stop {
    name regex ^(default-[a-z0-9]+-operations)\.127-0-0-1\.nip\.io {1}.default.svc.cluster.local
    answer name ^(default-[a-z0-9]+-operations)\.default\.svc\.cluster\.local {1}.127-0-0-1.nip.io
}
```

`[a-z0-9]+` matches the operator CR name: athena removes `-` and `_` from it
(URL-MANAGEMENT-EXISTING.md §3), so it never contains a dash. That prevents
`default-org1peer-operations` from being confused with a CR whose own name
ends in an endpoint word. Scenario B needs no such pattern.

**Expected outcomes:**
- In the `expose-none` leg (scenario C), the CoreDNS ConfigMap contains six
  endpoint rewrite blocks ahead of the existing wildcards. In the
  `expose-all` and `expose-none-internal` (scenario B) legs, it is unchanged.
- From an in-cluster pod, `nslookup <ns>-<peer>-operations.<domain>` returns
  the ClusterIP of Service `<ns>-<peer>-operations`, which is neither the
  nginx ClusterIP nor the `<ns>-<peer>-peer` ClusterIP.
- The console FQDN still resolves to the nginx ClusterIP.
- CoreDNS is restarted after the ConfigMap is applied.
- The function is the direct prototype for the equivalent function in
  `kind_with_envoy_gateway.sh` introduced in Step 2.

**Todo list:**
- [ ] In `.github/scripts/kind_with_nginx.sh`, add the inputs (they default to
  the values the tutorial already uses):
  ```bash
  NAMESPACE=${NAMESPACE:-default}
  CLUSTER_DOMAIN=${CLUSTER_DOMAIN:-cluster.local}
  # HLF_NETWORK_DOMAIN defaults to NIP_DOMAIN (= exposed domain) inside
  # apply_coredns_override
  ```
- [ ] Add a helper that prints the endpoint rewrite blocks:
  ```bash
  # coredns_endpoint_rewrites NAMESPACE HLF_NETWORK_DOMAIN CLUSTER_DOMAIN
  # One rewrite per endpoint type: <ns>-<cr>-<endpoint>.<domain> -> per-endpoint
  # Service <ns>-<cr>-<endpoint>.<ns>.svc.<cluster_domain> (MIGRATION-STEP-1 1.6).
  coredns_endpoint_rewrites() {
    local ns="$1" domain="$2" cluster_domain="$3"
    local domain_re="${domain//./\\.}"
    local cluster_domain_re="${cluster_domain//./\\.}"
    local endpoint
    for endpoint in ca peer orderer operations grpcweb admin; do
      printf '        rewrite stop {\n'
      printf '            name regex ^(%s-[a-z0-9]+-%s)\\.%s {1}.%s.svc.%s\n' \
        "${ns}" "${endpoint}" "${domain_re}" "${ns}" "${cluster_domain}"
      printf '            answer name ^(%s-[a-z0-9]+-%s)\\.%s\\.svc\\.%s {1}.%s\n' \
        "${ns}" "${endpoint}" "${ns}" "${cluster_domain_re}" "${domain}"
      printf '        }\n'
    done
  }
  ```
- [ ] In `apply_coredns_override`, compute the block only for scenario C
  (all nodes unexposed, HLF network domain not cluster-local), and insert it
  right after `ready`, before the existing wildcard rewrites:
  ```bash
  HLF_NETWORK_DOMAIN=${HLF_NETWORK_DOMAIN:-${NIP_DOMAIN}}
  ENDPOINT_REWRITES=""
  if [[ "${EXPOSE_CA:-true}" == "false" \
     && "${EXPOSE_PEER:-true}" == "false" \
     && "${EXPOSE_ORDERER:-true}" == "false" \
     && "${HLF_NETWORK_DOMAIN}" != "${CLUSTER_DOMAIN}" ]]; then
    ENDPOINT_REWRITES=$(coredns_endpoint_rewrites \
      "${NAMESPACE}" "${HLF_NETWORK_DOMAIN}" "${CLUSTER_DOMAIN}")
  fi
  ```
  ```
      .:53 {
          errors
          health {
             lameduck 5s
          }
          ready
  ${ENDPOINT_REWRITES}
          rewrite name regex (.*)\.localho\.st host.ingress.internal
          rewrite name regex (.*)\.${NIP_DOMAIN} host.ingress.internal
          hosts { ... unchanged ... }
          kubernetes ${CLUSTER_DOMAIN} in-addr.arpa ip6.arpa { ... unchanged ... }
          ...
  ```
- [ ] Run `bash -n .github/scripts/kind_with_nginx.sh`.
- [ ] Locally, run `kubectl -n kube-system get cm coredns -o yaml` after
  bootstrap with `EXPOSE_*=false` and check the six blocks and the unchanged
  wildcard / `hosts` lines.

**Relevant context:**
- Only CA, peer and orderer get endpoint rules. The console keeps resolving
  through the wildcard. With `expose_console: false`, the collection and the
  Job reach it through its in-cluster Service URL (sub-tasks 1.4 and 1.9),
  not through its FQDN.
- The rules are pattern-based, so they also cover nodes added later
  (`peers: N`, extra orderer nodes) without touching CoreDNS again.
- Partial exposure is not covered by these rules: see the last note of
  sub-task 1.6.
- Sub-task 1.10 assertions 3–6 verify this end to end. In scenario B
  (`HLF_NETWORK_DOMAIN == CLUSTER_DOMAIN`), assertion 6 checks plain
  kube-dns resolution instead of a rewrite.
- In CI, the variables reach `kind_with_nginx.sh` through `fvtest.yml`,
  changed in sub-task 1.9: this PR only changes the script.
- This script hard-codes `CLUSTER_DOMAIN` because it writes the Corefile
  itself. The Ansible side reads it from that same Corefile
  (`network_domains`, sub-task 1.1), so both always agree.

### ✋  check 1.8

**Proves:** the six rules exist only in scenario C, come before the
wildcards, and send each endpoint name to its own Service; the console name
still goes to nginx.

1. `bash -n .github/scripts/kind_with_nginx.sh`.
2. The helper alone, no cluster:
   ```bash
   bash -c 'source <(sed -n "/^coredns_endpoint_rewrites()/,/^}/p" .github/scripts/kind_with_nginx.sh)
            coredns_endpoint_rewrites default 127-0-0-1.nip.io cluster.local'
   ```
   Expected: six `rewrite stop` blocks (`ca`, `peer`, `orderer`,
   `operations`, `grpcweb`, `admin`); the `operations` one is the example
   above.
3. Scenario C cluster. The bootstrap recreates the cluster: everything on it
   is lost. Export the LDE §5 variables first.
   ```bash
   kind delete cluster
   EXPOSE_CA=false EXPOSE_PEER=false EXPOSE_ORDERER=false .github/scripts/kind_with_nginx.sh
   kubectl -n kube-system get cm coredns -o jsonpath='{.data.Corefile}'
   ```
   Expected: the six blocks right after `ready`, then the unchanged
   `localho.st` / nip.io wildcards, `hosts` block and
   `kubernetes cluster.local ...` line. The CoreDNS pods are younger than the
   change (`kubectl -n kube-system get pods -l k8s-app=kube-dns`).
4. A and B leave CoreDNS as today: repeat step 3 with no `EXPOSE_*` (A),
   then with `EXPOSE_*=false HLF_NETWORK_DOMAIN=cluster.local` (B).
   Expected: no `rewrite stop` block in either. End with the C cluster.
5. End to end in C: `.github/scripts/deploy-console.sh` (console exposed),
   then **Scenario C run**. Expected: exit 0.
6. Resolution from inside the cluster:
   ```bash
   PEER_OPS=$(kubectl get svc -n "$NS" -l "$SEL,fabric-ansible-collection/component=peer,fabric-ansible-collection/endpoint=operations" -o jsonpath='{.items[0].metadata.name}')
   kubectl get svc -n "$NS" "$PEER_OPS" "${PEER_OPS%-operations}-peer" -o custom-columns=NAME:.metadata.name,IP:.spec.clusterIP
   kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.spec.clusterIP}{"\n"}'
   indns "$PEER_OPS.$DOMAIN_A"
   indns "default-hlf-console-console.$DOMAIN_A"
   incluster curl -sk "https://$PEER_OPS.$DOMAIN_A/healthz"
   ```
   Expected: the operations name resolves to the ClusterIP of `$PEER_OPS`
   (not the `-peer` Service, not nginx); the console name resolves to the
   nginx ClusterIP; `/healthz` returns `{"status":"OK"}` through the
   original name.
7. **Destroy**.
8. **Changed files vs the merge-conflict analysis.**
   ```bash
   git fetch origin && git diff --name-only "$BASE"...HEAD
   ```
   Expected: only the files of the 1.8 row of the
   [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
   If a file is not listed, check that it is not changed by the
   sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 4: 1.7, 1.5, 1.11.
   Look at their row of the table and at their open PR
   (`gh pr diff <PR number> --name-only`). If one of them changes it,
   raise a warning in the PR description: 1.8 must be merged before
   or after that sub-task (for example 1.7), not at the same time.
   In both cases, add the file to the 1.8 row of the table.


---

<a id="subtask-1-9"></a>
## Sub-task 1.9 — CI workflow: `expose-none` matrix leg with in-cluster Ansible runner

**Scenarios:** [A](./SCENARIOS-MERMAID.md#scenario-a), [B](./SCENARIOS-MERMAID.md#scenario-b), [C](./SCENARIOS-MERMAID.md#scenario-c), end to end.

**Intent:** Extend `fvtest.yml` with matrix legs that validate the
unexposed scenarios on the nginx path. Their node FQDNs only resolve inside
the cluster: through CoreDNS rewrites in scenario C (sub-task 1.8), or
because they are Service FQDNs in scenario B. The GitHub Actions runner,
**outside** the KIND cluster, cannot resolve them: its `:443` traffic would
still reach nginx through the KIND host-port mapping, which is exactly the
path these legs must not use (confirmed locally on 2026-10-16: the module
health wait fails with `nodename nor servname provided`, finding F4).
These legs therefore run the tutorial Ansible playbooks **from inside the
cluster** using a Kubernetes Job.

| Leg | Scenario | `EXPOSE_*` | `HLF_NETWORK_DOMAIN` | CoreDNS rewrites | Runner |
|---|---|---|---|---|---|
| `expose-all` | A (everything exposed, no regression) | `true` | unset (= exposed domain) | none | Actions runner (unchanged) |
| `expose-none` | C (non-Kubernetes FQDNs) | `false` | unset (= exposed domain) | 6 per endpoint type | in-cluster Job |
| `expose-none-internal` | **B (Step 1 target)** | `false` | `cluster.local` | **none** | in-cluster Job |

**Expected outcomes:**
- `fvtest.yml` runs the three legs of the table above.
- `fail-fast: false` is set so every leg always completes.
- Both unexposed legs succeed: build, join, and deploy all exit 0.
- The `expose-none-internal` leg is the first end-to-end run of scenario B
  (URL-MANAGEMENT-NEW.md §9 check 5).

**Job design.** Three decisions settle the review's in-cluster Job findings
(read-only ConfigMap, flattened tree, 1 MiB limit, no ServiceAccount):

| # | Gap | Decision |
|---|---|---|
| J1 | How the tutorial reaches the Job | **Bake it into the runner image.** `tutorial/` (436 KB, ~80 files, one binary chaincode package `fabcar@1.0.0.tgz`) is copied into a writable directory of the image. No ConfigMap: no read-only mount, no flattening, no size limit. The playbooks write their `*.json` / `*.bin` identity and config files next to themselves (`tutorial/.gitignore`), which now just works. |
| J2 | ServiceAccount and RBAC | A dedicated ServiceAccount `ansible-runner` with a namespaced Role, plus a small Role in `kube-system` for the CoreDNS ConfigMap (manifest below). |
| J3 | Variable injection inside the Job | **The Job runs `run-tests.sh`**, not the tutorial scripts directly. It thus gets the same `yq` patching as the runner leg (connection, `expose_*`, domains, sub-task 1.3) and the same build → join → deploy → destroy sequence. `API_ENDPOINT` is `console_incluster_url`. |

**Runner image** — `.github/docker/ansible-runner/Dockerfile`. It extends the
collection image the repository already builds (`Dockerfile` at the root,
published by `.github/workflows/main.yml`). That image already has Ansible,
the collection, `kubernetes.core`, `fabric-sdk-py`, `openshift`, the Fabric
`peer`, `osnadmin` and `configtxlator` binaries, and an entrypoint that works
under a random UID. Only the test-only tools and files are added:

```dockerfile
# Built in CI from the repository root:
#   docker build -t fabric-ansible-collection:ci .
#   docker build -t ansible-runner:ci -f .github/docker/ansible-runner/Dockerfile .
ARG BASE_IMAGE=fabric-ansible-collection:ci
FROM ${BASE_IMAGE}
# Test-only tools: jq, shasum (TEST_RUN_ID stamping), pip for yq.
USER root
RUN microdnf install -y jq perl-Digest-SHA python3-pip && microdnf clean -y all
USER 7051
# Python yq (run-tests.sh uses `yq -yi`, which mikefarah's yq does not support).
RUN python3.9 -m pip install --user yq
# Writable copy of the tests: run-tests.sh does `cd tutorial` relative to the repo root.
COPY --chown=7051:0 .github/scripts /workspace/.github/scripts
COPY --chown=7051:0 tutorial /workspace/tutorial
USER root
RUN chmod -R g=u /workspace
USER 7051
WORKDIR /workspace
ENTRYPOINT [ "/docker-entrypoint.sh" ]
CMD [ ".github/scripts/run-tests.sh" ]
```

- The base image is built in the **same** CI run from the checked-out commit,
  so the Job tests the collection under test, not a published release.
- **Built and tried on 2026-10-16** (local KIND, arm64): both images build;
  the runner has `yq` (Python, `-yi` works), `jq`, `shasum`, `peer` 2.5.9,
  `ansible-playbook`, `kubernetes.core` 2.4.0; `/workspace/tutorial` is
  writable, also under a random UID with group 0 (OpenShift-style). Run as a
  pod with the `ansible-runner` ServiceAccount, it read `kube-system/coredns`
  through `kubernetes.core` (in-cluster token, no kubeconfig) and got HTTP
  200 from `console_incluster_url`. The base image has no `pip`, `jq` or
  `shasum`, hence the extra packages.
- Fabric version: the base image builds `peer` v2.5.9, while the runner leg
  installs 2.4.7 (`fvtest.yml`). Both talk to the same console-deployed
  nodes; align them in Step 0 (already listed in REVIEW-MIGRATION-PLAN-STEP-0.md).
- `run-tests.sh` must work without `_cfg/console-env.sh` (it already falls
  back to environment variables) and skip the `.venv` activation when absent.

**RBAC** — `.github/k8s/ansible-runner-rbac.yml`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata: {name: ansible-runner, namespace: default}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: ansible-runner, namespace: default}
rules:
  # Per-endpoint Services (sub-task 1.6)
  - apiGroups: [""]
    resources: [services]
    verbs: [get, list, create, patch, update, delete]
  # Node CRs: read for checks, patch for neutralize_node_ingresses (sub-task 1.7)
  - apiGroups: [ibp.com]
    resources: [ibpcas, ibppeers, ibporderers]
    verbs: [get, list, patch]
  # Wait for the Ingress class after neutralization (sub-task 1.7)
  - apiGroups: [networking.k8s.io]
    resources: [ingresses]
    verbs: [get, list]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: ansible-runner, namespace: default}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: ansible-runner}
subjects: [{kind: ServiceAccount, name: ansible-runner, namespace: default}]
---
# cluster_domain lookup (sub-task 1.1): read only the coredns ConfigMap
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: ansible-runner-coredns, namespace: kube-system}
rules:
  - apiGroups: [""]
    resources: [configmaps]
    resourceNames: [coredns]
    verbs: [get]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: ansible-runner-coredns, namespace: kube-system}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: ansible-runner-coredns}
subjects: [{kind: ServiceAccount, name: ansible-runner, namespace: default}]
```

**Checked on 2026-10-16** with `kubectl auth can-i --as
system:serviceaccount:default:ansible-runner`: allowed to create/delete
Services, patch `ibppeers`/`ibporderers`, read Ingresses and
`kube-system/configmaps/coredns`; denied any other `kube-system` ConfigMap,
creating `ibppeers` or Deployments, and reading Secrets. Both manifests pass
`kubectl apply --dry-run=server`.

The Job never creates CAs, peers or orderers itself: it asks the console's
REST API, and the console's deployer and the operator create them with their
own ServiceAccounts. `kubernetes.core` inside the pod authenticates with the
mounted ServiceAccount token (in-cluster config); no kubeconfig is copied in.

**Job** — `.github/k8s/ansible-runner-job.yml`:

```yaml
apiVersion: batch/v1
kind: Job
metadata: {name: ansible-runner, namespace: default}
spec:
  backoffLimit: 0                 # a failed run must fail the CI step, not retry
  activeDeadlineSeconds: 3600
  template:
    spec:
      serviceAccountName: ansible-runner
      restartPolicy: Never
      containers:
        - name: runner
          image: ansible-runner:ci
          imagePullPolicy: Never  # loaded with `kind load docker-image`
          envFrom:
            - configMapRef: {name: ansible-runner-env}   # created by the CI step below
          env:
            - name: API_SECRET
              valueFrom: {secretKeyRef: {name: ansible-runner-auth, key: API_SECRET}}
```

`ansible-runner-env` holds, from the leg's `$GITHUB_ENV`: `API_ENDPOINT`
(= `console_incluster_url`, `https://hlf-console.default.svc.<cluster_domain>:3000`),
`API_AUTHTYPE`, `API_KEY`, `K8S_NAMESPACE`, `INGRESS_TYPE`, `EXPOSE_CONSOLE`,
`EXPOSE_CA`, `EXPOSE_PEER`, `EXPOSE_ORDERER`, `EXPOSED_DOMAIN`,
`HLF_NETWORK_DOMAIN`, `CLUSTER_DOMAIN`, `NEUTRALIZE_NODE_INGRESSES`,
`WAIT_TIMEOUT`. The console serves
**HTTPS** on 3000 with a certificate for the `exposed_domain` host (checked
2026-10-16, check 4); the modules don't verify certificates, so this works.

**Teardown.** `run-tests.sh` destroys the network at the end
(`join_network.sh destroy`). The sub-task 1.10 assertions need the network
**alive**, so the first Job runs `run-tests.sh` with `KEEP_NETWORK=true`, and
a last CI step runs a second Job, `ansible-runner-destroy`, with
`RUN_TESTS_MODE=destroy` (both options added to `run-tests.sh` in sub-task
1.3). The CI step generates `TEST_RUN_ID` once and passes it to both Jobs.

**Todo list:**
- [ ] Add a `scenario` matrix dimension to the `fvtest` job in
  `.github/workflows/fvtest.yml` with values
  `[expose-all, expose-none, expose-none-internal]`. Set `fail-fast: false`
  on the matrix.
- [ ] For `expose-all`: set `EXPOSE_CONSOLE=true`, `EXPOSE_CA=true`,
  `EXPOSE_PEER=true`, `EXPOSE_ORDERER=true` in `$GITHUB_ENV`. Keep existing
  runner-side `run-tests.sh` invocation — this path is unchanged.
- [ ] For `expose-none`: set all four `EXPOSE_*` flags to `false` in
  `$GITHUB_ENV`, and `EXPOSED_DOMAIN` to the console domain: the organization
  roles build the node FQDNs of scenario C from it (sub-task 1.1). Keep
  `INGRESS_TYPE=nginx`.
- [ ] In every leg, export `EXPOSE_*`, `NAMESPACE`, `HLF_NETWORK_DOMAIN` and
  `CLUSTER_DOMAIN` **before** `kind_with_nginx.sh`: since sub-task 1.8 the
  script reads them to write the CoreDNS rules, before any playbook runs.
  They must match what `run-tests.sh` writes to `common-vars.yml` (sub-task
  1.3).
- [ ] For `expose-none-internal`: same, plus
  `HLF_NETWORK_DOMAIN=cluster.local` and `CLUSTER_DOMAIN=cluster.local`,
  exported before `kind_with_nginx.sh` and the console deployment (the
  console must be **created** with `spec.deployer.domain`, finding F1).
- [ ] Create `.github/docker/ansible-runner/Dockerfile`,
  `.github/k8s/ansible-runner-rbac.yml` and `.github/k8s/ansible-runner-job.yml`
  as above.
- [ ] Add the following CI steps, each guarded by
  `if: matrix.scenario != 'expose-all'`:
  1. **Build and load the images**:
     ```bash
     docker build -t fabric-ansible-collection:ci .
     docker build -t ansible-runner:ci -f .github/docker/ansible-runner/Dockerfile .
     kind load docker-image ansible-runner:ci
     ```
  2. **Apply RBAC**: `kubectl apply -f .github/k8s/ansible-runner-rbac.yml`
  3. **Create the Job inputs**:
     ```bash
     kubectl create configmap ansible-runner-env \
       --from-literal=API_ENDPOINT="https://${CONSOLE_NAME}.${K8S_NAMESPACE}.svc.${CLUSTER_DOMAIN:-cluster.local}:3000" \
       --from-literal=API_AUTHTYPE="${API_AUTHTYPE}" --from-literal=API_KEY="${API_KEY}" \
       --from-literal=K8S_NAMESPACE="${K8S_NAMESPACE}" --from-literal=KEEP_NETWORK=true \
       --from-literal=TEST_RUN_ID="$(openssl rand -hex 20)" \
       --from-literal=INGRESS_TYPE="${INGRESS_TYPE}" \
       --from-literal=EXPOSE_CONSOLE="${EXPOSE_CONSOLE}" --from-literal=EXPOSE_CA="${EXPOSE_CA}" \
       --from-literal=EXPOSE_PEER="${EXPOSE_PEER}" --from-literal=EXPOSE_ORDERER="${EXPOSE_ORDERER}" \
       --from-literal=EXPOSED_DOMAIN="${EXPOSED_DOMAIN:-}" \
       --from-literal=HLF_NETWORK_DOMAIN="${HLF_NETWORK_DOMAIN:-}" \
       --from-literal=CLUSTER_DOMAIN="${CLUSTER_DOMAIN:-}" \
       --from-literal=NEUTRALIZE_NODE_INGRESSES="${NEUTRALIZE_NODE_INGRESSES:-}" \
       --from-literal=WAIT_TIMEOUT=1800
     kubectl create secret generic ansible-runner-auth --from-literal=API_SECRET="${API_SECRET}"
     ```
  4. **Run the Job**: `kubectl apply -f .github/k8s/ansible-runner-job.yml`
  5. **Wait for it** (fails fast on a failed Job):
     ```bash
     kubectl wait --for=jsonpath='{.status.conditions[?(@.status=="True")].type}'=Complete \
       --timeout=60m job/ansible-runner \
     || { kubectl get job ansible-runner -o jsonpath='{.status.conditions}'; exit 1; }
     ```
  6. **Retrieve logs** (`if: always() && matrix.scenario != 'expose-all'`):
     `kubectl logs job/ansible-runner --all-containers`
  7. **Reachability assertions** (sub-task 1.10), network still alive.
  8. **Destroy** (`if: always() && matrix.scenario != 'expose-all'`): a
     second Job, `ansible-runner-destroy`, same image and inputs plus
     `RUN_TESTS_MODE=destroy`; wait for it and print its logs like steps 5–6.
- [ ] Add `name: FV test (nginx / ${{ matrix.scenario }})` to the job.
- [ ] Run `yamllint` on the workflow and the two manifests.
- [ ] Try the Job locally first on the KIND cluster used for the
  URL-MANAGEMENT-NEW.md checks (scenario C needs no console change; scenario B
  needs the console re-created with `spec.deployer.domain`).

**Relevant context:**
- The `expose-all` leg is entirely unaffected by this sub-task — the `if:`
  conditions ensure the Job steps are skipped when `matrix.scenario == 'expose-all'`.
- A `kubectl wait --for=condition=complete` alone waits the full timeout
  when the Job fails; the `jsonpath` form above returns as soon as the Job
  has any final condition, and the `||` branch reports it.
- The Job image must be available inside the KIND cluster (`kind load
  docker-image`, `imagePullPolicy: Never`).
- Each Job starts from a fresh copy of the image, so nothing patched by the
  first Job survives into the destroy Job. Both therefore run `run-tests.sh`,
  which re-applies the same patching, with the **same** `TEST_RUN_ID` taken
  from `ansible-runner-env`: the randomised org and node names (Step 0
  stamping) are identical, and the destroy finds what the first Job
  created.
- Gateway API (`ingress_type: gateway-api`) matrix legs are **not** added in
  this step; leave a comment stub for Step 2.
- Reference full matrix design: MIGRATION-PLAN.md §5.3.4.

### ✋  check 1.9

**Proves:** the runner image and its RBAC work, the Job runs the whole test
suite from inside the cluster in B and in C, and the three CI legs pass.
Steps 1 to 7 run locally, before anything is pushed.

1. `yamllint .github/workflows/fvtest.yml .github/k8s/`; build both images
   (CI step 1, without `kind load` yet).
2. Scenario B cluster and console. `EXPOSED_DOMAIN` stays unset, as in CI:
   the console name stays under the nip.io domain.
   ```bash
   export EXPOSE_CONSOLE=false EXPOSE_CA=false EXPOSE_PEER=false EXPOSE_ORDERER=false
   export HLF_NETWORK_DOMAIN=cluster.local CLUSTER_DOMAIN=cluster.local
   kind delete cluster && .github/scripts/kind_with_nginx.sh && .github/scripts/deploy-console.sh
   kubectl get ibpconsole hlf-console -n "$NS" -o jsonpath='{.spec.deployer.domain}{"\n"}'
   ```
   Expected: `default.svc.cluster.local`: the console is **created** with
   it (finding F1).
3. Load the image, apply the RBAC (CI steps 1 and 2), check the permissions:
   ```bash
   kind load docker-image ansible-runner:ci
   kubectl apply -f .github/k8s/ansible-runner-rbac.yml
   SA=system:serviceaccount:default:ansible-runner
   kubectl auth can-i get configmap/coredns -n kube-system --as "$SA"     # yes
   kubectl auth can-i create services -n default --as "$SA"               # yes
   kubectl auth can-i patch ibppeers.ibp.com -n default --as "$SA"        # yes
   kubectl auth can-i get secrets -n default --as "$SA"                   # no
   kubectl auth can-i get configmap/kube-proxy -n kube-system --as "$SA"  # no
   ```
4. Run the Job: CI steps 3 to 6, with `CONSOLE_NAME=hlf-console` and
   `K8S_NAMESPACE=default`. Expected: the wait ends with `Complete`; the
   logs show build, join and deploy finishing, and
   `hlf_node_domain: default.svc.cluster.local`.
5. Destroy Job (CI step 8). Expected: `Complete`;
   `kubectl get ibpca,ibppeer,ibporderer -n "$NS"` and
   `kubectl get svc -n "$NS" -l "$SEL"` find nothing. Before the next run,
   delete the Jobs, `ansible-runner-env` and `ansible-runner-auth`.
6. Scenario C: steps 2 to 5 again with
   `unset HLF_NETWORK_DOMAIN CLUSTER_DOMAIN`. Expected: `Complete` both
   times; `hlf_node_domain` is the nip.io domain; CoreDNS has the six rules.
7. Scenario B with `NEUTRALIZE_NODE_INGRESSES=true` (the full run deferred
   from 1.7). Expected: `Complete`; before the destroy Job,
   `kubectl get ingress -n "$NS"` shows class `none` for every node Ingress.
8. On GitHub Actions, for the pushed branch:
   ```bash
   gh run list --workflow fvtest.yml --branch "$(git branch --show-current)" --limit 1
   gh run view <run id>
   ```
   Expected: three jobs, `FV test (nginx / expose-all)`,
   `FV test (nginx / expose-none)` and `FV test (nginx / expose-none-internal)`,
   all green; the Job steps are skipped in `expose-all`.
9. **Changed files vs the merge-conflict analysis.**
   ```bash
   git fetch origin && git diff --name-only "$BASE"...HEAD
   ```
   Expected: only the files of the 1.9 row of the
   [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
   If a file is not listed, check that it is not changed by the
   sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 5: 1.11.
   Look at their row of the table and at their open PR
   (`gh pr diff <PR number> --name-only`). If one of them changes it,
   raise a warning in the PR description: 1.9 must be merged before
   or after that sub-task (for example 1.11), not at the same time.
   In both cases, add the file to the 1.9 row of the table.


---

<a id="subtask-1-10"></a>
## Sub-task 1.10 — In-cluster service reachability assertions

**Scenarios:** [B](./SCENARIOS-MERMAID.md#scenario-b), [C](./SCENARIOS-MERMAID.md#scenario-c).

**Intent:** Define explicit, automatable assertions for the unexposed CI
legs (`expose-none`, `expose-none-internal`) that verify in-cluster
reachability without relying on the external runner's network access. All assertions run as ephemeral pods via
`kubectl run --rm -i --restart=Never` and execute as a CI step **after** the
in-cluster Ansible Job from sub-task 1.9 completes.

**Expected outcomes:**
- Six named assertions all pass in both unexposed legs.
- The `expose-all` leg is unaffected (assertions are guarded by
  `if: matrix.scenario != 'expose-all'`).
- Any single failing assertion produces a clear, actionable error message
  identifying the misconfigured resource.

**Todo list:**

- [ ] **Assertion 1 — Unexposed Ingress objects are not served by nginx.**
  The operator **always** creates the console and node Ingress objects (B2;
  no setting turns that off), so "no Ingress object" can never hold. The
  console Ingress must have class `unexposed_ingress_class` (sub-task 1.5);
  the node Ingress hosts must be under `hlf_node_domain`, and, with
  `neutralize_node_ingresses: true` (sub-task 1.7), their class too:
  ```bash
  NS="${NAMESPACE:-default}"; UNSERVED="${UNEXPOSED_INGRESS_CLASS:-none}"
  cls=$(kubectl get ingress -n "$NS" "$CONSOLE_NAME" -o jsonpath='{.spec.ingressClassName}')
  [ "$cls" = "$UNSERVED" ] || { echo "console Ingress class '$cls', expected '$UNSERVED'"; exit 1; }
  code=$(curl -sk -o /dev/null -w '%{http_code}' "$CONSOLE_URL/ak/api/v3/health")
  [ "$code" = 404 ] || { echo "console still served by nginx (HTTP $code)"; exit 1; }
  ```
  _Failure indicates_: the console CR did not get `spec.ingress.class`, or
  nginx serves the class (checked 2026-10-16: it does not, check 2).

- [ ] **Assertion 2 — Console ClusterIP Service responds** at
  `console_incluster_url` (HTTPS, Basic auth):
  ```bash
  kubectl run curl-console \
    --image=curlimages/curl:8.10.1 --restart=Never --rm -i --quiet \
    --namespace "$NS" --command -- \
    curl -sfk -u "$API_KEY:$API_SECRET" \
    "https://${CONSOLE_NAME}.${NS}.svc.${CLUSTER_DOMAIN:-cluster.local}:3000/ak/api/v3/health"
  ```
  _Failure indicates_: the console pod is not running, the Service selector is
  wrong, or the credentials are wrong (401).

- [ ] **Assertions 3–6 — common preamble.** Endpoints are discovered from
  the labelled Services of sub-task 1.6, so no node name is hardcoded:
  ```bash
  NS="${NAMESPACE:-default}"
  # hlf_node_domain: <ns>.svc.<cluster_domain> in scenario B, the HLF network domain otherwise
  if [ "${HLF_NETWORK_DOMAIN:-}" = "${CLUSTER_DOMAIN:-cluster.local}" ]; then
    DOMAIN="${NS}.svc.${CLUSTER_DOMAIN:-cluster.local}"
  else
    DOMAIN="${HLF_NETWORK_DOMAIN:-${EXPOSED_DOMAIN}}"
  fi
  SEL=app.kubernetes.io/managed-by=fabric-ansible-collection
  svcs_of() {  # svcs_of <endpoint-type> -> Service names
    kubectl get svc -n "$NS" -l "$SEL,fabric-ansible-collection/endpoint=$1" \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
  }
  incluster() {  # incluster <name> <image> <cmd...>
    kubectl run "$1" --image="$2" --restart=Never --rm -i --quiet \
      --namespace "$NS" --command -- "${@:3}"
  }
  ```

- [ ] **Assertion 3 — One Service per endpoint, correct target port, ready
  backends.** Static check of the endpoint → port mapping table (sub-task
  1.6). It proves that `-operations`, `-grpcweb` and `-admin` do not
  target the API port:
  ```bash
  declare -A want=( [ca/ca]=7054 [ca/operations]=9443
                    [peer/peer]=7051 [peer/operations]=9443 [peer/grpcweb]=7443
                    [orderer/orderer]=7050 [orderer/admin]=9443
                    [orderer/operations]=8443 [orderer/grpcweb]=7443 )
  for key in "${!want[@]}"; do
    comp="${key%/*}" ep="${key#*/}"
    names=$(kubectl get svc -n "$NS" \
      -l "$SEL,fabric-ansible-collection/component=$comp,fabric-ansible-collection/endpoint=$ep" \
      -o jsonpath='{.items[*].metadata.name}')
    [ -n "$names" ] || { echo "No $comp '$ep' Service found"; exit 1; }
    for svc in $names; do
      port=$(kubectl get svc -n "$NS" "$svc" -o jsonpath='{.spec.ports[?(@.port==443)].targetPort}')
      [ "$port" = "${want[$key]}" ] \
        || { echo "$svc: 443 -> $port, expected ${want[$key]}"; exit 1; }
      addrs=$(kubectl get endpoints -n "$NS" "$svc" -o jsonpath='{.subsets[*].addresses[*].ip}')
      [ -n "$addrs" ] \
        || { echo "$svc has no ready backend (selector assumption S3?)"; exit 1; }
    done
  done
  ```
  The `orderer/admin` entry is expected only on Fabric ≥ 2.4.1 (operator
  gate). Drop it from `want` for older pinned versions.
  _Failure indicates_: sub-task 1.6 skipped a component or endpoint type, or
  used a wrong target port, or the selector (S3) matches no pod.

- [ ] **Assertion 4 — Every operations endpoint answers `/healthz` on `:443`
  through its FQDN.** This exercises CoreDNS rewrite + per-endpoint Service
  + port 9443/8443, the path used by the console status checks and the
  collection's health waits:
  ```bash
  urls=$(svcs_of operations | sed "s|.*|https://&.${DOMAIN}/healthz|")
  incluster healthz curlimages/curl:8.10.1 sh -c '
    for u in '"$(echo $urls)"'; do
      curl -sk --connect-timeout 5 "$u" | grep -q "\"status\":\"OK\"" \
        || { echo "FAIL $u"; exit 1; }
    done'
  ```
  _Failure indicates_: the `operations` rewrite is missing, the Service
  targets the API port, or the node is unhealthy.

- [ ] **Assertion 5 — API, CA, grpcweb and admin endpoints accept TLS on
  `:443` through their FQDNs.** The CA `-ca` endpoint must return `/cainfo`
  JSON. For gRPC, grpcweb and the mTLS-only admin endpoint, a TLS-level
  answer is enough: curl exit 0, 35 (handshake alert, e.g. a client
  certificate is required) or 56. Exits 6, 7 and 28 (DNS failure, connection
  refused, timeout) fail. Port correctness is already proven by assertion 3:
  ```bash
  ca_urls=$(svcs_of ca | sed "s|.*|https://&.${DOMAIN}/cainfo|")
  tls_urls=$(for ep in peer orderer grpcweb admin; do svcs_of "$ep"; done \
    | sed "s|.*|https://&.${DOMAIN}/|")
  incluster tls-check curlimages/curl:8.10.1 sh -c '
    for u in '"$(echo $ca_urls)"'; do
      curl -sk --connect-timeout 5 "$u" | grep -q '"CAName"' || { echo "FAIL $u"; exit 1; }
    done
    for u in '"$(echo $tls_urls)"'; do
      rc=0; curl -sk -o /dev/null --connect-timeout 5 "$u" || rc=$?
      case $rc in 0|35|56) ;; *) echo "FAIL $u (curl exit $rc)"; exit 1;; esac
    done'
  ```
  _Failure indicates_: a rewrite for that endpoint type is missing, or the
  Service has no backend.

- [ ] **Assertion 6 — Each endpoint FQDN resolves to its own Service's
  ClusterIP** (not nginx, and not a sibling endpoint's Service). In scenario
  C this confirms the sub-task 1.8 rewrites; in scenario B the FQDN is the
  Service FQDN itself, so it confirms plain kube-dns resolution:
  ```bash
  pairs=$(kubectl get svc -n "$NS" -l "$SEL" \
    -o jsonpath='{range .items[*]}{.metadata.name}={.spec.clusterIP}{" "}{end}')
  incluster dns-check busybox:1.36.1 sh -c '
    for p in '"${pairs}"'; do
      fqdn="${p%%=*}.'"${DOMAIN}"'"; want="${p#*=}"
      got=$(nslookup "$fqdn" | awk "/^Address/ {a=\$2} END {print a}")
      [ "$got" = "$want" ] || { echo "FAIL $fqdn -> $got, expected $want"; exit 1; }
    done'
  ```
  _Failure indicates_: in scenario C, `coredns_endpoint_rewrites` was not
  emitted (check the `EXPOSE_*` / `HLF_NETWORK_DOMAIN` env passed to
  `kind_with_nginx.sh`), the `[a-z0-9]+` CR pattern does not match, or
  CoreDNS was not restarted. In scenario B, the console was not created
  with `spec.deployer.domain` (finding F1).

- [ ] Put the six assertions in one script,
  `.github/scripts/verify-unexposed-reachability.sh`, so they also run from a
  laptop against the local KIND cluster ( check 1.10). It prints each
  assertion name, then `OK` or the failure message.
- [ ] Call it from a single `"Verify unexposed reachability"` step in
  `fvtest.yml`, conditioned on `if: matrix.scenario != 'expose-all'`.
- [ ] Export `EXPOSED_DOMAIN` (the console domain, `<ip>.nip.io` in CI) in
  both unexposed legs: in scenario C the preamble falls back to it, because
  `HLF_NETWORK_DOMAIN` is unset there.
- [ ] Use `set -euo pipefail` at the top of the script so the
  first failing assertion aborts the step. Commands whose non-zero exit is
  expected are wrapped as `rc=0; cmd || rc=$?`.

**Relevant context:**
- `CONSOLE_NAME`, `CONSOLE_URL`, `API_KEY`, `API_SECRET` come from
  `_cfg/console-env.sh` / the CI environment (`deploy-console.sh`).
- Assertions 3–6 cover **every** endpoint of **every** node, discovered from
  the `fabric-ansible-collection/*` labels. Adding peers or orderer nodes
  needs no change here.
- Sub-tasks 1.6 and 1.8 must be complete before assertions 3–6 can pass.

### ✋  check 1.10

**Proves:** the six assertions pass on a correct network, and a broken
Service or a served console makes the right assertion fail with a clear
message.

1. `bash -n .github/scripts/verify-unexposed-reachability.sh` (and
   `shellcheck` when installed).
2. Positive, scenario B: rebuild a B network with the Job ( check 1.9,
   steps 2 to 4, without the destroy Job), then:
   ```bash
   CONSOLE_NAME=hlf-console CONSOLE_URL="https://default-hlf-console-console.$DOMAIN_A" \
   EXPOSED_DOMAIN="$DOMAIN_A" HLF_NETWORK_DOMAIN=cluster.local CLUSTER_DOMAIN=cluster.local \
   .github/scripts/verify-unexposed-reachability.sh
   ```
   Expected: the six assertion names, each followed by `OK`; exit 0.
3. Negative, wrong target port:
   ```bash
   PEER_OPS=$(kubectl get svc -n "$NS" -l "$SEL,fabric-ansible-collection/component=peer,fabric-ansible-collection/endpoint=operations" -o jsonpath='{.items[0].metadata.name}')
   kubectl patch svc "$PEER_OPS" -n "$NS" --type=json -p '[{"op":"replace","path":"/spec/ports/0/targetPort","value":7051}]'
   ```
   Rerun step 2. Expected: assertion 3 fails with
   `<PEER_OPS>: 443 -> 7051, expected 9443`. Patch the port back to `9443`
   and rerun: all `OK`.
4. Negative, console served again:
   `kubectl patch ibpconsole hlf-console -n "$NS" --type merge -p '{"spec":{"ingress":{"class":"nginx"}}}'`.
   Once `kubectl get ingress -n "$NS"` shows `nginx` for the console, rerun
   step 2. Expected: assertion 1 fails, naming the class. Patch it back to
   `none`.
5. Scenario C: the positive run on a C network ( check 1.9, step 6),
   without `HLF_NETWORK_DOMAIN` and `CLUSTER_DOMAIN`. Expected: exit 0;
   assertion 6 now proves the rewrites.
6. Run the destroy Job. On GitHub Actions, the "Verify unexposed
   reachability" step is green in both unexposed legs and skipped in
   `expose-all`.
7. **Changed files vs the merge-conflict analysis.**
   ```bash
   git fetch origin && git diff --name-only "$BASE"...HEAD
   ```
   Expected: only the files of the 1.10 row of the
   [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
   If a file is not listed, check that it is not changed by the
   sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 6: 1.12, 1.11.
   Look at their row of the table and at their open PR
   (`gh pr diff <PR number> --name-only`). If one of them changes it,
   raise a warning in the PR description: 1.10 must be merged before
   or after that sub-task (for example 1.12), not at the same time.
   In both cases, add the file to the 1.10 row of the table.


---

<a id="subtask-1-11"></a>
## Sub-task 1.11 — Tutorial: nginx expose-all scenario (no-regression)

**Scenarios:** [A](./SCENARIOS-MERMAID.md#scenario-a).

**Intent:** Update or create a tutorial that explicitly demonstrates the
current default nginx deployment (all services exposed). This is a reference
baseline that confirms no regression and documents the `expose_*` variable schema
for users.

**Expected outcomes:**
- Tutorial page at `docs/source/tutorials/nginx-expose-all.rst` (new) or updated
  inline in `docs/source/tutorials/oss-installing.rst` with a dedicated section.
- Documents `ingress_type: nginx` (default), `expose_console: true`, and the
  other `expose_*: true` defaults.
- Documents `exposed_domain` (and the `console_domain` deprecation),
  `hlf_network_domain` (default: `exposed_domain`) and `cluster_domain`.
- Shows how to set these variables in a vars file (e.g. `common-vars.yml`) or
  via `ansible-playbook -e @vars.yml`.
- Documents the existing `kubectl get ingress` verification steps.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Decide whether to add a new page or a section in the existing
  `oss-installing.rst`; document the decision in the plan file.
- [ ] Add a "Variables reference" table listing all `expose_*`,
  `ingress_type`, domain variables, `unexposed_ingress_class` and
  `neutralize_node_ingresses` with their defaults and effects (sub-task 1.1).
- [ ] Add a verification step showing `kubectl get ingress -n <namespace>` output
  when all services are exposed.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Files to update: `docs/source/tutorials/oss-installing.rst`,
  `docs/source/tutorials/hlfsupport-installing.rst`.
- Role reference files: `docs/source/roles/fabric-operator-crds.rst`,
  `docs/source/roles/fabric-console.rst`.

### ✋  check 1.11

**Proves:** the page builds cleanly, its variable table matches the role,
and its commands work as written.

1. `make -C docs html 2>&1 | grep -iE 'warning|error'`: no output.
2. Every key of `roles/network_domains/defaults/main.yml`
   (`yq 'keys' roles/network_domains/defaults/main.yml`) is in the page's
   variables table, with the same default.
3. Someone who did not write the page follows it on a fresh KIND cluster,
   copying the commands as written. Expected: the results the page shows,
   including the `kubectl get ingress` output (class `nginx` everywhere).
4. **Changed files vs the merge-conflict analysis.**
   ```bash
   git fetch origin && git diff --name-only "$BASE"...HEAD
   ```
   Expected: only the files of the 1.11 row of the
   [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
   If a file is not listed, check that it is not changed by the
   sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 2 and later: every sub-task still open.
   Look at their row of the table and at their open PR
   (`gh pr diff <PR number> --name-only`). If one of them changes it,
   raise a warning in the PR description: 1.11 must be merged before
   or after that sub-task (for example 1.x), not at the same time.
   In both cases, add the file to the 1.11 row of the table.


---

<a id="subtask-1-12"></a>
## Sub-task 1.12 — Tutorial: nginx no-expose scenario

**Scenarios:** [B](./SCENARIOS-MERMAID.md#scenario-b).

**Intent:** Create a new tutorial that demonstrates the extreme opposite scenario:
deploying a Hyperledger Fabric network on a single cluster where no service is
exposed externally through the NGINX ingress controller. This is the
tutorial of scenario B. (PRE-ANALYSIS.md calls the same use case "topology
A — in-cluster": its letters are about where Ansible runs, not the ones of
this plan.)

**Expected outcomes:**
- New tutorial page at
  `docs/source/tutorials/nginx-no-expose.rst`.
- Demonstrates scenario B in a vars file: `expose_console: false`,
  `expose_ca: false`, `expose_peer: false`, `expose_orderer: false`,
  `exposed_domain: <public domain>`, `hlf_network_domain: cluster.local`.
- Explains that the console URL is still built from `exposed_domain`, and
  that its TLS certificate already covers it, so the console can be exposed
  later by hand (nginx Ingress or Gateway API `TLSRoute`, URL-MANAGEMENT-NEW.md
  §5.3), or by re-running the console role with `expose_console: true`.
- Explains that node FQDNs are Kubernetes Service FQDNs
  (`<ns>-<cr>-<endpoint>.<ns>.svc.cluster.local`), served by the per-endpoint
  Services, with no CoreDNS change.
- Shows `kubectl get ingress -n <namespace>`: the Ingress objects exist
  (the operator always creates them) with class `none` for the console, and
  for the nodes when `neutralize_node_ingresses: true`.
- Added to the `toctree` in `docs/source/index.rst`.
- `make -C docs html` builds without warnings.

**Todo list:**
- [ ] Create `docs/source/tutorials/nginx-no-expose.rst` with:
  - Prerequisites section (nginx ingress controller installed but routes not
    required for in-cluster use).
  - Example vars file for scenario B (above) and `ingress_type: nginx`.
  - Step-by-step playbook execution using `ansible-playbook -e @no-expose-vars.yml`.
  - Verification: console notice message in the playbook output; console
    URL through nginx returns 404; `console_incluster_url` answers from a
    pod.
  - Requirement: the organization playbooks must run inside the cluster
    (sub-task 1.9) because node FQDNs only resolve there.
  - Explanation of when to use this scenario (single-cluster bootstrap, GitOps
    lead-org setup, development environment).
- [ ] Add `nginx-no-expose` to the `toctree` in `docs/source/index.rst`.
- [ ] Run `make -C docs html` and fix any warnings.

**Relevant context:**
- Why run everything in-cluster (PRE-ANALYSIS.md topology A): PRE-ANALYSIS.md
  §2.4 and §2.5.
- Console notice message implementation: sub-task 1.4 above.
- In-cluster console URL: `console_incluster_url`,
  `https://<console>.<namespace>.svc.<cluster_domain>:3000`.

### ✋  check 1.12

**Proves:** the page builds, is reachable from the index, and lets a reader
reproduce scenario B.

1. `make -C docs html 2>&1 | grep -iE 'warning|error'`: no output;
   `nginx-no-expose` appears in the navigation.
2. Someone who did not write the page follows it on a fresh KIND cluster,
   with the playbooks running in-cluster (the Job of 1.9). Expected, as the
   page says: the console notice in the output; the console URL through
   nginx answers `404`; `console_incluster_url` answers from a pod (`401`
   without credentials); `kubectl get ingress -n default` shows class `none`
   for the console; every node URL ends with `.default.svc.cluster.local`.
3. The page uses this plan's scenario letter (B) and does not call it
   "scenario A".
4. **Changed files vs the merge-conflict analysis.**
   ```bash
   git fetch origin && git diff --name-only "$BASE"...HEAD
   ```
   Expected: only the files of the 1.12 row of the
   [files table](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#files-changed-by-each-sub-task).
   If a file is not listed, check that it is not changed by the
   sub-tasks running in parallel in [wave](./MIGRATION-STEP-1-SUBSTEP-MERGE-CONFLICTS-RISK-ANALYSIS.md#waves) 6: 1.10, 1.11.
   Look at their row of the table and at their open PR
   (`gh pr diff <PR number> --name-only`). If one of them changes it,
   raise a warning in the PR description: 1.12 must be merged before
   or after that sub-task (for example 1.10), not at the same time.
   In both cases, add the file to the 1.12 row of the table.


---

## Acceptance criteria for Step 1

A Step 1 delivery is considered complete when all of the following pass:

1. `ansible-lint` and `yamllint` pass on all modified files.
2. `run-tests.sh` correctly injects all `ingress_type` and `expose_*` variables into `common-vars.yml` (and passes `bash -n` validation).
3. `fvtest.yml` matrix runs three legs: `nginx/expose-all`,
   `nginx/expose-none` (scenario C) and `nginx/expose-none-internal`
   (scenario B); all complete successfully with `fail-fast: false`.
4. The `nginx/expose-all` leg is byte-for-byte equivalent in test coverage to
   the pre-Step-1 single-leg run — no existing test scenario has been removed
   or weakened.
5. Both unexposed legs run the tutorial playbooks inside the KIND
   cluster via a Kubernetes Job (sub-task 1.9) and all six reachability
   assertions pass (sub-task 1.10): the console Ingress is not served by
   nginx; console health endpoint returns HTTP 200 in-cluster; one Service per
   endpoint exists with the expected `443 → targetPort` and ready backends;
   every operations FQDN answers `/healthz` on `:443`; every API, CA, grpcweb
   and admin FQDN accepts TLS on `:443`; each endpoint FQDN resolves to its
   own Service's ClusterIP.
6. In `expose-none` mode the collection creates **one ClusterIP Service per
   endpoint** (CA: `ca`, `operations`; peer: `peer`, `operations`, `grpcweb`;
   orderer: `orderer`, `admin`, `operations`, `grpcweb`), each mapping `443`
   to that endpoint's native port (sub-task 1.6). In scenario C, **one
   CoreDNS rewrite per endpoint type** (sub-task 1.8); in scenario B, **no
   CoreDNS change**. The operator's own Services are left unmodified, and
   console registry entries are not mutated. Every node URL returned by the
   console passes V5.
7. Domain handling (sub-tasks 1.1, 1.2, 1.5), all covered by the
   `network_domains` tests:
   - No new variable set: `hlf_node_domain = console_domain`, the rendered
     `IBPConsole` equals today's (minus the duplicate `networkinfo:` key),
     nothing is read from the cluster, and a `console_domain` deprecation
     notice is printed.
   - `hlf_network_domain: <cluster_domain>` with CA, peer and orderer
     unexposed: `hlf_network_domain_is_cluster_local` is true, the console
     gets `spec.deployer.domain: <namespace>.svc.<cluster_domain>`, node URLs
     are Service FQDNs, and no CoreDNS rewrite is applied.
   - The same with any of `expose_ca/peer/orderer: true` fails immediately,
     listing the flags (V3). `expose_console: true` is allowed.
   - A sub-zone of the cluster domain (e.g. `default.svc.cluster.local`) as
     `hlf_network_domain` fails, naming `<cluster_domain>` as the value to use
     (V2); an `exposed_domain` inside the cluster domain fails (V1).
   - `exposed_domain` and `console_domain` set to different values fail.
   - The cluster domain is looked up, best effort, in the
     `kube-system/coredns` ConfigMap via `k8s_info` (no `kubectl exec`),
     whenever it matters. When found, it is used if `cluster_domain` is
     empty, and a different user-set `cluster_domain` fails the play naming
     both values. When not found, a user-set `cluster_domain` is trusted with
     a warning, and an empty one fails the play asking the user to set it.
8. `docs/source` builds without warnings (`make -C docs html`).
9. No Gateway API CRD, template, task, or Kubernetes resource is introduced —
   the Gateway API path is entirely absent from the codebase at this stage.
10. Every  check, 1.1 to 1.12, has been run, in order: none was skipped to
    start a later sub-task.
