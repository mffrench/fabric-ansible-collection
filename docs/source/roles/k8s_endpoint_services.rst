..
.. SPDX-License-Identifier: Apache-2.0
..

:github_url: https://github.com/hyperledger-labs/fabric-ansible-collection/edit/main/docs/source/roles/k8s_endpoint_services.rst


k8s_endpoint_services -- Create one Service per endpoint of the components that are not exposed
===============================================================================================

.. contents::
   :local:
   :depth: 1


Synopsis
--------

Internal role, called by the `endorsing_organization <./endorsing_organization.html>`_ and `ordering_organization <./ordering_organization.html>`_ roles when *expose_ca*, *expose_peer* or *expose_orderer* is ``false``. Kubernetes only: it requires the ``kubernetes.core`` collection and a kubeconfig.

The operator advertises every endpoint of a component on port 443, as ``<namespace>-<CR name>-<endpoint>.<domain>:443``, and its own Service for the component cannot map port 443 to more than one container port. This role creates one ClusterIP Service per endpoint instead, named ``<namespace>-<CR name>-<endpoint>``, mapping port 443 to the endpoint's container port:

=========================  ================  ==============
Component                  Endpoint          Container port
=========================  ================  ==============
Certificate authority      ``ca``            7054
Certificate authority      ``operations``    9443
Peer                       ``peer``          7051
Peer                       ``operations``    9443
Peer                       ``grpcweb``       7443
Ordering service node      ``orderer``       7050
Ordering service node      ``admin``         9443
Ordering service node      ``operations``    8443
Ordering service node      ``grpcweb``       7443
=========================  ================  ==============

The operator's own Services are not modified. The cluster DNS must send the component URLs to these Services, for example with one CoreDNS rewrite per endpoint type.

``tasks_from: verify``, run after the component is created, fails if a URL reported by the console for the component has no matching Service. ``tasks_from: delete`` deletes the Services.

Parameters
----------

  k8s_endpoint_services_namespace (required)
    The Kubernetes namespace of the console and of the components it creates.

    | **Type**: str

  k8s_endpoint_services_component (required)
    The kind of component: ``ca``, ``peer`` or ``orderer``.

    | **Type**: str

  k8s_endpoint_services_names (required)
    The console names of the components: the certificate authority name, the peer names, or the ordering service name.

    | **Type**: list
    | **Elements**: str

  k8s_endpoint_services_orderer_nodes
    The number of ordering service nodes. Only used for ``orderer``.

    | **Type**: int
    | **Default value**: ``1``

  k8s_endpoint_services_cr_name_regex
    The console names each operator custom resource after the component name, in lower case, without the characters matching this regular expression. For example, ``Org1 CA`` becomes ``org1ca``.

    | **Type**: str
    | **Default value**: ``[^a-z0-9]``

  k8s_endpoint_services_orderer_node_suffix
    Ordering service nodes are named ``<ordering service CR name><suffix><n>``, for example ``orderingservicenode1``.

    | **Type**: str
    | **Default value**: ``node``

  k8s_endpoint_services_selector_key
    The pod label holding the custom resource name, as used by the operator's own Services.

    | **Type**: str
    | **Default value**: ``app``

  k8s_endpoint_services_urls
    Only for ``tasks_from: verify``. The URLs reported by the console for the components (``api_url``, ``operations_url``, ``grpcwp_url``, ``osnadmin_url``). Empty values are ignored.

    | **Type**: list
    | **Elements**: str

Examples
--------

.. code-block:: yaml+jinja

  - name: Create the Services of the peer endpoints
    ansible.builtin.include_role:
      name: hyperledger.fabric_ansible_collection.k8s_endpoint_services
    vars:
      k8s_endpoint_services_namespace: fabricinfra
      k8s_endpoint_services_component: peer
      k8s_endpoint_services_names: ["Org1 Peer1", "Org1 Peer2"]
