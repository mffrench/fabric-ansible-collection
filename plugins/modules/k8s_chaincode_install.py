#!/usr/bin/python
#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ..module_utils.k8s_fabric import (admin_argument_spec,
                                       console_argument_spec,
                                       get_console_if_needed, grpc_host_port,
                                       pem, run_admin_job, sh, tls_root)
from ..module_utils.k8s_jobs import (INPUT_DIR, K8sModule, fail_with_job_logs,
                                     k8s_job_argument_spec)
from ..module_utils.utils import get_peers_by_module

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: k8s_chaincode_install
short_description: Install a chaincode package on Hyperledger Fabric peers with a Kubernetes Job
description:
    - Install a chaincode package on peers, from a Kubernetes Job signed by the administrator of their
      organization, and return its package ID.
    - Use this module instead of the M(installed_chaincode) module when the peers are not exposed outside
      of the Kubernetes cluster.
    - Peers that have the package installed are left as they are.
options:
    peers:
        description:
            - The peers to install the package on.
            - You can pass strings, which are the display names of peers registered with the Fabric
              operations console.
            - You can also pass dictionaries, which must match the result format of one of the
              M(peer_info) or M(peer) modules.
        type: list
        elements: raw
        required: true
    path:
        description:
            - The path of the chaincode package on the Ansible host, for example built by M(ccaas_package).
            - The package goes to the Job in a Secret, so it must be smaller than 1 MiB, as the packages
              of chaincodes that run as an external service.
        type: path
        required: true
extends_documentation_fragment:
    - hyperledger.fabric_ansible_collection.k8s
    - hyperledger.fabric_ansible_collection.k8s.jobs
    - hyperledger.fabric_ansible_collection.k8s.console
    - hyperledger.fabric_ansible_collection.k8s.admin
'''

EXAMPLES = '''
- name: Install the chaincode on the peers
  hyperledger.fabric_ansible_collection.k8s_chaincode_install:
    api_endpoint: https://console.example.org:32000
    api_authtype: basic
    api_key: xxxxxxxx
    api_secret: xxxxxxxx
    namespace: org1
    msp_id: Org1MSP
    peers:
      - Org1 Peer1
      - Org1 Peer2
    path: mycc_1.0.tgz
  register: install
'''

RETURN = '''
---
package_id:
    description:
        - The package ID of the package.
    returned: always
    type: str
installed:
    description:
        - The display names of the peers the package was installed on by this run.
    returned: always
    type: list
    elements: str
'''

# A Secret holds at most 1 MiB, with the other inputs.
MAX_PACKAGE_SIZE = 900 * 1024

SCRIPT = f'''PKG={INPUT_DIR}/package.tgz
PACKAGE_ID="$(peer lifecycle chaincode calculatepackageid "$PKG")"
echo "FAC_RESULT package_id $PACKAGE_ID"
install_once() {{
  # The output is written to a file: jq 1.6 exits with 0 on an empty input.
  if CORE_PEER_ADDRESS="$1" CORE_PEER_TLS_ROOTCERT_FILE="$2" peer lifecycle chaincode queryinstalled -O json > /work/installed.json 2>/dev/null \\
     && [ -s /work/installed.json ] \\
     && jq -e --arg id "$PACKAGE_ID" '.installed_chaincodes[]? | select(.package_id == $id)' /work/installed.json >/dev/null 2>&1; then
    echo "$PACKAGE_ID is already installed on $1"
  else
    CORE_PEER_ADDRESS="$1" CORE_PEER_TLS_ROOTCERT_FILE="$2" peer lifecycle chaincode install "$PKG"
    echo "FAC_RESULT installed $1"
  fi
}}
'''


def main():

    # Create the module.
    argument_spec = console_argument_spec(required=False)
    argument_spec.update(k8s_job_argument_spec())
    argument_spec.update(admin_argument_spec())
    argument_spec.update(
        peers=dict(type='list', elements='raw', required=True),
        path=dict(type='path', required=True),
    )
    required_if = [
        ('api_authtype', 'basic', ['api_secret']),
    ]
    module = K8sModule(argument_spec=argument_spec, supports_check_mode=False, required_if=required_if)

    try:
        with open(module.params['path'], 'rb') as file:
            package = file.read()
        if len(package) > MAX_PACKAGE_SIZE:
            raise Exception(f'The package is {len(package)} bytes, more than the {MAX_PACKAGE_SIZE} bytes a Job can receive')

        console = get_console_if_needed(module, 'peers')
        peers = get_peers_by_module(console, module)

        inputs = {'package.tgz': package}
        script = SCRIPT
        names = dict()
        for i, peer in enumerate(peers):
            address = grpc_host_port(peer.api_url)
            names[address] = peer.name
            inputs[f'peer-{i}-tls.pem'] = pem(tls_root(peer))
            script += 'install_once ' + sh(address, f'{INPUT_DIR}/peer-{i}-tls.pem') + '\n'

        results, logs = run_admin_job(module, 'chaincode-install', script, dict(), inputs)
        installed = [names.get(a, a) for a in results.get('installed', list())]
        module.exit_json(changed=bool(installed), package_id=results['package_id'][0], installed=installed)

    # Notify Ansible of the exception.
    except Exception as e:
        fail_with_job_logs(module, e)


if __name__ == '__main__':
    main()
