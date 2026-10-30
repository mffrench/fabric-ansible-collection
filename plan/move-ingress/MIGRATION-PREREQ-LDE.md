# Local Development Environment (LDE) — Running CI Tests Locally

This document describes how to set up and run the Functional Verification (FV) CI
tests on a developer workstation. It is written to work on **macOS** and
**Linux**, under **bash** or **zsh**; platform-specific points are called out
where they differ.

---

## 1. Prerequisites & Environment Setup

Ensure the following tools and CLI utilities are installed and available in `$PATH`:

1. **A Docker daemon**: Docker Desktop, Colima, Rancher Desktop or native
   `docker`/`podman` on Linux, running with at least 4 CPUs and 8 GB RAM.
   ⚠️ **Host ports 80 and 443 must be free** — see section 8.
2. **Kind**: Kubernetes in Docker (`kind version`).
3. **kubectl & jq**: cluster inspection and CoreDNS config
   (macOS `brew install kubectl jq`; Debian/Ubuntu `apt install kubectl jq`).
4. **Python ≥ 3.10**: required by `ansible-core` 2.17. Any 3.10+ interpreter
   works; the examples below use `python3.10` because that is what CI pins, but
   a newer one is fine.
5. **yq**: must be **python-yq** (`pip install yq`, installed by
   `requirements.txt` inside the venv). The Go `yq` from Homebrew or apt is a
   *different* tool and does **not** support the `yq -yi` in-place YAML writes
   the test scripts rely on. `lde_preflight` (section 4.1) checks which one is
   on `PATH`.
6. **Ansible**: installed inside the virtualenv by section 2, not system-wide.
   A system Ansible on `PATH` shadows the venv one and will not find the
   `kubernetes` SDK.

---

## 2. Python 3.10 Virtual Environment & Dependencies

To ensure a clean, isolated environment and avoid library incompatibilities, use Python's built-in [`venv`](https://docs.python.org/3/library/venv.html) module with **Python 3.10** exactly.

### 2.1 Create and Activate Python 3.10 Virtual Environment

```bash
# Verify Python 3.10 is installed
python3.10 --version

# Create virtual environment in .venv
python3.10 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade base packaging tools inside the virtual environment
pip install --upgrade pip setuptools wheel
```

### 2.2 Install Python Requirements & Collection Dependencies

Install the Python dependencies from [`requirements.txt`](../../requirements.txt) inside the active virtual environment:

```bash
pip install -r requirements.txt
```

Verify that required Ansible collections are installed or available:

```bash
ansible-galaxy collection install community.crypto community.general kubernetes.core
```

---

## 3. Build and Install Local Fabric Ansible Collection

Build the collection package from the repository root and install it into your local Ansible collections path:

```bash
ansible-galaxy collection build -f
ansible-galaxy collection install $(ls -1 | grep fabric_ansible_collection) -f
```

---

## 4. Install Hyperledger Fabric CLI Binaries (Fabric 2.5.15)

The tutorial playbooks and test scripts interact with Fabric CLI tools (`peer`,
`configtxlator`, ...). `BlockchainModule` checks for them at module start-up, so
a missing `peer` fails the very first task of any playbook.

Run this from the repository root — it detects OS and architecture, so the same
command works on macOS (Intel and Apple silicon) and on Linux (x86_64 and
arm64):

```bash
FABRIC_VERSION=2.5.15
OS=$(uname -s | tr '[:upper:]' '[:lower:]')          # darwin | linux
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)        ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
esac

curl -sSL "https://github.com/hyperledger/fabric/releases/download/v${FABRIC_VERSION}/hyperledger-fabric-${OS}-${ARCH}-${FABRIC_VERSION}.tar.gz" | tar xzf -
```

This unpacks `bin/` and `config/` into the repository root; both are gitignored.

### 4.1 Load the LDE shell environment

