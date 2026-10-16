#!/usr/bin/python
#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import gzip
import hashlib
import io
import json
import os
import tarfile

from ansible.module_utils._text import to_native
from ansible.module_utils.basic import AnsibleModule

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: ccaas_package
short_description: Build the package of a chaincode that runs as an external service
description:
    - Build the package of a chaincode as a service (CCaaS) on the Ansible host, and compute its package ID.
      The package only holds the address of the chaincode server, not its code.
    - The package is reproducible. The same label and address give the same package, and the same package ID.
    - Install the package with the M(k8s_chaincode_install) or M(installed_chaincode) modules.
options:
    label:
        description:
            - The label of the package, usually C(<name>_<version>).
        type: str
        required: true
    address:
        description:
            - The address (C(host:port)) the peers dial to reach the chaincode server, for example the
              Kubernetes Service of the chaincode, C(mycc-v1-0:9999).
        type: str
        required: true
    dial_timeout:
        description:
            - The dial timeout of the peers.
        type: str
        default: 10s
    path:
        description:
            - The path of the package to write.
        type: path
        required: true
notes:
    - The peers connect to the chaincode server without TLS.
requirements: []
'''

EXAMPLES = '''
- name: Build the package of the chaincode
  hyperledger.fabric_ansible_collection.ccaas_package:
    label: mycc_1.0
    address: mycc-v1-0:9999
    path: mycc_1.0.tgz
  register: package
'''

RETURN = '''
---
path:
    description:
        - The path of the package.
    returned: always
    type: str
package_id:
    description:
        - The package ID of the package, C(<label>:<sha256 of the package>).
    returned: always
    type: str
'''


def targz(files):
    """tar.gz of (name, bytes), with fixed modes and dates, so that the same
    content gives the same bytes."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for name, data in files:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode='wb', mtime=0) as file:
        file.write(raw.getvalue())
    return compressed.getvalue()


def ccaas_package(label, address, dial_timeout='10s'):
    connection = json.dumps(dict(address=address, dial_timeout=dial_timeout, tls_required=False), indent=2).encode('utf-8')
    metadata = json.dumps(dict(type='ccaas', label=label), indent=2).encode('utf-8')
    return targz([('metadata.json', metadata), ('code.tar.gz', targz([('connection.json', connection)]))])


def package_id(label, package):
    return f'{label}:{hashlib.sha256(package).hexdigest()}'


def main():

    # Create the module.
    argument_spec = dict(
        label=dict(type='str', required=True),
        address=dict(type='str', required=True),
        dial_timeout=dict(type='str', default='10s'),
        path=dict(type='path', required=True),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    try:
        p = module.params
        package = ccaas_package(p['label'], p['address'], p['dial_timeout'])
        changed = True
        if os.path.exists(p['path']):
            with open(p['path'], 'rb') as file:
                changed = file.read() != package
        if changed and not module.check_mode:
            with open(p['path'], 'wb') as file:
                file.write(package)
        module.exit_json(changed=changed, path=p['path'], package_id=package_id(p['label'], package))

    # Notify Ansible of the exception.
    except Exception as e:
        module.fail_json(msg=to_native(e))


if __name__ == '__main__':
    main()
