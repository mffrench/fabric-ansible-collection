..
.. SPDX-License-Identifier: Apache-2.0
..

Exposing everything with the nginx ingress controller
=====================================================

By default, the collection exposes every component of a network through the nginx ingress controller: the console, the certificate authorities, the peers and the ordering nodes. This page describes that default setup: which variables control it, what they default to, how to set them and how to check the result.

Nothing on this page changes how you install the software. Follow `Installing the Hyperledger Fabric Open Source Stack <./oss-installing.html>`_ or `Installing the IBM Support for Hyperledger Fabric <./hlfsupport-installing.html>`_ first.

.. note::

    nginx is the only ingress backend supported (``ingress_type: nginx``), on Kubernetes clusters whose nginx ingress controller has SSL passthrough enabled.

What the default exposes
------------------------

With the default values, every component gets an Ingress that nginx serves. The collection needs nothing else from you than the domain under which these components are reachable (``exposed_domain``).

The components are reachable under these names:

- The console: ``https://<namespace>-<console_name>-console.<exposed_domain>``.
- Every other component: ``<namespace>-<component_name>-<endpoint>.<domain>``, where ``<domain>`` is ``hlf_network_domain``, which defaults to ``exposed_domain``, and ``<endpoint>`` is one of:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Component
     - Endpoints
   * - Certificate authority
     - ``ca``, ``operations``
   * - Peer
     - ``peer``, ``operations``, ``grpcweb``
   * - Ordering node
     - ``orderer``, ``operations``, ``grpcweb``, ``admin``

Setting the exposure variables
------------------------------

With the defaults, the only variable to set is ``exposed_domain``. In the playbooks of the installation tutorials, replace the line:

.. highlight:: yaml

::

    console_domain: <console_domain>

with:

::

    exposed_domain: <exposed_domain>

``console_domain`` is the former name of ``exposed_domain``. It is still accepted, but it is deprecated: the roles print a deprecation notice when you use it, and they fail when both variables are set to different values.

You can also keep the variables in a file and pass it to ``ansible-playbook``:

::

    ---
    exposed_domain: apps.my-cluster.example.org

    # The other variables of this page, with their default values.
    # ingress_type: nginx
    # expose_console: true
    # expose_ca: true
    # expose_peer: true
    # expose_orderer: true

.. highlight:: none

::

    ansible-playbook install-oss.yml -e @vars.yml

The playbooks of the ``tutorial`` directory read the same variables from ``tutorial/common-vars.yml``.

Exposure variables reference
----------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 14 62

   * - Variable
     - Default
     - Effect
   * - ``ingress_type``
     - ``nginx``
     - The ingress backend. ``nginx`` is the only supported value.
   * - ``expose_console``
     - ``true``
     - The console is reachable from outside the cluster through its Ingress. When ``false``, its Ingress gets the class ``unexposed_ingress_class``, so that no controller serves it. The role then waits for the console Deployment instead of its Ingress, and prints the address of the console inside the cluster.
   * - ``expose_ca``, ``expose_peer``, ``expose_orderer``
     - ``true``
     - The certificate authorities, the peers and the ordering nodes are reachable from outside the cluster through their Ingress. When ``false``, the component is meant to be reached from inside the cluster only.
   * - ``expose_peer_operations``, ``expose_orderer_operations``, ``expose_grpcweb``
     - ``false``
     - No effect with nginx, which serves every endpoint of an exposed component. Reserved for the Gateway API backend.
   * - ``exposed_domain``
     - ``""``
     - The domain of the console URL and of the console TLS certificate. When empty, ``console_domain`` is used. One of the two is required by the console roles.
   * - ``console_domain``
     - none
     - Deprecated alias of ``exposed_domain``.
   * - ``hlf_network_domain``
     - ``""``
     - The domain of the names of the certificate authorities, peers and ordering nodes. When empty, ``exposed_domain`` is used, and all components share one domain. Set it to the domain of the cluster (usually ``cluster.local``) to give the nodes the names of their Kubernetes Services. The nodes must then not be exposed.
   * - ``cluster_domain``
     - ``""``
     - The DNS zone of the cluster. When empty, it is read from the ``kube-system/coredns`` ConfigMap, and only when it is needed: with the default values, the roles read nothing from the cluster. When set, it is checked against that ConfigMap if the ConfigMap can be read.
   * - ``unexposed_ingress_class``
     - ``none``
     - The Ingress class given to the components that are not exposed. No controller serves it.
   * - ``neutralize_node_ingresses``
     - ``false``
     - When ``true``, the custom resources of the unexposed certificate authorities, peers and ordering nodes also get ``unexposed_ingress_class``. Their Ingress is kept, but nginx no longer serves it.
   * - ``gateway_class_name``
     - ``fabric-envoy-gateway``
     - Reserved for the Gateway API backend. No effect with nginx.
   * - ``ingress_ca_port``, ``ingress_grpc_orderer_port``, ``ingress_grpc_peer_port``
     - ``7054``, ``7050``, ``7051``
     - Reserved for the Gateway API backend. No effect with nginx.
   * - ``network_domains_namespace``, ``network_domains_console_name``, ``network_domains_resolve_cluster_domain``, ``network_domains_urls``
     - ``""``, ``""``, ``false``, ``[]``
     - Inputs of the internal role that computes the domains. The roles that use it set them: do not set them yourself.

Checking the exposure
---------------------

List the Ingress objects of the namespace of your network:

.. highlight:: none

::

    kubectl get ingress -n <namespace>

When everything is exposed, you see one Ingress for the console, one for each certificate authority, one for each peer and one for each ordering node. The class of every Ingress is ``nginx``, and every host ends with your ``exposed_domain``. The output looks like this:

::

    NAME          CLASS   HOSTS                                                                                                                                                                       ADDRESS     PORTS     AGE
    hlf-console   nginx   fabric-hlf-console-console.apps.example.org                                                                                                                                 localhost   80, 443   12m
    org1ca        nginx   fabric-org1ca-ca.apps.example.org,fabric-org1ca-operations.apps.example.org                                                                                                  localhost   80, 443   9m
    org1peer1     nginx   fabric-org1peer1-peer.apps.example.org,fabric-org1peer1-operations.apps.example.org,fabric-org1peer1-grpcweb.apps.example.org                                               localhost   80, 443   7m
    ordnode1      nginx   fabric-ordnode1-orderer.apps.example.org,fabric-ordnode1-operations.apps.example.org,fabric-ordnode1-grpcweb.apps.example.org,fabric-ordnode1-admin.apps.example.org         localhost   80, 443   6m

The names of the Ingress objects and the ``ADDRESS`` and ``AGE`` columns depend on your components and on your cluster. A class other than ``nginx`` on a row means that the component is not exposed: check ``expose_*`` and ``unexposed_ingress_class``.
