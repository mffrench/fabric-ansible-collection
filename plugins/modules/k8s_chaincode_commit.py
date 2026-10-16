#!/usr/bin/python
#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ..module_utils.k8s_fabric import (CHAINCODE_DEFINITION_MUTUALLY_EXCLUSIVE,
                                       admin_argument_spec,
                                       chaincode_definition_args,
                                       chaincode_definition_argument_spec,
                                       console_argument_spec,
                                       get_console_if_needed, grpc_host_port,
                                       orderer_settings, pem, run_admin_job,
                                       sh, tls_root)
from ..module_utils.k8s_jobs import (INPUT_DIR, K8sModule, fail_with_job_logs,
                                     k8s_job_argument_spec)
from ..module_utils.organizations import Organization
from ..module_utils.utils import (get_ordering_service_by_module,
                                  get_organization_by_name,
                                  get_peers_by_module)

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: k8s_chaincode_commit
short_description: Commit a chaincode definition to a channel with a Kubernetes Job
description:
    - Commit a chaincode definition to a channel, from a Kubernetes Job signed by the administrator of an
      organization. The commit is endorsed by I(peers) and I(endorsing_peers), one peer for each
      organization the lifecycle endorsement policy of the channel needs.
    - Use this module instead of the M(committed_chaincode) module when the peers or the ordering service
      are not exposed outside of the Kubernetes cluster.
    - Nothing is done if this sequence of the chaincode is committed.
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
    peers:
        description:
            - Peers of the organization, joined to the channel. The first one runs the commit.
            - You can pass strings, which are the display names of peers registered with the Fabric
              operations console.
            - You can also pass dictionaries, which must match the result format of one of the
              M(peer_info) or M(peer) modules.
        type: list
        elements: raw
        required: true
    endorsing_peers:
        description:
            - Peers of the other organizations, that the console of this organization does not know.
        type: list
        elements: dict
        default: []
        suboptions:
            address:
                description:
                    - The address (C(host:port)) of the peer, that resolves in the cluster.
                type: str
                required: true
            organization:
                description:
                    - The organization of the peer, to trust its TLS root certificate.
                    - You can pass a string, which is the name of an organization registered with the Fabric
                      operations console, or a dictionary in the result format of the M(organization_info) module.
                    - Mutually exclusive with I(tls_root_cert).
                type: raw
            tls_root_cert:
                description:
                    - The base64 encoded PEM TLS root certificate of the peer.
                type: str
extends_documentation_fragment:
    - hyperledger.fabric_ansible_collection.k8s
    - hyperledger.fabric_ansible_collection.k8s.jobs
    - hyperledger.fabric_ansible_collection.k8s.console
    - hyperledger.fabric_ansible_collection.k8s.admin
    - hyperledger.fabric_ansible_collection.k8s.chaincode_definition
'''

EXAMPLES = '''
- name: Commit the chaincode
  hyperledger.fabric_ansible_collection.k8s_chaincode_commit:
    api_endpoint: https://console.example.org:32000
    api_authtype: basic
    api_key: xxxxxxxx
    api_secret: xxxxxxxx
    namespace: org1
    msp_id: Org1MSP
    ordering_service: Ordering Service
    peers:
      - Org1 Peer1
    endorsing_peers:
      - address: org2-org2peer1-peer.example.org:443
        organization: Org2
    channel: mychannel
    name: mycc
    version: "1.0"
    sequence: 1
    endorsement_policy: "OR('Org1MSP.peer','Org2MSP.peer')"
'''

RETURN = '''
---
committed:
    description:
        - Whether the definition was committed by this run.
    returned: always
    type: bool
'''


def script(definition, peer_args):
    return f'''# The output is written to a file: jq 1.6 exits with 0 on an empty input.
if peer lifecycle chaincode querycommitted -C "$CHANNEL" -n "$CC_NAME" -O json > /work/committed.json 2>/dev/null \\
   && [ -s /work/committed.json ] \\
   && jq -e --argjson seq "$CC_SEQUENCE" '.sequence == $seq' /work/committed.json >/dev/null 2>&1; then
  echo "sequence $CC_SEQUENCE of $CC_NAME is committed"
  exit 0
fi
peer lifecycle chaincode checkcommitreadiness {definition} -O json
peer lifecycle chaincode commit -o "$ORDERER" --tls --cafile "$ORDERER_CA" {definition} {peer_args}
echo "FAC_RESULT committed true"
'''


def endorsing_peer_tls_root(console, endorsing_peer):
    if endorsing_peer['tls_root_cert']:
        return endorsing_peer['tls_root_cert']
    organization = endorsing_peer['organization']
    if isinstance(organization, dict):
        organization = Organization.from_json(organization)
    else:
        organization = get_organization_by_name(console, organization)
    return organization.tls_root_certs[0]


def main():

    # Create the module.
    argument_spec = console_argument_spec(required=False)
    argument_spec.update(k8s_job_argument_spec())
    argument_spec.update(admin_argument_spec())
    argument_spec.update(chaincode_definition_argument_spec())
    argument_spec.update(
        ordering_service=dict(type='raw', required=True),
        peers=dict(type='list', elements='raw', required=True),
        endorsing_peers=dict(type='list', elements='dict', default=list(), options=dict(
            address=dict(type='str', required=True),
            organization=dict(type='raw'),
            tls_root_cert=dict(type='str'),
        ), mutually_exclusive=[('organization', 'tls_root_cert')], required_one_of=[('organization', 'tls_root_cert')]),
    )
    required_if = [
        ('api_authtype', 'basic', ['api_secret']),
    ]
    module = K8sModule(argument_spec=argument_spec, supports_check_mode=False, required_if=required_if,
                       mutually_exclusive=CHAINCODE_DEFINITION_MUTUALLY_EXCLUSIVE)

    try:
        p = module.params
        console = get_console_if_needed(module, 'ordering_service', 'peers',
                                        needed=any(isinstance(e['organization'], str) for e in p['endorsing_peers']))
        ordering_service = get_ordering_service_by_module(console, module)
        peers = get_peers_by_module(console, module)

        env, inputs = orderer_settings(ordering_service)
        env.update(
            CHANNEL=p['channel'], CC_NAME=p['name'], CC_SEQUENCE=p['sequence'],
            CORE_PEER_ADDRESS=grpc_host_port(peers[0].api_url), CORE_PEER_TLS_ROOTCERT_FILE=f'{INPUT_DIR}/peer-0-tls.pem',
        )
        peer_args = list()
        endorsers = [(grpc_host_port(peer.api_url), tls_root(peer)) for peer in peers]
        endorsers += [(e['address'], endorsing_peer_tls_root(console, e)) for e in p['endorsing_peers']]
        for i, (address, root) in enumerate(endorsers):
            inputs[f'peer-{i}-tls.pem'] = pem(root)
            peer_args += ['--peerAddresses', address, '--tlsRootCertFiles', f'{INPUT_DIR}/peer-{i}-tls.pem']

        results, logs = run_admin_job(module, 'chaincode-commit', script(chaincode_definition_args(p), sh(*peer_args)), env, inputs)
        committed = bool(results.get('committed'))
        module.exit_json(changed=committed, committed=committed)

    # Notify Ansible of the exception.
    except Exception as e:
        fail_with_job_logs(module, e)


if __name__ == '__main__':
    main()
