#!/usr/bin/python
#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type


from ..module_utils.k8s_fabric import (NODE_OUS_CONFIG, admin_object_names,
                                       b64, console_argument_spec, enroll_url,
                                       https_host_port, pem, sh)
from ..module_utils.k8s_jobs import (INPUT_DIR, MANAGED_BY, MANAGED_BY_LABEL,
                                     K8sJob, K8sModule, apply_config_map, container,
                                     ensure_service_account,
                                     fail_with_job_logs, get_api_client,
                                     get_object, k8s_job_argument_spec,
                                     pod_spec)
from ..module_utils.utils import (get_certificate_authority_by_module,
                                  get_console)

try:
    from kubernetes import client
except ImportError:
    pass  # get_api_client reports the missing library

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: k8s_identity_bootstrap
short_description: Register and enroll Hyperledger Fabric identities with a Kubernetes Job
description:
    - Register identities with a certificate authority, and enroll the administrator of the
      organization, from a Kubernetes Job that runs in the namespace of the certificate authority.
    - Use this module instead of the M(registered_identity) and M(enrolled_identity) modules when the
      certificate authority is not exposed outside of the Kubernetes cluster. The Ansible host only
      talks to the console (to look the certificate authority up) and to the Kubernetes API.
    - The private key of the administrator stays in the cluster, in the Secret I(<name_prefix>-admin-key).
      Its certificate is published in the ConfigMap I(<name_prefix>-admin-cert), and the certificates of
      the certificate authority in the ConfigMap I(<name_prefix>-ca-certs). The other C(k8s_*) modules
      sign with this administrator.
    - The administrator is only enrolled when its Secret or its ConfigMap is missing.
    - Identities that are already registered are left as they are.
