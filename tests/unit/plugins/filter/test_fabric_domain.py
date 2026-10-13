#
# SPDX-License-Identifier: Apache-2.0
#
import importlib.util
import os

import pytest

_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'plugins', 'filter', 'fabric_domain.py')
_SPEC = importlib.util.spec_from_file_location('fabric_domain', _PATH)
fabric_domain = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fabric_domain)


@pytest.mark.parametrize('domain, namespace, cluster_domain, expected', [
    ('example.com', 'fabricinfra', 'cluster.local', 'external'),
    ('127-0-0-1.nip.io', 'default', 'cluster.local', 'external'),
    ('localho.st', 'fabricinfra', 'cluster.local', 'external'),
    # looks internal, but outside the configured cluster domain
    ('fabricinfra.svc.mycluster.local', 'fabricinfra', 'cluster.local', 'external'),
    # a domain that only ends with the same characters is not inside the zone
    ('notcluster.local', 'fabricinfra', 'cluster.local', 'external'),
    ('fabricinfra.svc.cluster.local', 'fabricinfra', 'cluster.local', 'internal'),
    ('FabricInfra.SVC.Cluster.Local.', 'fabricinfra', 'cluster.local', 'internal'),
    ('fabricinfra.svc.mycluster.local', 'fabricinfra', 'mycluster.local', 'internal'),
    ('svc.cluster.local', 'fabricinfra', 'cluster.local', 'invalid'),
    ('cluster.local', 'fabricinfra', 'cluster.local', 'invalid'),
    ('other.svc.cluster.local', 'fabricinfra', 'cluster.local', 'invalid'),
    ('a.fabricinfra.svc.cluster.local', 'fabricinfra', 'cluster.local', 'invalid'),
])
def test_fabric_domain_kind(domain, namespace, cluster_domain, expected):
    assert fabric_domain.fabric_domain_kind(domain, namespace, cluster_domain) == expected


def test_default_cluster_domain():
    assert fabric_domain.fabric_domain_kind('fabricinfra.svc.cluster.local', 'fabricinfra') == 'internal'


def test_filter_is_registered():
    filters = fabric_domain.FilterModule().filters()
    assert filters['fabric_domain_kind'] is fabric_domain.fabric_domain_kind
