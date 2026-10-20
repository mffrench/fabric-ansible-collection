#!/usr/bin/python
#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json

from ..module_utils.k8s_fabric import (FETCH_CONFIG, SUBMIT_UPDATE,
                                       admin_argument_spec,
                                       console_argument_spec,
                                       get_console_if_needed,
                                       orderer_settings, run_admin_job)
from ..module_utils.k8s_jobs import (INPUT_DIR, K8sModule, fail_with_job_logs,
                                     k8s_job_argument_spec)
from ..module_utils.msp_utils import organization_to_msp
from ..module_utils.utils import (get_ordering_service_by_module,
                                  get_organizations_by_module)

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: k8s_consortium_members
short_description: Add organizations to a consortium of the system channel with a Kubernetes Job
description:
    - Add organizations to a consortium of the system channel of an ordering service, from a Kubernetes
      Job signed by the administrator of the ordering organization.
    - Use this module instead of the M(channel_config) and M(consortium_member) modules when the ordering
      service is not exposed outside of the Kubernetes cluster.
    - Organizations that are already members are left as they are. Nothing is submitted when every
      organization is a member.
    - An organization that is also in the Orderer group of the system channel (the ordering organization)
      keeps the same MSP definition, as Fabric refuses two different definitions of the same MSP.
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
    organizations:
        description:
            - The organizations to add.
            - You can pass strings, which are the names of organizations registered with the Fabric
              operations console.
            - You can also pass dictionaries, which must match the result format of one of the
              M(organization_info) or M(organization) modules.
        type: list
        elements: raw
        required: true
    consortium:
        description:
            - The name of the consortium.
        type: str
        default: SampleConsortium
    system_channel:
        description:
            - The name of the system channel.
        type: str
        default: testchainid
extends_documentation_fragment:
    - hyperledger.fabric_ansible_collection.k8s
    - hyperledger.fabric_ansible_collection.k8s.jobs
    - hyperledger.fabric_ansible_collection.k8s.console
    - hyperledger.fabric_ansible_collection.k8s.admin
'''

EXAMPLES = '''
- name: Add the endorsing organizations to the consortium
  hyperledger.fabric_ansible_collection.k8s_consortium_members:
    api_endpoint: https://console.example.org:32000
    api_authtype: basic
    api_key: xxxxxxxx
    api_secret: xxxxxxxx
    namespace: ordering-org
    msp_id: OrdererMSP
    ordering_service: Ordering Service
    organizations:
      - Org1
      - Org2
'''

RETURN = '''
---
added:
    description:
        - The MSP IDs of the organizations added to the consortium by this run.
    returned: always
    type: list
    elements: str
'''

SCRIPT = FETCH_CONFIG + f'''cp /work/config.json /work/modified.json
if ! jq -e --arg c "$CONSORTIUM" '.channel_group.groups.Consortiums.groups[$c]' /work/config.json >/dev/null; then
  echo "the consortium $CONSORTIUM does not exist in $CHANNEL" >&2
  exit 1
fi
for f in {INPUT_DIR}/org-*.json; do
  MSP=$(jq -r '.values.MSP.value.config.name' "$f")
  if jq -e --arg c "$CONSORTIUM" --arg m "$MSP" '.channel_group.groups.Consortiums.groups[$c].groups[$m]' /work/modified.json >/dev/null; then
    echo "$MSP is already a member of $CONSORTIUM"
    continue
  fi
  # Same MSP definition as in the Orderer group, if the organization is there.
  jq --slurpfile sys /work/config.json --arg m "$MSP" \\
    '($sys[0].channel_group.groups.Orderer.groups[$m].values.MSP) as $msp | if $msp != null then .values.MSP = $msp else . end' \\
    "$f" > /work/org.json
  jq --arg c "$CONSORTIUM" --arg m "$MSP" --slurpfile org /work/org.json \\
    '.channel_group.groups.Consortiums.groups[$c].groups[$m] = $org[0]' /work/modified.json > /work/next.json
  mv /work/next.json /work/modified.json
  echo "FAC_RESULT added $MSP"
done
''' + SUBMIT_UPDATE


def main():

    # Create the module.
    argument_spec = console_argument_spec(required=False)
    argument_spec.update(k8s_job_argument_spec())
    argument_spec.update(admin_argument_spec())
    argument_spec.update(
        ordering_service=dict(type='raw', required=True),
        organizations=dict(type='list', elements='raw', required=True),
        consortium=dict(type='str', default='SampleConsortium'),
        system_channel=dict(type='str', default='testchainid'),
    )
    required_if = [
        ('api_authtype', 'basic', ['api_secret']),
    ]
    module = K8sModule(argument_spec=argument_spec, supports_check_mode=False, required_if=required_if)

    try:
        console = get_console_if_needed(module, 'ordering_service', 'organizations')
        ordering_service = get_ordering_service_by_module(console, module)
        organizations = get_organizations_by_module(console, module)

        env, inputs = orderer_settings(ordering_service)
        env.update(CHANNEL=module.params['system_channel'], CONSORTIUM=module.params['consortium'])
        for i, organization in enumerate(organizations):
            inputs[f'org-{i}.json'] = json.dumps(organization_to_msp(organization, endorsement_policy_required=True))

        results, logs = run_admin_job(module, 'consortium-members', SCRIPT, env, inputs)
        added = results.get('added', list())
        module.exit_json(changed=bool(results.get('updated')), added=added)

    # Notify Ansible of the exception.
    except Exception as e:
        fail_with_job_logs(module, e)


if __name__ == '__main__':
    main()
