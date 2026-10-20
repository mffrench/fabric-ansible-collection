#!/usr/bin/python
#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import urllib.parse

from ..module_utils.k8s_fabric import (FETCH_CONFIG, SUBMIT_UPDATE,
                                       admin_argument_spec,
                                       console_argument_spec,
                                       get_console_if_needed,
                                       orderer_settings, run_admin_job)
from ..module_utils.k8s_jobs import (INPUT_DIR, K8sModule, fail_with_job_logs,
                                     k8s_job_argument_spec)
from ..module_utils.utils import (get_ordering_service_by_module,
                                  get_peers_by_module)

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: k8s_anchor_peers
short_description: Set the anchor peers of an organization in a channel with a Kubernetes Job
description:
    - Set the anchor peers of an organization in a channel, from a Kubernetes Job signed by the
      administrator of the organization.
    - Use this module instead of the M(channel_config) and M(channel_member) modules when the ordering
      service is not exposed outside of the Kubernetes cluster.
    - The anchor peers of the organization are replaced by I(peers). Nothing is submitted when they are
      the same.
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
            - The anchor peers of the organization I(msp_id), at the address published by the console.
            - You can pass strings, which are the display names of peers registered with the Fabric
              operations console.
            - You can also pass dictionaries, which must match the result format of one of the
              M(peer_info) or M(peer) modules.
        type: list
        elements: raw
        required: true
    anchor_port:
        description:
            - The port of the anchor peers, instead of the port of the address published by the console
              (for example, the native port C(7051) when the other organizations reach the peers there).
        type: int
extends_documentation_fragment:
    - hyperledger.fabric_ansible_collection.k8s
    - hyperledger.fabric_ansible_collection.k8s.jobs
    - hyperledger.fabric_ansible_collection.k8s.console
    - hyperledger.fabric_ansible_collection.k8s.admin
'''

EXAMPLES = '''
- name: Set the anchor peer of Org1
  hyperledger.fabric_ansible_collection.k8s_anchor_peers:
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
'''

RETURN = '''
---
anchor_peers:
    description:
        - The anchor peers of the organization in the channel.
    returned: always
    type: list
    elements: dict
    contains:
        host:
            description:
                - The host of the anchor peer.
            type: str
        port:
            description:
                - The port of the anchor peer.
            type: int
'''

SCRIPT = FETCH_CONFIG + f'''MSP="$CORE_PEER_LOCALMSPID"
if ! jq -e --arg m "$MSP" '.channel_group.groups.Application.groups[$m]' /work/config.json >/dev/null; then
  echo "$MSP is not a member of $CHANNEL" >&2
  exit 1
fi
# The version is kept: compute_update increments it.
jq --arg m "$MSP" --slurpfile a {INPUT_DIR}/anchor-peers.json \\
  '.channel_group.groups.Application.groups[$m].values.AnchorPeers = {{
     mod_policy: "Admins",
     value: {{ anchor_peers: $a[0] }},
     version: (.channel_group.groups.Application.groups[$m].values.AnchorPeers.version // "0")
   }}' /work/config.json > /work/modified.json
''' + SUBMIT_UPDATE


def anchor_peers(peers, port=None):
    result = list()
    for peer in peers:
        parts = urllib.parse.urlsplit(peer.api_url)
        result.append(dict(host=parts.hostname, port=port or parts.port or 443))
    return result


def main():

    # Create the module.
    argument_spec = console_argument_spec(required=False)
    argument_spec.update(k8s_job_argument_spec())
    argument_spec.update(admin_argument_spec())
    argument_spec.update(
        ordering_service=dict(type='raw', required=True),
        channel=dict(type='str', required=True),
        peers=dict(type='list', elements='raw', required=True),
        anchor_port=dict(type='int'),
    )
    required_if = [
        ('api_authtype', 'basic', ['api_secret']),
    ]
    module = K8sModule(argument_spec=argument_spec, supports_check_mode=False, required_if=required_if)

    try:
        console = get_console_if_needed(module, 'ordering_service', 'peers')
        ordering_service = get_ordering_service_by_module(console, module)
        anchors = anchor_peers(get_peers_by_module(console, module), module.params['anchor_port'])

        env, inputs = orderer_settings(ordering_service)
        env.update(CHANNEL=module.params['channel'])
        inputs['anchor-peers.json'] = json.dumps(anchors)

        results, logs = run_admin_job(module, 'anchor-peers', SCRIPT, env, inputs)
        module.exit_json(changed=bool(results.get('updated')), anchor_peers=anchors)

    # Notify Ansible of the exception.
    except Exception as e:
        fail_with_job_logs(module, e)


if __name__ == '__main__':
    main()
