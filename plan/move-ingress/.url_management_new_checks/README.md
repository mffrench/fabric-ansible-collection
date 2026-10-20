# URL-MANAGEMENT-NEW §9 checks (2026-10-16)

Artefacts of the checks recorded in [`../URL-MANAGEMENT-NEW.md`](../URL-MANAGEMENT-NEW.md) §9.
Local KIND cluster (`kindest/node:v1.25.3`, macOS arm64), nginx, namespace `default`,
console `hlf-console`, domain `127-0-0-1.nip.io`. Test resources were deleted afterwards.

## Reproduce

```bash
export KUBECONFIG="$PWD/_cfg/k8s_context.yaml" ANSIBLE_PYTHON_INTERPRETER="$PWD/.venv/bin/python"
export PATH="$PWD/bin:$PATH"                       # Fabric CLI (peer), needed by the modules
.github/scripts/kind_with_nginx.sh                 # logs/kind.log (exit 125 = registry step only)
.github/scripts/deploy-console.sh                  # logs/deploy-console.log
source _cfg/console-env.sh
C=plan/move-ingress/.url_management_new_checks

# Check 1: decoupled node domain (restart the console: the deployer reads settings at startup, F1)
kubectl patch ibpconsole hlf-console --type merge -p '{"spec":{"deployer":{"domain":"default.svc.cluster.local"}}}'
kubectl rollout restart deploy/hlf-console && kubectl rollout status deploy/hlf-console
# Pass names containing spaces as JSON: -e key="a b" is cut at the space (finding F3).
ansible-playbook -i localhost, -c local $C/playbooks/create-ca.yml -e '{"ca_display_name": "Check1 CA", "ca_wait": 20}'
kubectl get ibpca check1 -o jsonpath='{.spec.domain}'
kubectl apply -f $C/manifests/check1-per-endpoint-services.yml

# Check 2: unserved console Ingress
kubectl patch ibpconsole hlf-console --type merge -p '{"spec":{"ingress":{"class":"none"}}}'

# Checks 7 then 3: node Ingress neutralization, then a console update
kubectl patch ibpca check1 --type merge -p '{"spec":{"ingress":{"class":"none"}}}'
ansible-playbook -i localhost, -c local $C/playbooks/update-ca.yml -e ca_display_name=Check1

# Check 6: V5 URL assertion
ansible-playbook -i localhost, -c local $C/playbooks/check6-v5.yml
```

## Files

| Path | Content |
|---|---|
| `playbooks/create-ca.yml` | creates a CA through the `certificate_authority` module (check 1) |
| `playbooks/update-ca.yml` | changes the CA resources through the module (check 3) |
| `playbooks/delete-ca.yml` | deletes the CA through the module (cleanup) |
| `playbooks/check6-v5.yml` | V5 assertion on 10 URL cases (check 6) |
| `playbooks/00-deploy-console-check.yml` | `tutorial/00-deploy-fabric-console.yml` + `spec.deployer.domain` (`-e check_deployer_domain=…`); prepared, not used: the console was patched instead. Run it from `tutorial/` (it reads `common-vars.yml`). |
| `manifests/check1-per-endpoint-services.yml` | the two per-endpoint Services of sub-task 1.3b for the CA |
| `logs/kind.log`, `logs/deploy-console.log` | cluster and console bootstrap |
| `logs/check1-ca.log` | CA creation (health wait fails from the laptop, F4) |
| `results/c7-before.txt`, `results/c7-after.txt` | CA pod UID / restarts / Deployment generation / Ingress class around the patch (check 7) |
| `results/check1-ca-tls-cert.pem` | CA TLS certificate (public), SANs under `default.svc.cluster.local` |

## `network_domains/` — prototype of the shared role (MIGRATION-STEP-1 sub-task 1.1)

| Path | Content |
|---|---|
| `roles/network_domains/` | prototype role: `defaults/main.yml`, `tasks/main.yml`, `tasks/cluster_domain.yml`, `tasks/verify_urls.yml` |
| `test.yml`, `test_case.yml` | 13 cases (scenarios A–D, alias, V1–V3, cluster-domain match/mismatch); `run.log`: 13/13 PASS against the live KIND CoreDNS ConfigMap |
| `test_extra_vars.yml` | inputs passed with `-e` (empty `cluster_domain`) still resolve; `run_extra_vars.log` |

```bash
cd plan/move-ingress/.url_management_new_checks/network_domains
ANSIBLE_ROLES_PATH=$PWD/roles ansible-playbook -i localhost, -c local test.yml
```

## `job/` — in-cluster runner prototype (MIGRATION-STEP-1 sub-task 1.5)

| Path | Content |
|---|---|
| `Dockerfile` | runner image, on top of the repository's collection image (`docker build -t fabric-ansible-collection:ci .`) |
| `rbac.yml`, `job.yml` | ServiceAccount / Roles and the Job, as in sub-task 1.5 (`kubectl apply --dry-run=server` passes) |
| `probe.yml` | playbook run in a pod with the `ansible-runner` ServiceAccount: reads `kube-system/coredns`, calls `console_incluster_url` (both OK) |
| `runner-build.log` | runner image build |

Not kept: the collection build tarball (197 MB, rebuild with `ansible-galaxy collection build`) and a copy of `tutorial/common-vars.yml`.
