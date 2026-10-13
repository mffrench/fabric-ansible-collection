#
# SPDX-License-Identifier: Apache-2.0
#
import glob
import os

import pytest
import yaml

_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')

# Variables that several roles declare in their own defaults. Every role that
# declares one of them must use the same default value.
SHARED_VARIABLES = [
    'ingress_type',
    'expose_console',
    'expose_ca',
    'expose_peer',
    'expose_orderer',
    'cluster_domain',
    'namespace',
]

# Shared variables each role reads, and must therefore declare in its own defaults.
ROLE_READS = {
    'fabric_console': ['ingress_type', 'expose_console', 'expose_ca', 'expose_peer', 'expose_orderer', 'cluster_domain', 'namespace'],
    'hlfsupport_console': ['ingress_type', 'expose_console', 'expose_ca', 'expose_peer', 'expose_orderer', 'cluster_domain', 'namespace'],
    'endorsing_organization': ['expose_ca', 'expose_peer', 'namespace'],
    'ordering_organization': ['expose_ca', 'expose_orderer', 'namespace'],
}


def _role_defaults():
    defaults = {}
    for path in sorted(glob.glob(os.path.join(_ROOT, 'roles', '*', 'defaults', 'main.yml'))):
        role = os.path.basename(os.path.dirname(os.path.dirname(path)))
        with open(path) as f:
            defaults[role] = yaml.safe_load(f) or {}
    return defaults


@pytest.mark.parametrize('variable', SHARED_VARIABLES)
def test_shared_default_is_consistent(variable):
    values = {role: d[variable] for role, d in _role_defaults().items() if variable in d}
    assert values, '{0} is not declared in any role'.format(variable)
    assert len(set(map(repr, values.values()))) == 1, '{0} has different defaults: {1}'.format(variable, values)


@pytest.mark.parametrize('role', sorted(ROLE_READS))
def test_roles_declare_the_variables_they_read(role):
    missing = [v for v in ROLE_READS[role] if v not in _role_defaults()[role]]
    assert not missing, '{0} reads but does not declare: {1}'.format(role, missing)
