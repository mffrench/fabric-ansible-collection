#!/usr/bin/python
#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json

from ..module_utils.k8s_fabric import (admin_argument_spec,
                                       console_argument_spec,
                                       get_console_if_needed,
                                       orderer_settings, run_admin_job)
from ..module_utils.k8s_jobs import (INPUT_DIR, K8sModule, fail_with_job_logs,
                                     k8s_job_argument_spec)
from ..module_utils.utils import (get_ordering_service_by_module,
                                  get_organizations_by_module)

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: k8s_channel
short_description: Create a Hyperledger Fabric channel with a Kubernetes Job
description:
    - Create a channel from a consortium of the system channel, with a Kubernetes Job signed by the
      administrator of a member organization.
    - Use this module instead of the M(channel_block) and M(channel_config) modules when the ordering
      service is not exposed outside of the Kubernetes cluster.
    - The configuration update is built as by the C(create) operation of the M(channel_config) module.
      The Job encodes it, signs it and submits it.
    - Nothing is done if the channel exists.
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
    name:
        description:
            - The name of the channel.
        type: str
        required: true
    organizations:
        description:
            - The organizations of the channel. They must be members of I(consortium).
            - You can pass strings, which are the names of organizations registered with the Fabric
              operations console.
            - You can also pass dictionaries, which must match the result format of one of the
              M(organization_info) or M(organization) modules.
        type: list
        elements: raw
        required: true
    policies:
        description:
            - The policies of the Application group of the channel, as in the M(channel_config) module,
              a dictionary of policy names to policies (Fabric policy JSON, or the path of a JSON file).
            - Defaults to C(ANY Readers), C(ANY Writers), C(MAJORITY Admins), and C(MAJORITY Endorsement)
              for C(Endorsement) and C(LifecycleEndorsement).
        type: dict
    capabilities:
        description:
            - The capabilities of the channel.
        type: dict
        default: {}
        suboptions:
            application:
                description:
                    - The application capability.
                type: str
                default: V2_0
            channel:
                description:
                    - The channel capability.
                type: str
            orderer:
                description:
                    - The orderer capability.
                type: str
    consortium:
        description:
            - The consortium of the system channel the channel is created from.
        type: str
        default: SampleConsortium
extends_documentation_fragment:
    - hyperledger.fabric_ansible_collection.k8s
    - hyperledger.fabric_ansible_collection.k8s.jobs
    - hyperledger.fabric_ansible_collection.k8s.console
    - hyperledger.fabric_ansible_collection.k8s.admin
'''

EXAMPLES = '''
- name: Create the channel
  hyperledger.fabric_ansible_collection.k8s_channel:
    api_endpoint: https://console.example.org:32000
    api_authtype: basic
    api_key: xxxxxxxx
    api_secret: xxxxxxxx
    namespace: org1
    msp_id: Org1MSP
    ordering_service: Ordering Service
    name: mychannel
    organizations:
      - Org1
      - Org2
'''

RETURN = '''
---
created:
    description:
        - Whether the channel was created by this run.
    returned: always
    type: bool
'''

SCRIPT = f'''if peer channel fetch 0 /work/genesis.block -c "$CHANNEL" -o "$ORDERER" --tls --cafile "$ORDERER_CA" >/dev/null 2>&1; then
  echo "the channel $CHANNEL exists"
  exit 0
