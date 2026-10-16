#!/usr/bin/python
#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import time

from ansible.module_utils._text import to_native

from ..module_utils.k8s_jobs import (K8sModule, get_api_client, get_object,
                                     k8s_connection_argument_spec, k8s_name)

try:
    from kubernetes import client
except ImportError:
    pass  # get_api_client reports the missing library

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: k8s_component_ready
short_description: Wait until Hyperledger Fabric components are running in Kubernetes
description:
    - Wait until the Kubernetes Deployments of certificate authorities, peers or ordering
      service nodes created by the operator are rolled out and available.
    - Use this module instead of the operations URL check (C(/healthz)) of the
      M(certificate_authority), M(peer) and M(ordering_service) modules when the component
      is not exposed outside of the Kubernetes cluster. Set I(wait_mode=none) on those modules.
    - This module talks to the Kubernetes API only, never to the components.
options:
    components:
        description:
            - The components to wait for.
            - Either the console display name of the component (for example, C(Org1 CA)), or the name
              of its Kubernetes objects (for example, C(org1ca)). The operator names the Deployment
              after the display name, in lower case, without the characters other than a-z and 0-9.
            - The Deployment of ordering service node I(N) is named C(<ordering service>nodeN),
              for example C(orderingservicenode1).
        type: list
        elements: str
        required: true
    timeout:
        description:
            - The timeout, in seconds, to wait until every component is available.
        type: int
        default: 600
notes:
    - The Deployment of a component is created by the operator a few seconds after the console
      creates the component, so a missing Deployment is waited for, not reported as an error.
extends_documentation_fragment:
    - hyperledger.fabric_ansible_collection.k8s
'''

EXAMPLES = '''
- name: Create the certificate authority without checking its operations URL
  hyperledger.fabric_ansible_collection.certificate_authority:
    state: present
    api_endpoint: https://console.example.org:32000
    api_authtype: basic
    api_key: xxxxxxxx
    api_secret: xxxxxxxx
    name: Org1 CA
    config_override:
      ca:
        registry:
          maxenrollments: -1
          identities:
            - name: admin
              pass: adminpw
              type: client
    wait_mode: none

- name: Wait for the certificate authority in Kubernetes
  hyperledger.fabric_ansible_collection.k8s_component_ready:
    namespace: org1
    components:
      - Org1 CA
'''

RETURN = '''
---
components:
    description:
        - The components that are available.
    returned: always
    type: list
    elements: dict
    contains:
        name:
            description:
                - The name of the Deployment.
            type: str
            sample: org1ca
        replicas:
            description:
                - The number of available replicas.
            type: int
            sample: 1
'''


def rollout_status(deployment):
    """None if the Deployment is rolled out and available, else what it waits for.
    Same checks as kubectl rollout status."""
    if deployment is None:
        return 'the Deployment does not exist yet'
    status = deployment.status
    replicas = deployment.spec.replicas if deployment.spec.replicas is not None else 1
    if (status.observed_generation or 0) < deployment.metadata.generation:
        return 'the Deployment update is not observed yet'
    if (status.updated_replicas or 0) < replicas:
        return f'{status.updated_replicas or 0} of {replicas} replicas updated'
    if (status.replicas or 0) > (status.updated_replicas or 0):
        return 'old replicas are pending termination'
    if (status.available_replicas or 0) < replicas:
        return f'{status.available_replicas or 0} of {replicas} replicas available'
    return None


def main():

    # Create the module.
    argument_spec = k8s_connection_argument_spec()
    argument_spec.update(
        components=dict(type='list', elements='str', required=True),
        timeout=dict(type='int', default=600),
    )
    module = K8sModule(argument_spec=argument_spec, supports_check_mode=True)

    try:
        apps = client.AppsV1Api(get_api_client(module))
        namespace = module.params['namespace']
        names = [k8s_name(c) for c in module.params['components']]
        deadline = time.time() + module.params['timeout']
        pending = dict()
        ready = dict()
        while True:
            for name in names:
                if name in ready:
                    continue
                deployment = get_object(apps.read_namespaced_deployment, name, namespace)
                reason = rollout_status(deployment)
                if reason is None:
                    ready[name] = deployment.status.available_replicas
                    pending.pop(name, None)
                else:
                    pending[name] = reason
            if not pending:
                break
            if time.time() > deadline:
                details = ', '.join(f'{namespace}/{n}: {r}' for n, r in pending.items())
                raise Exception(f'Components not available within {module.params["timeout"]} seconds: {details}')
            time.sleep(2)

        module.exit_json(changed=False, components=[dict(name=n, replicas=ready[n]) for n in names])

    # Notify Ansible of the exception.
    except Exception as e:
        module.fail_json(msg=to_native(e))


if __name__ == '__main__':
    main()
