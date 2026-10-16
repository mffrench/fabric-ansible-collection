#!/usr/bin/python
#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ..module_utils.k8s_fabric import (admin_argument_spec,
                                       console_argument_spec,
                                       get_console_if_needed, grpc_host_port,
                                       orderer_settings, pem, run_admin_job,
                                       sh, tls_root)
from ..module_utils.k8s_jobs import (INPUT_DIR, K8sModule, fail_with_job_logs,
                                     k8s_job_argument_spec)
from ..module_utils.utils import (get_ordering_service_by_module,
                                  get_peers_by_module)

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: k8s_channel_join
short_description: Join Hyperledger Fabric peers to a channel with a Kubernetes Job
description:
    - Join peers to a channel, from a Kubernetes Job signed by the administrator of their organization.
      The Job fetches the genesis block of the channel from the ordering service.
    - Use this module instead of the M(channel_block) and M(peer_channel) modules when the peers or the
      ordering service are not exposed outside of the Kubernetes cluster.
    - Peers that are already members of the channel are left as they are.
options:
    ordering_service:
        description:
            - The ordering service.
            - You can pass a string, which is the cluster name of an ordering service registered with
              the Fabric operations console.
            - You can also pass a list, which must match the result format of one of the
              M(ordering_service_info) or M(ordering_service) modules.
        type: raw
        required: true
    channel:
        description:
            - The name of the channel.
        type: str
        required: true
    peers:
        description:
            - The peers to join.
            - You can pass strings, which are the display names of peers registered with the Fabric
              operations console.
            - You can also pass dictionaries, which must match the result format of one of the
              M(peer_info) or M(peer) modules.
        type: list
        elements: raw
        required: true
extends_documentation_fragment:
    - hyperledger.fabric_ansible_collection.k8s
    - hyperledger.fabric_ansible_collection.k8s.jobs
    - hyperledger.fabric_ansible_collection.k8s.console
    - hyperledger.fabric_ansible_collection.k8s.admin
'''

EXAMPLES = '''
- name: Join the peers to the channel
  hyperledger.fabric_ansible_collection.k8s_channel_join:
    api_endpoint: https://console.example.org:32000
    api_authtype: basic
    api_key: xxxxxxxx
    api_secret: xxxxxxxx
    namespace: org1
    msp_id: Org1MSP
    ordering_service: Ordering Service
    channel: mychannel
    peers:
      - Org1 Peer1
      - Org1 Peer2
'''

RETURN = '''
---
joined:
    description:
        - The display names of the peers joined to the channel by this run.
    returned: always
    type: list
    elements: str
'''

SCRIPT = '''peer channel fetch 0 /work/genesis.block -c "$CHANNEL" -o "$ORDERER" --tls --cafile "$ORDERER_CA"
join_once() {
  if CORE_PEER_ADDRESS="$1" CORE_PEER_TLS_ROOTCERT_FILE="$2" peer channel list 2>/dev/null | grep -qx "$CHANNEL"; then
    echo "$1 is already a member of $CHANNEL"
  else
    CORE_PEER_ADDRESS="$1" CORE_PEER_TLS_ROOTCERT_FILE="$2" peer channel join -b /work/genesis.block
    echo "FAC_RESULT joined $1"
  fi
}
'''


def main():

    # Create the module.
    argument_spec = console_argument_spec(required=False)
    argument_spec.update(k8s_job_argument_spec())
    argument_spec.update(admin_argument_spec())
    argument_spec.update(
        ordering_service=dict(type='raw', required=True),
        channel=dict(type='str', required=True),
        peers=dict(type='list', elements='raw', required=True),
    )
    required_if = [
        ('api_authtype', 'basic', ['api_secret']),
    ]
    module = K8sModule(argument_spec=argument_spec, supports_check_mode=False, required_if=required_if)

    try:
        console = get_console_if_needed(module, 'ordering_service', 'peers')
        ordering_service = get_ordering_service_by_module(console, module)
        peers = get_peers_by_module(console, module)

        env, inputs = orderer_settings(ordering_service)
        env.update(CHANNEL=module.params['channel'])
        script = SCRIPT
        names = dict()
        for i, peer in enumerate(peers):
            address = grpc_host_port(peer.api_url)
            names[address] = peer.name
            inputs[f'peer-{i}-tls.pem'] = pem(tls_root(peer))
            script += 'join_once ' + sh(address, f'{INPUT_DIR}/peer-{i}-tls.pem') + '\n'

        results, logs = run_admin_job(module, 'channel-join', script, env, inputs)
        joined = [names.get(a, a) for a in results.get('joined', list())]
        module.exit_json(changed=bool(joined), joined=joined)

    # Notify Ansible of the exception.
    except Exception as e:
        fail_with_job_logs(module, e)


if __name__ == '__main__':
    main()
