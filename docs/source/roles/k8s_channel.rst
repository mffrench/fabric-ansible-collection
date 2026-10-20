..
.. SPDX-License-Identifier: Apache-2.0
..

:github_url: https://github.com/hyperledger-labs/fabric-ansible-collection/edit/main/docs/source/roles/k8s_channel.rst


k8s_channel -- Run the channel steps of an organization with Kubernetes Jobs
============================================================================

.. contents::
   :local:
   :depth: 1


Synopsis
--------

This role runs the channel steps of an organization when the ordering service or the peers are not exposed outside of the Kubernetes cluster: add organizations to the consortium of the system channel, create a channel, join peers, and set anchor peers.

Each step runs in a Kubernetes Job, in the namespace of the organization, signed by its administrator as published by the ``k8s_identity_bootstrap`` module (the ``endorsing_organization`` and ``ordering_organization`` roles with ``expose_ca: false``). The Ansible host only talks to the console of the organization and to the Kubernetes API.

Each organization runs the steps it is in charge of: a step runs when its variable is not empty. The steps do nothing when the network is already in the expected state.

Parameters
----------

  api_endpoint, api_authtype, api_key, api_secret, api_token_endpoint, api_timeout
    The console of the organization, to look up the ordering service, the organizations and the peers by name.

  namespace (required)
    The Kubernetes namespace of the organization, where its administrator is published and where the Jobs run.

    | **Type**: str

  organization_msp_id (required)
    The MSP ID of the organization whose administrator signs.

    | **Type**: str

  ordering_service_name (required)
    The cluster name of the ordering service in the console.

    | **Type**: str

  channel_name (required)
    The name of the channel.

    | **Type**: str

  consortium_organizations
    Ordering organization. The organizations to add to the consortium (module ``k8s_consortium_members``).

    | **Type**: list
    | **Default value**: ``[]``

  consortium
    The name of the consortium.

    | **Type**: str
    | **Default value**: ``SampleConsortium``

  system_channel
    The name of the system channel.

    | **Type**: str
    | **Default value**: ``testchainid``

  channel_organizations
    One member organization. The organizations of the channel to create (module ``k8s_channel``).

    | **Type**: list
    | **Default value**: ``[]``

  channel_policies
    The policies of the Application group of the channel (see the ``k8s_channel`` module).

    | **Type**: dict

  channel_capabilities
    The capabilities of the channel (see the ``k8s_channel`` module).

    | **Type**: dict
    | **Default value**: ``{}``

  join_peers
    Each member organization. Its peers to join to the channel (module ``k8s_channel_join``).

    | **Type**: list
    | **Default value**: ``[]``

  anchor_peers
    Each member organization. Its anchor peers (module ``k8s_anchor_peers``).

    | **Type**: list
    | **Default value**: ``[]``

  anchor_port
    The port of the anchor peers, instead of the port published by the console.

    | **Type**: int

  k8s_jobs
    Options of the Kubernetes Jobs: ``kubeconfig``, ``context``, ``images``, ``image_pull_policy``, ``image_pull_secrets``, ``host_aliases``, ``job_timeout``, ``name_prefix``.

    | **Type**: dict
    | **Default value**: ``{}``

Examples
--------

.. code-block:: yaml+jinja

  - name: Add the organizations to the consortium
    vars:
      api_endpoint: https://ordering-org-console.example.org
      api_authtype: basic
      api_key: xxxxxxxx
      api_secret: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
      namespace: ordering-org
      organization_msp_id: OrdererMSP
      ordering_service_name: Ordering Service
      channel_name: mychannel
      consortium_organizations: [Org1, Org2]
    roles:
      - hyperledger.fabric_ansible_collection.k8s_channel

  - name: Create the channel, join the peers and set the anchor peer of Org1
    vars:
      api_endpoint: https://org1-console.example.org
      api_authtype: basic
      api_key: xxxxxxxx
      api_secret: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
      namespace: org1
      organization_msp_id: Org1MSP
      ordering_service_name: Ordering Service
      channel_name: mychannel
      channel_organizations: [Org1, Org2]
      join_peers: [Org1 Peer1, Org1 Peer2]
      anchor_peers: [Org1 Peer1]
    roles:
      - hyperledger.fabric_ansible_collection.k8s_channel
