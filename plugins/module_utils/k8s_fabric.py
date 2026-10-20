#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import base64
import shlex
import urllib.parse

from .k8s_jobs import (INPUT_DIR, K8sJob, container, get_api_client,
                       get_object, pod_spec)
from .utils import get_console

try:
    from kubernetes import client
except ImportError:
    pass  # get_api_client reports the missing library

# Kubernetes objects that hold the administrator of an organization, for the
# Jobs to sign with.
#   <prefix>-admin-key   Secret     key.pem
#   <prefix>-admin-cert  ConfigMap  cert.pem
#   <prefix>-ca-certs    ConfigMap  ca-tls-cert.pem, msp-root.pem, tls-root.pem, config.yaml
NODE_OUS_CONFIG = '''NodeOUs:
  Enable: true
  ClientOUIdentifier:  { Certificate: cacerts/ca.pem, OrganizationalUnitIdentifier: client }
  PeerOUIdentifier:    { Certificate: cacerts/ca.pem, OrganizationalUnitIdentifier: peer }
  AdminOUIdentifier:   { Certificate: cacerts/ca.pem, OrganizationalUnitIdentifier: admin }
  OrdererOUIdentifier: { Certificate: cacerts/ca.pem, OrganizationalUnitIdentifier: orderer }
'''

ADMIN_MSP_DIR = '/etc/hyperledger/admin/msp'


def console_argument_spec(required=True):
    """Options of the modules that look components up in the console."""
    return dict(
        api_endpoint=dict(type='str', required=required),
        api_authtype=dict(type='str', required=required, choices=['ibmcloud', 'basic']),
        api_key=dict(type='str', required=required, no_log=True),
        api_secret=dict(type='str', no_log=True),
        api_timeout=dict(type='int', default=60),
        api_token_endpoint=dict(type='str', default='https://iam.cloud.ibm.com/identity/token'),
    )


def admin_object_names(prefix):
    return dict(
        key_secret=f'{prefix}-admin-key',
        cert_config_map=f'{prefix}-admin-cert',
        ca_certs_config_map=f'{prefix}-ca-certs',
    )


def admin_msp_volume(prefix, name='admin-msp'):
    """MSP directory of the organization administrator, from the objects that
    k8s_identity_bootstrap publishes."""
    names = admin_object_names(prefix)
    return dict(name=name, projected=dict(defaultMode=0o400, sources=[
        dict(secret=dict(name=names['key_secret'], items=[
            dict(key='key.pem', path='keystore/key.pem'),
        ])),
        dict(configMap=dict(name=names['cert_config_map'], items=[
            dict(key='cert.pem', path='signcerts/cert.pem'),
            dict(key='cert.pem', path='admincerts/cert.pem'),
        ])),
        dict(configMap=dict(name=names['ca_certs_config_map'], items=[
            dict(key='msp-root.pem', path='cacerts/ca.pem'),
            dict(key='config.yaml', path='config.yaml'),
        ])),
    ]))


def pem(b64_pem):
    """FAC certificates are base64 encoded PEM files."""
    return base64.b64decode(b64_pem).decode('utf-8')


def b64(pem_text):
    return base64.b64encode(pem_text.encode('utf-8')).decode('utf-8')


def https_host_port(url, default_port=443):
    """host:port of an https URL (the port the client must dial, never omitted)."""
    parts = urllib.parse.urlsplit(url)
    return f'{parts.hostname}:{parts.port or default_port}'


def enroll_url(url, enrollment_id, enrollment_secret):
    """https://<id>:<secret>@host:port, for fabric-ca-client. The ID and the
    secret are percent encoded, so that any character can be used."""
    quote = lambda s: urllib.parse.quote(s, safe='')  # noqa: E731
    return f'https://{quote(enrollment_id)}:{quote(enrollment_secret)}@{https_host_port(url)}'


def sh(*words):
    """Shell command line from words, each quoted."""
    return ' '.join(shlex.quote(str(w)) for w in words)


def grpc_host_port(url, default_port=443):
    """host:port of a grpcs:// URL published by the console."""
    parts = urllib.parse.urlsplit(url)
    return f'{parts.hostname}:{parts.port or default_port}'


def tls_root(component):
    """TLS root certificate (base64 PEM) to trust a peer or an ordering service node."""
    return component.tls_ca_root_cert or component.pem


def needs_console(module, *parameter_names):
    """Whether one of the parameters names a component, to be looked up in the console
    (the other values are results of the *_info modules)."""
    for name in parameter_names:
        value = module.params.get(name)
        values = value if isinstance(value, list) else [value]
        if any(isinstance(v, str) for v in values):
            return True
    return False


def admin_argument_spec():
    """Options of the modules that sign with the organization administrator."""
    return dict(
        msp_id=dict(type='str', required=True),
        name_prefix=dict(type='str'),
    )


