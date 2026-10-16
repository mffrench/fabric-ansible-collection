#
# SPDX-License-Identifier: Apache-2.0
#
import gzip
import io
import json
import shlex
import tarfile
from types import SimpleNamespace

from ansible_collections.hyperledger.fabric_ansible_collection.plugins.modules import (
    ccaas_package, k8s_anchor_peers, k8s_channel, k8s_component_ready,
    k8s_identity_bootstrap)


def deployment(generation=1, observed=1, replicas=1, updated=1, total=1, available=1):
    return SimpleNamespace(
        metadata=SimpleNamespace(generation=generation),
        spec=SimpleNamespace(replicas=replicas),
        status=SimpleNamespace(observed_generation=observed, updated_replicas=updated,
                               replicas=total, available_replicas=available),
    )


def test_rollout_status():
    assert k8s_component_ready.rollout_status(None) == 'the Deployment does not exist yet'
    assert k8s_component_ready.rollout_status(deployment()) is None
    assert 'not observed' in k8s_component_ready.rollout_status(deployment(generation=2, observed=1))
    assert 'updated' in k8s_component_ready.rollout_status(deployment(updated=0))
    assert 'pending termination' in k8s_component_ready.rollout_status(deployment(total=2))
    assert 'available' in k8s_component_ready.rollout_status(deployment(available=0))


def test_identity_script_registers_with_quoted_arguments():
    ca = SimpleNamespace(ca_name='ca', tlsca_name='tlsca')
    identities = [
        dict(enrollment_id='org1admin', enrollment_secret='TOPSECRET-1', type='admin', max_enrollments=-1, affiliation='', attributes=[]),
        dict(enrollment_id="o'peer", enrollment_secret='TOPSECRET-2', type='peer', max_enrollments=5, affiliation='org1.department1',
             attributes=[dict(name='role', value='a b', ecert=True)]),
    ]
    script = k8s_identity_bootstrap.ca_script(ca, 'https://ca.example.org:443', identities, enroll_admin=True)
    lines = [line for line in script.splitlines() if line.startswith('register_once ')]
    assert shlex.split(lines[0]) == ['register_once', 'org1admin', '/fac/input/identity-0-secret',
                                     '--id.type=admin', '--id.maxenrollments=-1']
    assert shlex.split(lines[1]) == ['register_once', "o'peer", '/fac/input/identity-1-secret', '--id.type=peer',
                                     '--id.maxenrollments=5', '--id.affiliation=org1.department1', '--id.attrs=role=a b:ecert']
    assert '/fac/input/admin-url' in script and '/work/out/key.pem' in script
    # The secrets are read from the input files, never written in the script.
    assert 'TOPSECRET' not in script


def test_identity_script_without_identities_nor_admin_only_reads_the_ca():
    script = k8s_identity_bootstrap.ca_script(SimpleNamespace(ca_name='ca', tlsca_name='tlsca'), 'https://ca:443', [], False)
    assert 'getcainfo' in script
    assert 'registrar-url' not in script and 'admin-url' not in script


def test_channel_create_envelope():
    envelope = k8s_channel.channel_create_envelope('mychannel', 'SampleConsortium', ['Org1MSP', 'Org2MSP'],
                                                   k8s_channel.DEFAULT_POLICIES, dict(application='V2_0', channel=None, orderer=None))
    header = envelope['payload']['header']['channel_header']
    assert header == dict(channel_id='mychannel', type=2)
    update = envelope['payload']['data']['config_update']
    application = update['write_set']['groups']['Application']
    assert sorted(application['groups']) == ['Org1MSP', 'Org2MSP']
    assert sorted(application['policies']) == ['Admins', 'Endorsement', 'LifecycleEndorsement', 'Readers', 'Writers']
    assert application['values']['Capabilities']['value'] == dict(capabilities=dict(V2_0=dict()))
    assert update['write_set']['values']['Consortium']['value']['name'] == 'SampleConsortium'
    assert 'Capabilities' not in update['write_set']['values']


def test_channel_create_envelope_with_channel_and_orderer_capabilities():
    envelope = k8s_channel.channel_create_envelope('c', 'SampleConsortium', ['Org1MSP'], dict(),
                                                   dict(application='V2_0', channel='V2_0', orderer='V2_0'))
    update = envelope['payload']['data']['config_update']
    assert update['write_set']['values']['Capabilities']['value'] == dict(capabilities=dict(V2_0=dict()))
    assert 'Orderer' in update['read_set']['groups'] and 'Orderer' in update['write_set']['groups']


def test_anchor_peers_use_the_published_address_or_the_given_port():
    peers = [SimpleNamespace(api_url='grpcs://org1-org1peer1-peer.example.org:443'),
             SimpleNamespace(api_url='grpcs://org1-org1peer2-peer.example.org')]
    assert k8s_anchor_peers.anchor_peers(peers) == [
        dict(host='org1-org1peer1-peer.example.org', port=443),
        dict(host='org1-org1peer2-peer.example.org', port=443),
    ]
    assert [a['port'] for a in k8s_anchor_peers.anchor_peers(peers, 7051)] == [7051, 7051]


def test_ccaas_package_is_reproducible():
    first = ccaas_package.ccaas_package('mycc_1.0', 'mycc-v1-0:9999')
    assert first == ccaas_package.ccaas_package('mycc_1.0', 'mycc-v1-0:9999')
    assert first != ccaas_package.ccaas_package('mycc_1.0', 'mycc-v1-0:9998')
    assert ccaas_package.package_id('mycc_1.0', first).startswith('mycc_1.0:')

    with tarfile.open(fileobj=io.BytesIO(first), mode='r:gz') as tar:
        metadata = json.load(tar.extractfile('metadata.json'))
        code = tar.extractfile('code.tar.gz').read()
    assert metadata == dict(type='ccaas', label='mycc_1.0')
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(code))) as tar:
        connection = json.load(tar.extractfile('connection.json'))
    assert connection == dict(address='mycc-v1-0:9999', dial_timeout='10s', tls_required=False)