options:
    certificate_authority:
        description:
            - The certificate authority to use.
            - You can pass a string, which is the display name of a certificate authority registered
              with the Fabric operations console.
            - You can also pass a dictionary, which must match the result format of one of the
              M(certificate_authority_info) or M(certificate_authority) modules.
        type: raw
        required: true
    ca_url:
        description:
            - The URL the Job uses to reach the certificate authority, for example
              C(https://org1-org1ca-ca.org1.svc.cluster.local:443).
            - Defaults to the API URL of the certificate authority, which must then resolve in the cluster.
        type: str
    registrar:
        description:
            - The identity that registers I(identities), usually the administrator of the certificate authority.
        type: dict
        required: true
        suboptions:
            enrollment_id:
                description:
                    - The enrollment ID of the registrar.
                type: str
                required: true
            enrollment_secret:
                description:
                    - The enrollment secret of the registrar.
                type: str
                required: true
    identities:
        description:
            - The identities to register, if they are not registered yet.
        type: list
        elements: dict
        default: []
        suboptions:
            enrollment_id:
                description:
                    - The enrollment ID of the identity.
                type: str
                required: true
            enrollment_secret:
                description:
                    - The enrollment secret of the identity.
                type: str
                required: true
            type:
                description:
                    - The type of the identity.
                type: str
                default: client
                choices:
                    - admin
                    - client
                    - peer
                    - orderer
            max_enrollments:
                description:
                    - The maximum number of times that the identity can be enrolled. C(-1) means no limit.
                type: int
                default: -1
            affiliation:
                description:
                    - The affiliation of the identity.
                type: str
                default: ''
            attributes:
                description:
                    - The attributes of the identity.
                type: list
                elements: dict
                default: []
                suboptions:
                    name:
                        description:
                            - The name of the attribute.
                        type: str
                        required: true
                    value:
                        description:
                            - The value of the attribute.
                        type: str
                        required: true
                    ecert:
                        description:
                            - Whether the attribute is added to the enrollment certificate by default.
                        type: bool
                        default: false
    admin:
        description:
            - The administrator of the organization to enroll. It must be registered, so list it in
              I(identities) too, with the type C(admin).
        type: dict
        suboptions:
            name:
                description:
                    - The name of the administrator, returned in I(enrolled_identity).
                type: str
                required: true
            enrollment_id:
                description:
                    - The enrollment ID of the administrator.
                type: str
                required: true
            enrollment_secret:
                description:
                    - The enrollment secret of the administrator.
                type: str
                required: true
    name_prefix:
        description:
            - The prefix of the names of the published Secret and ConfigMaps.
            - Defaults to I(namespace).
        type: str
    service_account:
        description:
            - The service account of the Job pod when it enrolls the administrator, the only pod that
              writes to the Kubernetes API (the Secret I(<name_prefix>-admin-key)).
        type: str
        default: fac-identity-bootstrap
    manage_service_account:
        description:
            - Whether to create I(service_account), with a Role (of the same name) that only allows to create
              Secrets and to get and patch the Secret I(<name_prefix>-admin-key).
            - Set to C(false) to use a service account managed elsewhere, with these permissions.
        type: bool
        default: true
extends_documentation_fragment:
    - hyperledger.fabric_ansible_collection.k8s
    - hyperledger.fabric_ansible_collection.k8s.jobs
    - hyperledger.fabric_ansible_collection.k8s.console
'''

EXAMPLES = '''
- name: Register the organization identities and enroll its administrator
  hyperledger.fabric_ansible_collection.k8s_identity_bootstrap:
    api_endpoint: https://console.example.org:32000
    api_authtype: basic
    api_key: xxxxxxxx
    api_secret: xxxxxxxx
    certificate_authority: Org1 CA
    namespace: org1
    registrar:
      enrollment_id: admin
      enrollment_secret: adminpw
    identities:
      - enrollment_id: org1admin
        enrollment_secret: org1adminpw
        type: admin
      - enrollment_id: org1peer
        enrollment_secret: org1peerpw
        type: peer
    admin:
      name: Org1 Admin
      enrollment_id: org1admin
      enrollment_secret: org1adminpw
  register: org1_identities

- name: Create the organization from the certificates returned by the Job
  hyperledger.fabric_ansible_collection.organization:
    api_endpoint: https://console.example.org:32000
    api_authtype: basic
    api_key: xxxxxxxx
    api_secret: xxxxxxxx
    name: Org1
    msp_id: Org1MSP
    root_certs: "{{ org1_identities.root_certs }}"
    intermediate_certs: "{{ org1_identities.intermediate_certs }}"
    tls_root_certs: "{{ org1_identities.tls_root_certs }}"
    tls_intermediate_certs: "{{ org1_identities.tls_intermediate_certs }}"
    admins:
      - "{{ org1_identities.enrolled_identity.cert }}"
'''

RETURN = '''
---
registered:
    description:
        - The enrollment IDs registered by this run (the identities that were not registered yet).
    returned: always
    type: list
    elements: str
enrolled_identity:
    description:
        - The administrator of the organization, in the result format of the M(enrolled_identity)
          module, without the private key (it stays in the Secret I(<name_prefix>-admin-key)).
    returned: when I(admin) is given
    type: dict
    contains:
        name:
            description:
                - The name of the administrator.
            type: str
        cert:
            description:
                - The base64 encoded PEM certificate of the administrator.
            type: str
        ca:
            description:
                - The base64 encoded PEM root certificate of the certificate authority.
            type: str
admin_enrolled:
    description:
        - Whether the administrator was enrolled by this run.
    returned: always
    type: bool
root_certs:
    description:
        - The base64 encoded PEM root certificates of the certificate authority.
    returned: always
    type: list
    elements: str
intermediate_certs:
    description:
        - The base64 encoded PEM intermediate certificates of the certificate authority.
    returned: always
    type: list
    elements: str
tls_root_certs:
    description:
        - The base64 encoded PEM root certificates of the TLS certificate authority.
    returned: always
    type: list
    elements: str
tls_intermediate_certs:
    description:
        - The base64 encoded PEM intermediate certificates of the TLS certificate authority.
    returned: always
    type: list
    elements: str
k8s_objects:
    description:
        - The names of the published Kubernetes objects.
    returned: always
    type: dict
    contains:
        key_secret:
            description:
                - The Secret with the private key of the administrator (key.pem).
            type: str
        cert_config_map:
            description:
                - The ConfigMap with the certificate of the administrator (cert.pem).
            type: str
        ca_certs_config_map:
            description:
                - The ConfigMap with the certificates of the certificate authority (ca-tls-cert.pem,
                  msp-root.pem, tls-root.pem) and the NodeOUs configuration (config.yaml).
            type: str
'''

CA_TLS_CERT = f'{INPUT_DIR}/ca-tls-cert.pem'


def ca_script(ca, ca_url, identities, enroll_admin):
    """Script of the fabric-ca-client container. It prints the public results
    as FAC_RESULT lines and leaves the administrator key in /work/out/key.pem."""
    lines = [
        'b64() { base64 < "$1" | tr -d "\\n"; }',
        'export FABRIC_CA_CLIENT_HOME=/work/home',
        f'CA_URL={sh(ca_url)}',
        f'CA_OPTS="--caname {ca.ca_name} --tls.certfiles {CA_TLS_CERT}"',
        '',
        '# Certificates of the certificate authority and of the TLS certificate authority',
        f'fabric-ca-client getcainfo -u "$CA_URL" --caname {sh(ca.ca_name)} --tls.certfiles {CA_TLS_CERT} -M /work/ca',
        f'fabric-ca-client getcainfo -u "$CA_URL" --caname {sh(ca.tlsca_name)} --tls.certfiles {CA_TLS_CERT} -M /work/tlsca',
        'for dir in ca tlsca; do',
        '  if [ "$dir" = ca ]; then kind=""; else kind="tls_"; fi',
        '  for f in /work/$dir/cacerts/*.pem; do',
        '    if [ -f "$f" ]; then echo "FAC_RESULT ${kind}root_cert $(b64 "$f")"; fi',
        '  done',
        '  for f in /work/$dir/intermediatecerts/*.pem; do',
        '    if [ -f "$f" ]; then echo "FAC_RESULT ${kind}intermediate_cert $(b64 "$f")"; fi',
        '  done',
        'done',
    ]
    if identities:
        lines += [
            '',
            '# Registrar, enrolled for this Job only',
            f'fabric-ca-client enroll $CA_OPTS -M /work/registrar -u "$(cat {INPUT_DIR}/registrar-url)" >/dev/null',
            'register_once() {',
            '  id="$1"; secret_file="$2"; shift 2',
            '  if fabric-ca-client identity list --id "$id" $CA_OPTS -M /work/registrar -u "$CA_URL" >/dev/null 2>&1; then',
            '    echo "identity $id is already registered"',
            '  else',
            '    fabric-ca-client register $CA_OPTS -M /work/registrar -u "$CA_URL" --id.name "$id" --id.secret "$(cat "$secret_file")" "$@"',
            '    echo "FAC_RESULT registered $id"',
            '  fi',
            '}',
        ]
        for i, identity in enumerate(identities):
            args = [f"--id.type={identity['type']}", f"--id.maxenrollments={identity['max_enrollments']}"]
            if identity['affiliation']:
                args.append(f"--id.affiliation={identity['affiliation']}")
            if identity['attributes']:
                attrs = ','.join(f"{a['name']}={a['value']}" + (':ecert' if a['ecert'] else '') for a in identity['attributes'])
                args.append(f'--id.attrs={attrs}')
            lines.append('register_once ' + sh(identity['enrollment_id'], f'{INPUT_DIR}/identity-{i}-secret', *args))
    if enroll_admin:
        lines += [
            '',
            '# Administrator of the organization',
            f'fabric-ca-client enroll $CA_OPTS -M /work/admin -u "$(cat {INPUT_DIR}/admin-url)" >/dev/null',
            'echo "FAC_RESULT admin_cert $(b64 "$(ls /work/admin/signcerts/*.pem | head -n 1)")"',
            'mkdir -p /work/out',
            'cp "$(ls /work/admin/keystore/*_sk | head -n 1)" /work/out/key.pem',
        ]
    return '\n'.join(lines) + '\n'


def publish_script(namespace, secret_name):
    """Script of the kubectl container: the only one that sees the private key."""
    return '\n'.join([
        f'kubectl -n {sh(namespace)} create secret generic {sh(secret_name)} --from-file=key.pem=/work/out/key.pem --dry-run=client -o yaml \\',
        f'  | kubectl label --local -f - {MANAGED_BY_LABEL}={MANAGED_BY} -o yaml \\',
        f'  | kubectl -n {sh(namespace)} apply -f -',
        f'echo "Secret {secret_name} published"',
    ]) + '\n'


def main():

    # Create the module.
    argument_spec = console_argument_spec(required=False)
    argument_spec.update(k8s_job_argument_spec())
    argument_spec.update(
        certificate_authority=dict(type='raw', required=True),
        ca_url=dict(type='str'),
        registrar=dict(type='dict', required=True, options=dict(
            enrollment_id=dict(type='str', required=True),
            enrollment_secret=dict(type='str', required=True, no_log=True),
        )),
        identities=dict(type='list', elements='dict', default=list(), options=dict(
            enrollment_id=dict(type='str', required=True),
            enrollment_secret=dict(type='str', required=True, no_log=True),
            type=dict(type='str', default='client', choices=['admin', 'client', 'peer', 'orderer']),
            max_enrollments=dict(type='int', default=-1),
            affiliation=dict(type='str', default=''),
            attributes=dict(type='list', elements='dict', default=list(), options=dict(
                name=dict(type='str', required=True),
                value=dict(type='str', required=True),
                ecert=dict(type='bool', default=False),
            )),
        )),
        admin=dict(type='dict', options=dict(
            name=dict(type='str', required=True),
            enrollment_id=dict(type='str', required=True),
            enrollment_secret=dict(type='str', required=True, no_log=True),
        )),
        name_prefix=dict(type='str'),
        service_account=dict(type='str', default='fac-identity-bootstrap'),
        manage_service_account=dict(type='bool', default=True),
    )
    required_if = [
        ('api_authtype', 'basic', ['api_secret']),
    ]
    module = K8sModule(argument_spec=argument_spec, supports_check_mode=False, required_if=required_if)

    try:
        p = module.params
        namespace = p['namespace']
        names = admin_object_names(p['name_prefix'] or namespace)
        admin = p['admin']

        # Look the certificate authority up: URL, CA names and TLS certificate.
        console = None
        if not isinstance(p['certificate_authority'], dict):
            if not p['api_endpoint']:
                raise Exception('api_endpoint is required when certificate_authority is a name')
            console = get_console(module)
        ca = get_certificate_authority_by_module(console, module)
        ca_url = p['ca_url'] or ca.api_url
        ca_url = f'https://{https_host_port(ca_url)}'

        api_client = get_api_client(module)
        core = client.CoreV1Api(api_client)

        # Enroll the administrator only once: a new enrollment would give a new
        # key, and the console and the channels know the current certificate.
        enroll_admin = False
        if admin:
            key = get_object(core.read_namespaced_secret, names['key_secret'], namespace)
            cert = get_object(core.read_namespaced_config_map, names['cert_config_map'], namespace)
            enroll_admin = not (key and 'key.pem' in (key.data or dict()) and cert and 'cert.pem' in (cert.data or dict()))

        # Job inputs, mounted at /fac/input.
        inputs = {'ca-tls-cert.pem': pem(ca.pem)}
        if p['identities']:
            inputs['registrar-url'] = enroll_url(ca_url, p['registrar']['enrollment_id'], p['registrar']['enrollment_secret'])
        for i, identity in enumerate(p['identities']):
            inputs[f'identity-{i}-secret'] = identity['enrollment_secret']
        if enroll_admin:
            inputs['admin-url'] = enroll_url(ca_url, admin['enrollment_id'], admin['enrollment_secret'])

        # fabric-ca-client, then kubectl to publish the private key if there is one.
        changed = False
        if enroll_admin and p['manage_service_account']:
            changed |= ensure_service_account(api_client, namespace, p['service_account'], [
                dict(apiGroups=[''], resources=['secrets'], verbs=['create']),
                dict(apiGroups=[''], resources=['secrets'], resourceNames=[names['key_secret']], verbs=['get', 'patch', 'update']),
            ])
        work = dict(name='work', emptyDir=dict())
        mounts = [dict(name='work', mountPath='/work')]
        ca_container = container(module, 'fabric-ca-client', 'fabric_ca', ca_script(ca, ca_url, p['identities'], enroll_admin), volume_mounts=mounts)
        if enroll_admin:
            spec = pod_spec(module,
                            init_containers=[ca_container],
                            containers=[container(module, 'publish', 'kubectl', publish_script(namespace, names['key_secret']), volume_mounts=mounts)],
                            volumes=[work],
                            service_account=p['service_account'])
        else:
            spec = pod_spec(module, containers=[ca_container], volumes=[work])
        results, logs = K8sJob(module, api_client, 'identity-bootstrap').run(spec, inputs)

        root_certs = results.get('root_cert', list())
        tls_root_certs = results.get('tls_root_cert', list())
        if not root_certs or not tls_root_certs:
            raise Exception('The Job did not return the root certificates of the certificate authority')
        registered = results.get('registered', list())
        changed |= bool(registered) or enroll_admin

        # Publish the public certificates.
        enrolled_identity = None
        if admin:
            if enroll_admin:
                admin_cert = results['admin_cert'][0]
                changed |= apply_config_map(core, namespace, names['cert_config_map'], {'cert.pem': pem(admin_cert)})
            else:
                admin_cert = b64(get_object(core.read_namespaced_config_map, names['cert_config_map'], namespace).data['cert.pem'])
            enrolled_identity = dict(name=admin['name'], cert=admin_cert, ca=root_certs[0])
        changed |= apply_config_map(core, namespace, names['ca_certs_config_map'], {
            'ca-tls-cert.pem': pem(ca.pem),
            'msp-root.pem': pem(root_certs[0]),
            'tls-root.pem': pem(tls_root_certs[0]),
            'config.yaml': NODE_OUS_CONFIG,
        })

        result = dict(
            changed=changed,
            registered=registered,
            admin_enrolled=enroll_admin,
            root_certs=root_certs,
            intermediate_certs=results.get('intermediate_cert', list()),
            tls_root_certs=tls_root_certs,
            tls_intermediate_certs=results.get('tls_intermediate_cert', list()),
            k8s_objects=names,
        )
        if enrolled_identity:
            result['enrolled_identity'] = enrolled_identity
        module.exit_json(**result)

    # Notify Ansible of the exception.
    except Exception as e:
        fail_with_job_logs(module, e)


if __name__ == '__main__':
    main()