def admin_job_spec(module, script, env=None):
    """Pod spec of a fabric-tools Job that signs with the organization administrator
    (published by k8s_identity_bootstrap). The pod gets no service account token."""
    prefix = module.params['name_prefix'] or module.params['namespace']
    env = dict(env or dict())
    env.update(
        CORE_PEER_LOCALMSPID=module.params['msp_id'],
        CORE_PEER_MSPCONFIGPATH=ADMIN_MSP_DIR,
        CORE_PEER_TLS_ENABLED='true',
    )
    mounts = [
        dict(name='admin-msp', mountPath=ADMIN_MSP_DIR, readOnly=True),
        dict(name='work', mountPath='/work'),
    ]
    tools = container(module, 'fabric-tools', 'fabric_tools', script, env=env, volume_mounts=mounts)
    return pod_spec(module, containers=[tools], volumes=[admin_msp_volume(prefix), dict(name='work', emptyDir=dict())])


# Fetch the latest configuration block of $CHANNEL and decode it to /work/config.json.
FETCH_CONFIG = '''peer channel fetch config /work/config_block.pb -c "$CHANNEL" -o "$ORDERER" --tls --cafile "$ORDERER_CA"
configtxlator proto_decode --type common.Block --input /work/config_block.pb | jq '.data.data[0].payload.data.config' > /work/config.json
'''

# Submit the difference between /work/config.json and /work/modified.json, signed
# by the administrator. Nothing is submitted (and UPDATED stays empty) when the
# two configurations are the same.
SUBMIT_UPDATE = '''jq -S . /work/config.json > /work/a.json
jq -S . /work/modified.json > /work/b.json
if cmp -s /work/a.json /work/b.json; then
  echo "the configuration of $CHANNEL is up to date"
else
  configtxlator proto_encode --type common.Config --input /work/config.json --output /work/config.pb
  configtxlator proto_encode --type common.Config --input /work/modified.json --output /work/modified.pb
  configtxlator compute_update --channel_id "$CHANNEL" --original /work/config.pb --updated /work/modified.pb --output /work/update.pb
  configtxlator proto_decode --type common.ConfigUpdate --input /work/update.pb \\
    | jq --arg ch "$CHANNEL" '{ payload: { header: { channel_header: { channel_id: $ch, type: 2 } }, data: { config_update: . } } }' \\
    | configtxlator proto_encode --type common.Envelope --output /work/update_envelope.pb
  peer channel update -f /work/update_envelope.pb -c "$CHANNEL" -o "$ORDERER" --tls --cafile "$ORDERER_CA"
  echo "FAC_RESULT updated true"
fi
'''


def get_console_if_needed(module, *parameter_names, needed=False):
    """The console client if one of the parameters names a component (or if
    needed), else None."""
    if not (needed or needs_console(module, *parameter_names)):
        return None
    if not module.params.get('api_endpoint'):
        raise Exception(f'api_endpoint is required to look up {", ".join(parameter_names)} by name')
    return get_console(module)


def orderer_settings(ordering_service):
    """Environment and inputs of a Job that talks to the ordering service:
    $ORDERER (host:port of its first node) and $ORDERER_CA (its TLS root)."""
    node = ordering_service.nodes[0]
    env = dict(ORDERER=grpc_host_port(node.api_url), ORDERER_CA=f'{INPUT_DIR}/orderer-tls.pem')
    return env, {'orderer-tls.pem': pem(tls_root(node))}


def check_admin_objects(api_client, namespace, prefix):
    """Fail early when the administrator is not published: the pod would wait
    for its volume until the Job times out."""
    core = client.CoreV1Api(api_client)
    names = admin_object_names(prefix)
    missing = list()
    if get_object(core.read_namespaced_secret, names['key_secret'], namespace) is None:
        missing.append(f'Secret {names["key_secret"]}')
    for name in (names['cert_config_map'], names['ca_certs_config_map']):
        if get_object(core.read_namespaced_config_map, name, namespace) is None:
            missing.append(f'ConfigMap {name}')
    if missing:
        raise Exception(f'The organization administrator is not published in {namespace} ({", ".join(missing)}): '
                        'enroll it with the k8s_identity_bootstrap module first')


def run_admin_job(module, operation, script, env, inputs):
    """Run a fabric-tools Job signed by the organization administrator."""
    api_client = get_api_client(module)
    check_admin_objects(api_client, module.params['namespace'], module.params['name_prefix'] or module.params['namespace'])
    spec = admin_job_spec(module, script, env)
    return K8sJob(module, api_client, operation).run(spec, inputs)


def chaincode_definition_argument_spec():
    """Options that define a chaincode, the same for approve and commit."""
    return dict(
        channel=dict(type='str', required=True),
        name=dict(type='str', required=True),
        version=dict(type='str', required=True),
        sequence=dict(type='int', required=True),
        endorsement_policy=dict(type='str'),
        endorsement_policy_ref=dict(type='str'),
        init_required=dict(type='bool', default=False),
    )


CHAINCODE_DEFINITION_MUTUALLY_EXCLUSIVE = [('endorsement_policy', 'endorsement_policy_ref')]


def chaincode_definition_args(params):
    """peer lifecycle arguments of the chaincode definition, quoted."""
    args = ['-C', params['channel'], '-n', params['name'], '-v', params['version'], '--sequence', params['sequence']]
    if params['endorsement_policy']:
        args += ['--signature-policy', params['endorsement_policy']]
    if params['endorsement_policy_ref']:
        args += ['--channel-config-policy', params['endorsement_policy_ref']]
    if params['init_required']:
        args.append('--init-required')
    return sh(*args)
