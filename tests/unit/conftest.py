#
# SPDX-License-Identifier: Apache-2.0
#
import os
import sys
import tempfile

# The modules and module_utils import each other relatively, as members of the
# collection package: make the repository importable under its collection name.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_COLLECTIONS = tempfile.mkdtemp(prefix='fac-unit-')
os.makedirs(os.path.join(_COLLECTIONS, 'ansible_collections', 'hyperledger'))
os.symlink(_ROOT, os.path.join(_COLLECTIONS, 'ansible_collections', 'hyperledger', 'fabric_ansible_collection'))
sys.path.insert(0, _COLLECTIONS)
