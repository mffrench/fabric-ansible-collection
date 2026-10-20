..
.. SPDX-License-Identifier: Apache-2.0
..

:github_url: https://github.com/hyperledger-labs/fabric-ansible-collection/edit/main/docs/source/roles/k8s_chaincode.rst


k8s_chaincode -- Deploy a chaincode as a service with Kubernetes Jobs
=====================================================================

.. contents::
   :local:
   :depth: 1


Synopsis
--------

This role deploys a chaincode that runs as a service (CCaaS) for an organization, when its peers or the ordering service are not exposed outside of the Kubernetes cluster:

1. build the package of the chaincode on the Ansible host (module ``ccaas_package``): it only holds the address of the chaincode server, ``<name>-v<version>:<port>``;
2. install the package on the peers of the organization (module ``k8s_chaincode_install``);
3. run the chaincode server: a Deployment and a Service named ``<name>-v<version>``, in the namespace of the organization. Each version has its own server, so that the current version is served until the new one is committed;
4. approve the chaincode definition for the organization (module ``k8s_chaincode_approve``);
5. commit the chaincode definition (module ``k8s_chaincode_commit``), for the organization that commits, once enough organizations approved.

The Fabric steps run in Kubernetes Jobs signed by the administrator of the organization, as published by the ``k8s_identity_bootstrap`` module. The steps do nothing when the network is already in the expected state.

Parameters
----------

  api_endpoint, api_authtype, api_key, api_secret, api_token_endpoint, api_timeout
    The console of the organization, to look up the ordering service and the peers by name.

  namespace (required)
    The Kubernetes namespace of the organization, where its administrator is published, and where the Jobs and the chaincode server run.

    | **Type**: str

  organization_msp_id (required)
    The MSP ID of the organization.

    | **Type**: str

  ordering_service_name (required)
    The cluster name of the ordering service in the console.

    | **Type**: str

  channel_name (required)
    The name of the channel.

    | **Type**: str

  chaincode_name (required), chaincode_version (required)
    The name and the version of the chaincode.

    | **Type**: str

  chaincode_image (required)
    The image of the chaincode server.

    | **Type**: str

  chaincode_peers (required)
    The peers of the organization that run the chaincode. The first one approves and commits.

    | **Type**: list

  chaincode_sequence
    The sequence number of the chaincode definition.

    | **Type**: int
    | **Default value**: ``1``

  chaincode_port, chaincode_image_pull_policy, chaincode_resources
    The port, the pull policy and the resources of the chaincode server.

    | **Default value**: ``9999``, ``IfNotPresent``, requests of 50m CPU and 64Mi memory, limits of 300m CPU and 256Mi memory

  chaincode_endorsement_policy, chaincode_endorsement_policy_ref, chaincode_init_required
    The chaincode definition (see the ``k8s_chaincode_approve`` module).

  chaincode_package_dir
    The directory of the package on the Ansible host.

    | **Type**: str
    | **Default value**: the directory of the playbook

  chaincode_approve
    Whether to approve the chaincode definition for the organization.

    | **Type**: bool
    | **Default value**: ``true``

  chaincode_commit
    Whether to commit the chaincode definition.

    | **Type**: bool
    | **Default value**: ``false``

  chaincode_endorsing_peers
    The peers of the other organizations that endorse the commit: ``address``, and ``organization`` or ``tls_root_cert`` (see the ``k8s_chaincode_commit`` module).

    | **Type**: list
    | **Default value**: ``[]``

  k8s_jobs
    Options of the Kubernetes Jobs: ``kubeconfig``, ``context``, ``images``, ``image_pull_policy``, ``image_pull_secrets``, ``host_aliases``, ``job_timeout``, ``name_prefix``.

    | **Type**: dict
    | **Default value**: ``{}``

Examples
--------

.. code-block:: yaml+jinja

  - name: Deploy the chaincode for Org1, and commit it
    vars:
      api_endpoint: https://org1-console.example.org
      api_authtype: basic
      api_key: xxxxxxxx
      api_secret: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
      namespace: org1
      organization_msp_id: Org1MSP
      ordering_service_name: Ordering Service
      channel_name: mychannel
      chaincode_name: mycc
      chaincode_version: "1.0"
      chaincode_image: registry.example.org/mycc:1.0
      chaincode_peers: [Org1 Peer1, Org1 Peer2]
      chaincode_endorsement_policy: "OR('Org1MSP.peer','Org2MSP.peer')"
      chaincode_commit: true
      chaincode_endorsing_peers:
        - address: org2-org2peer1-peer.example.org:443
          organization: Org2
    roles:
      - hyperledger.fabric_ansible_collection.k8s_chaincode
