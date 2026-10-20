#
# SPDX-License-Identifier: Apache-2.0
#
import shlex
from types import SimpleNamespace

from ansible_collections.hyperledger.fabric_ansible_collection.plugins.module_utils import k8s_fabric


def test_enroll_url_percent_encodes_the_credentials():
    url = k8s_fabric.enroll_url('https://org1-org1ca-ca.example.org', 'admin@org1', 'p:a/s@s w%rd')
    assert url == 'https://admin%40org1:p%3Aa%2Fs%40s%20w%25rd@org1-org1ca-ca.example.org:443'


def test_host_ports_default_to_443():
    assert k8s_fabric.https_host_port('https://ca.example.org') == 'ca.example.org:443'
    assert k8s_fabric.https_host_port('https://ca.example.org:7054') == 'ca.example.org:7054'
    assert k8s_fabric.grpc_host_port('grpcs://peer.example.org:443') == 'peer.example.org:443'
    assert k8s_fabric.grpc_host_port('grpcs://peer.example.org') == 'peer.example.org:443'


def test_tls_root_prefers_the_tls_ca_root_cert():
    assert k8s_fabric.tls_root(SimpleNamespace(tls_ca_root_cert='ROOT', pem='PEM')) == 'ROOT'
    assert k8s_fabric.tls_root(SimpleNamespace(tls_ca_root_cert=None, pem='PEM')) == 'PEM'


def test_needs_console_only_for_names():
    module = SimpleNamespace(params=dict(ordering_service=[dict(name='node')], peers=[dict(name='p')], one='Org1 Peer1'))
    assert not k8s_fabric.needs_console(module, 'ordering_service', 'peers')
    assert k8s_fabric.needs_console(module, 'peers', 'one')
    module.params['peers'] = [dict(name='p'), 'Org1 Peer2']
    assert k8s_fabric.needs_console(module, 'peers')


def test_admin_msp_volume_layout():
    volume = k8s_fabric.admin_msp_volume('org1')
    sources = volume['projected']['sources']
    assert sources[0]['secret']['name'] == 'org1-admin-key'
    assert sources[0]['secret']['items'] == [dict(key='key.pem', path='keystore/key.pem')]
    assert sources[1]['configMap']['name'] == 'org1-admin-cert'
    assert {i['path'] for i in sources[1]['configMap']['items']} == {'signcerts/cert.pem', 'admincerts/cert.pem'}
    assert sources[2]['configMap']['name'] == 'org1-ca-certs'


def test_pem_and_b64_round_trip():
    text = '-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n'
    assert k8s_fabric.pem(k8s_fabric.b64(text)) == text


def test_chaincode_definition_args_are_quoted():
    params = dict(channel='mychannel', name='mycc', version='1.0', sequence=2,
                  endorsement_policy="OR('Org1MSP.peer','Org2MSP.peer')", endorsement_policy_ref=None, init_required=True)
    args = shlex.split(k8s_fabric.chaincode_definition_args(params))
    assert args == ['-C', 'mychannel', '-n', 'mycc', '-v', '1.0', '--sequence', '2',
                    '--signature-policy', "OR('Org1MSP.peer','Org2MSP.peer')", '--init-required']
    params.update(endorsement_policy=None, endorsement_policy_ref='/Channel/Application/Endorsement', init_required=False)
    assert shlex.split(k8s_fabric.chaincode_definition_args(params))[-2:] == ['--channel-config-policy', '/Channel/Application/Endorsement']
