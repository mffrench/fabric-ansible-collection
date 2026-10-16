#
# SPDX-License-Identifier: Apache-2.0
#
from types import SimpleNamespace

import pytest

from ansible_collections.hyperledger.fabric_ansible_collection.plugins.module_utils import k8s_jobs


def module(**params):
    defaults = dict(namespace='org1', images=dict(), image_pull_policy='IfNotPresent',
                    image_pull_secrets=list(), host_aliases=list(), job_resources=None)
    defaults.update(params)
    return SimpleNamespace(params=defaults)


@pytest.mark.parametrize('display_name, expected', [
    ('Org1 CA', 'org1ca'),
    ('orgco1 Peer1', 'org1peer1'),
    (' Ordering Servicenode1', 'orderingservicenode1'),
    ('org1ca', 'org1ca'),
])
def test_k8s_name(display_name, expected):
    assert k8s_jobs.k8s_name(display_name) == expected


def test_parse_results_keeps_every_value_in_order():
    text = '\n'.join([
        '2026/10/15 [INFO] something',
        'FAC_RESULT registered org1admin',
        'FAC_RESULT root_cert AAAA',
        'FAC_RESULT registered org1peer',
        '  FAC_RESULT created true  ',
        'NOT_FAC_RESULT x y',
    ])
    assert k8s_jobs.parse_results(text) == dict(
        registered=['org1admin', 'org1peer'],
        root_cert=['AAAA'],
        created=['true'],
    )


def test_pod_spec_without_service_account_has_no_token():
    spec = k8s_jobs.pod_spec(module(), containers=[dict(name='c')])
    assert spec['automountServiceAccountToken'] is False
    assert 'serviceAccountName' not in spec
    assert spec['restartPolicy'] == 'Never'


def test_pod_spec_with_service_account_pull_secrets_and_host_aliases():
    m = module(image_pull_secrets=['registry'], host_aliases=[dict(ip='10.96.0.10', hostnames=['a.example.org'])])
    spec = k8s_jobs.pod_spec(m, containers=[dict(name='c')], init_containers=[dict(name='i')], service_account='sa')
    assert spec['serviceAccountName'] == 'sa'
    assert 'automountServiceAccountToken' not in spec
    assert spec['imagePullSecrets'] == [dict(name='registry')]
    assert spec['hostAliases'] == [dict(ip='10.96.0.10', hostnames=['a.example.org'])]
    assert spec['initContainers'] == [dict(name='i')]


def test_container_default_and_custom_images():
    c = k8s_jobs.container(module(), 'tools', 'fabric_tools', 'echo hi', env=dict(A=1))
    assert c['image'] == k8s_jobs.DEFAULT_IMAGES['fabric_tools']
    assert c['command'] == ['sh', '-ec'] and c['args'] == ['echo hi']
    assert c['env'] == [dict(name='A', value='1')]
    assert c['resources'] == k8s_jobs.DEFAULT_JOB_RESOURCES
    c = k8s_jobs.container(module(images=dict(fabric_tools='registry/tools:1')), 'tools', 'fabric_tools', 'true')
    assert c['image'] == 'registry/tools:1'


def test_inputs_are_mounted_in_every_container():
    spec = dict(containers=[dict(name='main')], initContainers=[dict(name='init')])
    k8s_jobs.K8sJob._mount_inputs(spec, 'input-secret')
    assert spec['volumes'] == [dict(name='fac-input', secret=dict(secretName='input-secret', defaultMode=0o400))]
    for c in spec['containers'] + spec['initContainers']:
        assert dict(name='fac-input', mountPath=k8s_jobs.INPUT_DIR, readOnly=True) in c['volumeMounts']