Rather than exporting variables by hand before each step, **source** the helper
script. It is idempotent, works under bash and zsh on macOS and Linux, and sets
up the virtualenv, `PATH`, `FABRIC_CFG_PATH`, `KUBECONFIG` and
`ANSIBLE_PYTHON_INTERPRETER` in one go:

```bash
source .github/scripts/lde-env.sh
lde_preflight
```

`lde_preflight` prints one line per dependency and returns non-zero if any is
missing. Re-run it after each of the following sections; everything should read
`ok` before section 7.

Two of the variables it sets are easy to miss when doing this manually:

| Variable | Why it is needed |
|---|---|
| `FABRIC_CFG_PATH` | the `peer` CLI looks for `core.yaml` there; the modules set it for their own subprocesses but not for the `peer version` start-up check |
| `ANSIBLE_PYTHON_INTERPRETER` | `deploy-console.sh` passes `-i localhost,`, which puts localhost **in the inventory**. Ansible only equates the target interpreter with the one running `ansible-playbook` for the *implicit* localhost; with an explicit one, interpreter discovery takes over and picks a system Python with no `kubernetes` SDK |

Verify the binaries resolve to the repository copy:

```bash
peer version
command -v peer    # -> <repo>/bin/peer
```

---

## 5. Bootstrap Local Kind Cluster with Ingress

The test environment sets up a Kind cluster with an NGINX Ingress controller bound to host ports 80/443 and configures CoreDNS for `.localho.st` routing.

1. **Set Host API Server Address and Port**:
   On macOS Docker Desktop, use `127.0.0.1` or your host IP:
   ```bash
   export KIND_API_SERVER_ADDRESS="127.0.0.1"
   export KIND_API_SERVER_PORT="8888"
   ```

2. **Execute the Kind bootstrap script**:
   ```bash
   chmod +x .github/scripts/kind_with_nginx.sh
   .github/scripts/kind_with_nginx.sh
   ```

3. **Verify the cluster and ingress controller**:
   ```bash
   kubectl get nodes
   kubectl wait --namespace ingress-nginx \
     --for=condition=ready pod \
     --selector=app.kubernetes.io/component=controller \
     --timeout=3m
   ```

4. **Ensure `KUBECONFIG` is active**:
   ```bash
   export KUBECONFIG="$PWD/_cfg/k8s_context.yaml"
   ```

---

## 6. Deploy Fabric Operator & Console

Before running any tests the Fabric Operator CRDs and the Fabric Operations Console
must be deployed into the cluster. The helper script does this and writes connection
details to `_cfg/console-env.sh`:

```bash
source .github/scripts/lde-env.sh    # sets KUBECONFIG and the rest
.github/scripts/deploy-console.sh
```

The script prints the console `API_ENDPOINT` it derived and waits for the console
deployment to become ready (`wait_timeout=600 s`).

### 6.1 (Optional) Deprovision Fabric Operator & Console

To tear down the console and operator CRDs without destroying the entire Kind cluster:

```bash
export KUBECONFIG="$PWD/_cfg/k8s_context.yaml"
.github/scripts/undeploy-console.sh
```

---

## 7. Run the Tests

With the console deployed, run the full FV test suite:

```bash
source .github/scripts/lde-env.sh
lde_preflight || echo "fix the above before continuing"
.github/scripts/run-tests.sh
```

`run-tests.sh` automatically sources `_cfg/console-env.sh` when it exists, so no
manual `export API_ENDPOINT=…` is required after `deploy-console.sh` has run.

### Option B: Running with `run-tutorial-tests.sh` (Parameterized / Multi-run)

If testing against an existing Fabric Operations Console endpoint (e.g. a remote
cluster), export the connection variables explicitly:

```bash
export API_ENDPOINT="https://<namespace>-<console-name>-console.<domain>"
export API_AUTHTYPE="basic"
export API_KEY="admin"
export API_SECRET="password"
export K8S_NAMESPACE="default"
export USE_DOCKER="false"

.github/scripts/run-tutorial-tests.sh
```

---

## 8. Troubleshooting

