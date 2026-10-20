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
                                       tls_root)
from ..module_utils.k8s_jobs import (INPUT_DIR, K8sModule, fail_with_job_logs,
                                     k8s_job_argument_spec)
from ..module_utils.utils import (get_ordering_service_by_module,
                                  get_peer_by_module)

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: k8s_chaincode_approve
short_description: Approve a chaincode definition for an organization with a Kubernetes Job
description:
    - Approve a chaincode definition for the organization of the administrator, from a Kubernetes Job
      signed by this administrator.
    - Use this module instead of the M(approved_chaincode) module when the peers or the ordering service
      are not exposed outside of the Kubernetes cluster.
    - Nothing is done if the organization has approved this definition with this package.
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
    peer:
        description:
            - A peer of the organization, joined to the channel.
            - You can pass a string, which is the display name of a peer registered with the Fabric
              operations console.
            - You can also pass a dictionary, which must match the result format of one of the
              M(peer_info) or M(peer) modules.
        type: raw
        required: true
    package_id:
        description:
            - The package ID of the chaincode installed on the peers of the organization, as returned by
              M(k8s_chaincode_install).
        type: str
        required: true
extends_documentation_fragment:
    - hyperledger.fabric_ansible_collection.k8s
    - hyperledger.fabric_ansible_collection.k8s.jobs
    - hyperledger.fabric_ansible_collection.k8s.console
    - hyperledger.fabric_ansible_collection.k8s.admin
    - hyperledger.fabric_ansible_collection.k8s.chaincode_definition
'''

EXAMPLES = '''
- name: Approve the chaincode for Org1
  hyperledger.fabric_ansible_collection.k8s_chaincode_approve:
    api_endpoint: https://console.example.org:32000
    api_authtype: basic
    api_key: xxxxxxxx
    api_secret: xxxxxxxx
    namespace: org1
    msp_id: Org1MSP
    ordering_service: Ordering Service
    peer: Org1 Peer1
    channel: mychannel
    name: mycc
    version: "1.0"
    sequence: 1
    package_id: "{{ install.package_id }}"
    endorsement_policy: "OR('Org1MSP.peer','Org2MSP.peer')"
'''

RETURN = '''
---
approved:
    description:
        - Whether the definition was approved by this run.
    returned: always
    type: bool
'''


def script(definition):
    return f'''# Approved already: same definition (commit readiness) and same package.
if peer lifecycle chaincode checkcommitreadiness {definition} -O json > /work/readiness.json 2>/dev/null \\
   && [ -s /work/readiness.json ] \\
   && jq -e --arg msp "$CORE_PEER_LOCALMSPID" '.approvals[$msp] == true' /work/readiness.json >/dev/null 2>&1 \\
   && peer lifecycle chaincode queryapproved -C "$CHANNEL" -n "$CC_NAME" --sequence "$CC_SEQUENCE" -O json > /work/approved.json 2>/dev/null \\
   && jq -e --arg id "$PACKAGE_ID" '.source.Type.LocalPackage.package_id == $id' /work/approved.json >/dev/null 2>&1; then
  echo "$CORE_PEER_LOCALMSPID has approved sequence $CC_SEQUENCE of $CC_NAME"
  exit 0
fi
peer lifecycle chaincode approveformyorg -o "$ORDERER" --tls --cafile "$ORDERER_CA" {definition} --package-id "$PACKAGE_ID"
echo "FAC_RESULT approved true"
'''


def main():

    # Create the module.
    argument_spec = console_argument_spec(required=False)
    argument_spec.update(k8s_job_argument_spec())
    argument_spec.update(admin_argument_spec())
    argument_spec.update(chaincode_definition_argument_spec())
    argument_spec.update(
        ordering_service=dict(type='raw', required=True),
        peer=dict(type='raw', required=True),
        package_id=dict(type='str', required=True),
    )
    required_if = [
        ('api_authtype', 'basic', ['api_secret']),
    ]
    module = K8sModule(argument_spec=argument_spec, supports_check_mode=False, required_if=required_if,
                       mutually_exclusive=CHAINCODE_DEFINITION_MUTUALLY_EXCLUSIVE)

    try:
        p = module.params
        console = get_console_if_needed(module, 'ordering_service', 'peer')
        ordering_service = get_ordering_service_by_module(console, module)
        peer = get_peer_by_module(console, module)

        env, inputs = orderer_settings(ordering_service)
        env.update(
            CHANNEL=p['channel'], CC_NAME=p['name'], CC_SEQUENCE=p['sequence'], PACKAGE_ID=p['package_id'],
            CORE_PEER_ADDRESS=grpc_host_port(peer.api_url), CORE_PEER_TLS_ROOTCERT_FILE=f'{INPUT_DIR}/peer-tls.pem',
        )
        inputs['peer-tls.pem'] = pem(tls_root(peer))

        results, logs = run_admin_job(module, 'chaincode-approve', script(chaincode_definition_args(p)), env, inputs)
        approved = bool(results.get('approved'))
        module.exit_json(changed=approved, approved=approved)

    # Notify Ansible of the exception.
    except Exception as e:
        fail_with_job_logs(module, e)


if __name__ == '__main__':
    main()
