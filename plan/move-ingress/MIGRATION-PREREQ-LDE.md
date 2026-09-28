# Local Development Environment (LDE) — Running CI Tests on macOS

This document describes how to set up and run the Functional Verification (FV) CI tests locally on an Apple macOS (OSX) workstation where **Kind** and **Ansible** are already installed.

---

## 1. Prerequisites & macOS Environment Setup

Ensure the following tools and CLI utilities are installed and available in `$PATH`:

1. **Docker Desktop / Colima**: Docker daemon must be running and allocated adequate resources (at least 4 CPUs and 8 GB RAM recommended).
2. **Kind**: Kubernetes in Docker (`kind version`).
3. **Ansible**: `ansible` and `ansible-playbook` (`ansible --version`).
4. **kubectl & jq**: Required for cluster inspection and CoreDNS config (`brew install kubectl jq`).
5. **Python 3.10**: Exact version required (`python3.10 --version`).
6. **yq & shasum**: Required by tutorial test runner scripts (`brew install yq` or `pip install yq`).

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

## 4. Install Hyperledger Fabric CLI Binaries (Fabric 2.4.7)

The tutorial playbooks and test scripts interact with Fabric CLI tools (`peer`, `configtxlator`, etc.). Install the Fabric 2.4.7 binaries for macOS:

```bash
# Set download architecture for macOS (darwin-arm64 or darwin-amd64)
ARCH="$(uname -m)"
[ "$ARCH" = "x86_64" ] && ARCH="amd64"

curl -sSL "https://github.com/hyperledger/fabric/releases/download/v2.5.15/hyperledger-fabric-darwin-${ARCH}-2.5.15.tar.gz" | tar xzf -
export PATH="$PWD/bin:$PATH"
```

Verify the binary is available:
```bash
peer version
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

## 6. Run the Tests

### Option A: Running the Tutorial Test Suite Directly

The test suite runs through `build_network.sh`, `join_network.sh`, `deploy_smart_contract.sh`, and teardown:

```bash
cd tutorial

# 1. Build the network (Ordering Org, Org1, consortium, channel setup)
./build_network.sh build

# 2. Join Org2 to the consortium and channel
./join_network.sh join

# 3. Deploy the smart contract (FabCar package lifecycle & test transactions)
./deploy_smart_contract.sh

# 4. Clean up / destroy components when done
./join_network.sh destroy
```

### Option B: Running with `run-tutorial-tests.sh` (Parameterized / Multi-run)

If testing against an existing Fabric Operations Console endpoint:

```bash
export API_ENDPOINT="https://127.0.0.1.nip.io:443"
export API_AUTHTYPE="basic"
export API_KEY="admin"
export API_SECRET="password"
export K8S_NAMESPACE="default"
export USE_DOCKER="false"

.github/scripts/run-tutorial-tests.sh
```

---

## 7. macOS Troubleshooting Tips

- **Port 80 / 443 Conflicts**: If Apache/httpd or another local web server is bound to port 80/443 on macOS, stop it (`sudo apachectl stop`) before launching the Kind cluster.
- **Docker Memory Limits**: Hyperledger Fabric nodes (orderers, peers, chaincode containers, couchdb) require sufficient memory. Ensure Docker Desktop has at least **8 GB RAM** allocated in **Settings > Resources**.
- **DNS Resolution**: `*.localho.st` and `*.nip.io` domains are resolved via CoreDNS overrides in the cluster. If host resolution fails locally, verify `ping 127-0-0-1.nip.io` resolves to `127.0.0.1`.