- **Port 80 / 443 conflicts** — the Kind node publishes host ports 80 and 443 for
  the ingress controller. Anything else holding them makes the console
  unreachable from the host, and the symptom is misleading: requests reach the
  *other* listener and come back `404`, as if the ingress were misconfigured.
  Identify the holder first:

  ```bash
  lsof -nP -iTCP:443 -sTCP:LISTEN     # macOS and most Linux
  ss -ltnp  '( sport = :443 )'        # Linux fallback
  ```

  `lde_preflight` reports this as a `check` line. Common holders:

  | Holder | How to free the port |
  |---|---|
  | **Rancher Desktop** with Kubernetes enabled — its k3s runs Traefik behind a `svclb`, forwarded to the host by an `ssh` tunnel. A `CN=TRAEFIK DEFAULT CERT` in the TLS handshake confirms it. | `rdctl set --kubernetes.options.traefik=false`, or disable Kubernetes entirely in Settings → Kubernetes (Rancher Desktop still provides the Docker daemon) |
  | Apache / httpd (macOS) | `sudo apachectl stop` |
  | A host nginx (Linux) | `sudo systemctl stop nginx` |

- **`Failed to import the required Python library (kubernetes)`** — Ansible is
  using the wrong interpreter. Source `lde-env.sh` (section 4.1), which pins
  `ANSIBLE_PYTHON_INTERPRETER`. Confirm with
  `ansible localhost -m debug -a var=ansible_playbook_python`.

- **`Failed to execute the required binary (peer)`** — `bin/` is not on `PATH`.
  Source `lde-env.sh`, then check `command -v peer`.

- **`yq: unknown shorthand flag: 'y'`** — the Go `yq` is on `PATH` ahead of
  python-yq. Activate the virtualenv, or `pip install yq`.
- **Docker Memory Limits**: Hyperledger Fabric nodes (orderers, peers, chaincode containers, couchdb) require sufficient memory. Ensure Docker Desktop has at least **8 GB RAM** allocated in **Settings > Resources**.
- **DNS Resolution**: `*.localho.st` and `*.nip.io` domains are resolved via CoreDNS overrides in the cluster. If host resolution fails locally, verify `ping 127-0-0-1.nip.io` resolves to `127.0.0.1`.

---

## 9. Validation Checklist

Work through each item in order before declaring the LDE ready.

- [ ] Kind cluster boots and NGINX Ingress controller pod becomes `Ready`
  ```bash
  kubectl wait --namespace ingress-nginx \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=3m
  ```
- [ ] Operator CRDs and Console deploy without error (`deploy-console.sh` exits 0).
- [ ] Console health endpoint responds with HTTP 200 and a JSON payload:
  ```bash
  source .github/scripts/lde-env.sh
  curl -sk -u "${API_KEY}:${API_SECRET}" "${API_ENDPOINT}/ak/api/v3/health" | jq 'keys'
  # Expected: ["OPTOOLS","OS"]
  ```
  Use **`/ak/api/v3/health`**, the path the modules call
  ([`consoles.py`](../../plugins/module_utils/consoles.py) builds it from
  `api_base_url`), and pass the credentials — it answers `401` without them.
  `${API_ENDPOINT}/health` is *not* the API: it serves the console's HTML UI, so
  piping it to `jq` fails with `Invalid numeric literal`.

- [ ] The TLS certificate presented on `:443` is the console's own, proving the
  ingress is doing SSL passthrough and no other listener has taken the port:
  ```bash
  curl -sk -v "${API_ENDPOINT}/" 2>&1 | grep 'subject:'
  # Expected: CN=<namespace>-<console-name>-console.<domain>, O=ibp2-auto-gen
  # A foreign CN (e.g. TRAEFIK DEFAULT CERT) means something else holds :443 —
  # see section 8.
  ```
- [ ] Tutorial playbooks (01 to 23) complete successfully (`run-tests.sh` exits 0).
- [ ] Network teardown plays (`join_network.sh destroy`) cleanly delete all created resources.