fi
configtxlator proto_encode --type common.Envelope --input {INPUT_DIR}/channel-create.json --output /work/channel.tx
peer channel create -c "$CHANNEL" -f /work/channel.tx -o "$ORDERER" --tls --cafile "$ORDERER_CA" --outputBlock /work/genesis.block
echo "FAC_RESULT created true"
'''


def implicit_meta(rule, sub_policy):
    return dict(type=3, value=dict(rule=rule, sub_policy=sub_policy))


DEFAULT_POLICIES = dict(
    Readers=implicit_meta('ANY', 'Readers'),
    Writers=implicit_meta('ANY', 'Writers'),
    Admins=implicit_meta('MAJORITY', 'Admins'),
    Endorsement=implicit_meta('MAJORITY', 'Endorsement'),
    LifecycleEndorsement=implicit_meta('MAJORITY', 'Endorsement'),
)


def channel_create_envelope(name, consortium, msp_ids, policies, capabilities):
    """Envelope of the configuration update that creates a channel, in the JSON
    format of configtxlator (as the create operation of channel_config)."""
    config_update = dict(
        channel_id=name,
        read_set=dict(
            groups=dict(Application=dict(groups={m: dict() for m in msp_ids})),
            values=dict(Consortium=dict(value=dict(name=consortium))),
        ),
        write_set=dict(
            groups=dict(Application=dict(
                groups={m: dict() for m in msp_ids},
                mod_policy='Admins',
                policies={n: dict(mod_policy='Admins', policy=p) for n, p in policies.items()},
                values=dict(Capabilities=dict(
                    mod_policy='Admins',
                    value=dict(capabilities={capabilities['application']: dict()}),
                )),
                version=1,
            )),
            values=dict(Consortium=dict(value=dict(name=consortium))),
        ),
    )
    if capabilities.get('channel'):
        config_update['read_set']['values']['Capabilities'] = dict()
        config_update['write_set']['values']['Capabilities'] = dict(
            mod_policy='Admins', value=dict(capabilities={capabilities['channel']: dict()}), version=1)
    if capabilities.get('orderer'):
        config_update['read_set']['groups']['Orderer'] = dict(values=dict(Capabilities=dict()))
        config_update['write_set']['groups']['Orderer'] = dict(values=dict(Capabilities=dict(
            mod_policy='Admins', value=dict(capabilities={capabilities['orderer']: dict()}), version=1)))
    return dict(payload=dict(
        header=dict(channel_header=dict(channel_id=name, type=2)),
        data=dict(config_update=config_update),
    ))


def load_policies(policies):
    if policies is None:
        return DEFAULT_POLICIES
    actual = dict()
    for name, policy in policies.items():
        if isinstance(policy, str):
            with open(policy, 'r') as file:
                actual[name] = json.load(file)
        elif isinstance(policy, dict):
            actual[name] = policy
        else:
            raise Exception(f'The policy {name} is invalid')
    return actual


def main():

    # Create the module.
    argument_spec = console_argument_spec(required=False)
    argument_spec.update(k8s_job_argument_spec())
    argument_spec.update(admin_argument_spec())
    argument_spec.update(
        ordering_service=dict(type='raw', required=True),
        name=dict(type='str', required=True),
        organizations=dict(type='list', elements='raw', required=True),
        policies=dict(type='dict'),
        capabilities=dict(type='dict', default=dict(), options=dict(
            application=dict(type='str', default='V2_0'),
            channel=dict(type='str'),
            orderer=dict(type='str'),
        )),
        consortium=dict(type='str', default='SampleConsortium'),
    )
    required_if = [
        ('api_authtype', 'basic', ['api_secret']),
    ]
    module = K8sModule(argument_spec=argument_spec, supports_check_mode=False, required_if=required_if)

    try:
        console = get_console_if_needed(module, 'ordering_service', 'organizations')
        ordering_service = get_ordering_service_by_module(console, module)
        organizations = get_organizations_by_module(console, module)

        name = module.params['name']
        envelope = channel_create_envelope(name, module.params['consortium'], [o.msp_id for o in organizations],
                                           load_policies(module.params['policies']), module.params['capabilities'])
        env, inputs = orderer_settings(ordering_service)
        env.update(CHANNEL=name)
        inputs['channel-create.json'] = json.dumps(envelope)

        results, logs = run_admin_job(module, 'channel-create', SCRIPT, env, inputs)
        created = bool(results.get('created'))
        module.exit_json(changed=created, created=created)

    # Notify Ansible of the exception.
    except Exception as e:
        fail_with_job_logs(module, e)


if __name__ == '__main__':
    main()
