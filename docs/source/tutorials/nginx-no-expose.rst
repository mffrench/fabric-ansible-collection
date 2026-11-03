..
.. SPDX-License-Identifier: Apache-2.0
..

Exposing nothing with the nginx ingress controller
==================================================

This page deploys a network on a single Kubernetes cluster without exposing any of its components outside the cluster: the console, the certificate authorities, the peers and the ordering nodes are reached from inside the cluster only. The collection's design documents call this setup scenario B.

The setup needs the Hyperledger Fabric Open Source Stack on Kubernetes, and a version of the collection that has the ``expose_*`` variables. Read `Installing the Hyperledger Fabric Open Source Stack <./oss-installing.html>`_ and `Building a network <./building.html>`_ first: this page reuses their playbooks.

When to use this setup
----------------------

- **Single-cluster bootstrap.** Every organization of the network runs in the same cluster, so no component needs a name outside it.
- **Lead organization setup with GitOps.** One organization builds the network from inside its cluster. The console is exposed later, only if people need it.
- **Development environment.** No DNS record, no public certificate and no route to create.

Do not use it for a network whose organizations run in different clusters: their nodes must reach each other, so they need names that resolve outside their own cluster.

How the components are reached
------------------------------

**The console** keeps the URL built from ``exposed_domain``: ``https://<namespace>-<console_name>-console.<exposed_domain>``. Its TLS certificate covers this URL. Its Ingress exists, because the operator always creates one, but it has the class ``none``: no controller serves it, so the URL answers ``404``. Inside the cluster, the console is reached at ``https://<console_name>.<namespace>.svc.<cluster_domain>:3000``. You can expose it later without redeploying it: see `Exposing the console later`_.

**The nodes** get the names of Kubernetes Services. With ``hlf_network_domain`` set to the cluster domain, the name of an endpoint is ``<namespace>-<component_name>-<endpoint>.<namespace>.svc.<cluster_domain>``, for example ``fabric-org1peer-peer.fabric.svc.cluster.local``. For each endpoint, the collection creates a ClusterIP Service of that name, which forwards port ``443`` to the native port of the endpoint:

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Component
     - Endpoint
     - Native port
   * - Certificate authority
     - ``ca``, ``operations``
     - ``7054``, ``9443``
   * - Peer
     - ``peer``, ``operations``, ``grpcweb``
     - ``7051``, ``9443``, ``7443``
   * - Ordering node
     - ``orderer``, ``admin``, ``operations``, ``grpcweb``
     - ``7050``, ``9443``, ``8443``, ``7443``

The cluster DNS resolves these names with no change: the collection does not touch CoreDNS.

These names only resolve inside the cluster. So the playbooks that create the organizations must run inside the cluster, in a pod: they connect to the nodes by these names. The console playbook can run from your computer, because it only talks to the Kubernetes API.

Requirements of this setup
--------------------------

- A Kubernetes cluster and a namespace for the network. In the commands below, replace ``<namespace>`` with its name.
- ``kubectl`` access to that namespace, with the right to create a ServiceAccount, a Role and a RoleBinding. The right to create a Role in ``kube-system`` is optional: see `Running the organization playbooks inside the cluster`_.
- The collection installed on your computer, as described in `Installation <../installation.html>`_, to install the console.
- Docker, a clone of the collection repository at the version you installed, and a container registry that your cluster pulls images from.
- The nginx ingress controller, with SSL passthrough enabled, only if you expose the console later. The network itself does not use it.

Writing the variables file
--------------------------

Create a file ``no-expose-vars.yml``:

.. highlight:: yaml

::

    ---
    ingress_type: nginx
    expose_console: false
    expose_ca: false
    expose_peer: false
    expose_orderer: false
    # Domain of the console URL and of the console TLS certificate.
    exposed_domain: apps.my-cluster.example.org
    # The nodes get the names of their Kubernetes Services.
    hlf_network_domain: cluster.local
    # Namespace of the console and of every node.
    k8s_namespace: <namespace>

``hlf_network_domain`` is the cluster domain itself, ``cluster.local`` on most clusters, not ``<namespace>.svc.cluster.local``: the roles fail on a sub-zone of the cluster domain and print the value to use. The roles read the cluster domain from the ``kube-system/coredns`` ConfigMap. If it cannot be read, also set ``cluster_domain: cluster.local``: the roles then trust it and print a warning.

``expose_ca``, ``expose_peer`` and ``expose_orderer`` must stay ``false``: names under the cluster domain cannot be exposed, so the roles fail when one of them is ``true``. ``expose_console`` can be ``true``: the console is then exposed, and the nodes are not.

Installing the console without exposing it
------------------------------------------

Write the playbook ``install-oss.yml`` of `Installing the Hyperledger Fabric Open Source Stack <./oss-installing.html>`_, for Kubernetes, with two changes:

- In both plays, set ``namespace`` to the same value as ``k8s_namespace`` in ``no-expose-vars.yml``.
- Remove the ``console_domain`` line: ``exposed_domain`` comes from the variables file. The roles fail when both are set to different values.

Run it with the variables file:

.. highlight:: none

::

    ansible-playbook install-oss.yml -e @no-expose-vars.yml

The role waits for the console Deployment, not for its Ingress. At the end of the output, instead of the console URL, it prints where the console is:

::

    TASK [hyperledger.fabric_ansible_collection.network_domains : Print console exposition notice] ***
    ok: [localhost] => {
        "msg": [
            "Console URL (not exposed): https://fabric-hlf-console-console.apps.my-cluster.example.org",
            "Reachable in-cluster at: https://hlf-console.fabric.svc.cluster.local:3000",
            "To expose it, route the console URL to Service hlf-console port 3000 in namespace fabric, with TLS passthrough (for example an nginx Ingress with ssl-passthrough, or a Gateway API TLSRoute), or run again with expose_console: true."
        ]
    }

Keep the second address: the organization playbooks use it to reach the console.

Running the organization playbooks inside the cluster
-----------------------------------------------------

The playbooks of `Building a network <./building.html>`_ run in a pod, from the image of the collection.

1. Build the image from your clone of the repository and push it to your registry:

   ::

       docker build -t <registry>/fabric-ansible:<version> .
       docker push <registry>/fabric-ansible:<version>

   On a KIND cluster, load it instead of pushing it: ``kind load docker-image <registry>/fabric-ansible:<version>``.

2. Create a file ``in-cluster-vars.yml`` with the connection details of the console, through its in-cluster address:

   .. code-block:: yaml

       ---
       api_endpoint: https://<console_name>.<namespace>.svc.cluster.local:3000
       api_authtype: basic
       api_key: <console_email>
       api_secret: <console_default_password>

   These values replace the connection details of the organization variables files of the tutorial: both organizations use the same console.

3. Store both variables files in a Secret:

   ::

       kubectl create secret generic fabric-ansible-vars -n <namespace> \
           --from-file=no-expose-vars.yml --from-file=in-cluster-vars.yml

4. Create a file ``fabric-ansible.yml`` with the ServiceAccount of the pod, its rights and the pod itself. The pod creates no certificate authority, peer or ordering node: it asks the console, and the console creates them. It only manages the Services of the endpoints and reads the custom resources, the Ingress objects and the Deployments of the nodes:

   .. code-block:: yaml

       ---
       apiVersion: v1
       kind: ServiceAccount
       metadata: {name: fabric-ansible, namespace: <namespace>}
       ---
       apiVersion: rbac.authorization.k8s.io/v1
       kind: Role
       metadata: {name: fabric-ansible, namespace: <namespace>}
       rules:
         - apiGroups: [""]
           resources: [services]
           verbs: [get, list, create, patch, update, delete]
         - apiGroups: [ibp.com]
           resources: [ibpcas, ibppeers, ibporderers]
           verbs: [get, list, patch]
         - apiGroups: [networking.k8s.io]
           resources: [ingresses]
           verbs: [get, list]
         - apiGroups: [apps]
           resources: [deployments]
           verbs: [get, list]
       ---
       apiVersion: rbac.authorization.k8s.io/v1
       kind: RoleBinding
       metadata: {name: fabric-ansible, namespace: <namespace>}
       roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: fabric-ansible}
       subjects: [{kind: ServiceAccount, name: fabric-ansible, namespace: <namespace>}]
       ---
       apiVersion: v1
       kind: Pod
       metadata: {name: fabric-ansible, namespace: <namespace>}
       spec:
         serviceAccountName: fabric-ansible
         containers:
           - name: ansible
             image: <registry>/fabric-ansible:<version>
             command: [sleep, infinity]
             volumeMounts:
               - {name: vars, mountPath: /vars, readOnly: true}
         volumes:
           - name: vars
             secret: {secretName: fabric-ansible-vars}

   To let the roles read the cluster domain, add this Role and RoleBinding to ``fabric-ansible.yml``. Without them, set ``cluster_domain`` in ``no-expose-vars.yml``:

   .. code-block:: yaml

       ---
       apiVersion: rbac.authorization.k8s.io/v1
       kind: Role
       metadata: {name: fabric-ansible-coredns, namespace: kube-system}
       rules:
         - apiGroups: [""]
           resources: [configmaps]
           resourceNames: [coredns]
           verbs: [get]
       ---
       apiVersion: rbac.authorization.k8s.io/v1
       kind: RoleBinding
       metadata: {name: fabric-ansible-coredns, namespace: kube-system}
       roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: fabric-ansible-coredns}
       subjects: [{kind: ServiceAccount, name: fabric-ansible, namespace: <namespace>}]

5. Create the objects and wait for the pod:

   ::

       kubectl apply -f fabric-ansible.yml
       kubectl wait pod/fabric-ansible -n <namespace> --for=condition=Ready --timeout=5m

6. Clone the playbooks into the pod, at the version of the image:

   ::

       kubectl exec -n <namespace> fabric-ansible -- git clone --depth 1 --branch <version> \
           https://github.com/hyperledger-labs/fabric-ansible-collection.git /home/hlf-user/fabric-ansible-collection

7. Run the playbooks that ``build_network.sh build`` runs, in the same order, with both variables files:

   ::

       kubectl exec -n <namespace> fabric-ansible -- bash -c '
         set -e
         cd /home/hlf-user/fabric-ansible-collection/tutorial
         for playbook in 01-create-ordering-organization-components.yml \
             02-create-endorsing-organization-components.yml \
             05-enable-capabilities.yml 06-add-organization-to-consortium.yml \
             09-create-channel.yml 10-join-peer-to-channel.yml \
             11-add-anchor-peer-to-channel.yml; do
           ansible-playbook "$playbook" -e @/vars/no-expose-vars.yml -e @/vars/in-cluster-vars.yml
         done'

   Every ``PLAY RECAP`` must show ``failed=0``. The loop stops at the first playbook that fails.

8. The playbooks wrote the identities of the organizations into the tutorial directory of the pod, as described in `Building a network <./building.html>`_. The pod has no persistent storage: copy them to your computer before you delete it:

   ::

       for identity in "Ordering Org CA Admin" "Ordering Org Admin" "Org1 CA Admin" "Org1 Admin"; do
         kubectl exec -n <namespace> fabric-ansible -- \
           cat "/home/hlf-user/fabric-ansible-collection/tutorial/${identity}.json" > "${identity}.json"
       done

Checking that nothing is exposed
--------------------------------

1. The console URL answers ``404``: nginx does not serve it.

   ::

       curl -sk -o /dev/null -w '%{http_code}\n' https://<namespace>-<console_name>-console.<exposed_domain>/ak/api/v3/health

   ``404`` comes from the nginx ingress controller. Without the controller, or without a DNS record for the domain, ``curl`` fails to connect instead: the console is not exposed either.

2. The console answers inside the cluster. Without credentials, its API answers ``401``:

   ::

       kubectl exec -n <namespace> fabric-ansible -- \
           curl -sk -o /dev/null -w '%{http_code}\n' https://<console_name>.<namespace>.svc.cluster.local:3000/ak/api/v3/health

3. The Ingress of the console has the class ``none``, and the host of every node ends with ``.<namespace>.svc.cluster.local``:

   ::

       kubectl get ingress -n <namespace>

   ::

       NAME                   CLASS   HOSTS                                                                                                                                                                                                   ADDRESS     PORTS     AGE
       hlf-console            none    fabric-hlf-console-console.apps.my-cluster.example.org                                                                                                                                                              80, 443   17m
       orderingorgca          nginx   fabric-orderingorgca-ca.fabric.svc.cluster.local,fabric-orderingorgca-operations.fabric.svc.cluster.local                                                                                               localhost   80, 443   4m56s
       orderingservicenode1   nginx   fabric-orderingservicenode1-orderer.fabric.svc.cluster.local,fabric-orderingservicenode1-operations.fabric.svc.cluster.local,fabric-orderingservicenode1-grpcweb.fabric.svc.cluster.local + 1 more...   localhost   80, 443   3m56s
       org1ca                 nginx   fabric-org1ca-ca.fabric.svc.cluster.local,fabric-org1ca-operations.fabric.svc.cluster.local                                                                                                             localhost   80, 443   3m3s
       org1peer               nginx   fabric-org1peer-peer.fabric.svc.cluster.local,fabric-org1peer-operations.fabric.svc.cluster.local,fabric-org1peer-grpcweb.fabric.svc.cluster.local                                                      localhost   80, 443   111s

   No controller serves the Ingress of the console, so it has no ``ADDRESS``. The node Ingress objects keep the class ``nginx``: see `Not serving the node Ingress objects`_.

4. Every endpoint has its Service, and the nodes answer through it:

   ::

       kubectl get service -n <namespace> -l app.kubernetes.io/managed-by=fabric-ansible-collection
       kubectl exec -n <namespace> fabric-ansible -- \
           curl -sk https://<namespace>-org1peer-operations.<namespace>.svc.cluster.local/healthz

   The second command prints ``{"status":"OK",...}``.

Not serving the node Ingress objects
------------------------------------

The operator creates an Ingress for each certificate authority, peer and ordering node, with the class ``nginx`` and the names of the nodes as hosts. No client outside the cluster resolves these names, but a client that reaches the nginx ingress controller and sends one of these names still reaches the node.

To stop nginx serving them, add this line to ``no-expose-vars.yml`` before you run the organization playbooks:

.. highlight:: yaml

::

    neutralize_node_ingresses: true

The roles then give the class ``unexposed_ingress_class`` (``none`` by default) to the custom resources of the nodes, and wait for the operator to apply it. The Ingress objects are kept, with the class ``none``. A client that sends the name of a node to nginx then gets an answer from nginx itself, with the controller's default certificate, and no longer reaches the node.

On a network that already exists, update the Secret with the new file:

.. highlight:: none

::

    kubectl create secret generic fabric-ansible-vars -n <namespace> \
        --from-file=no-expose-vars.yml --from-file=in-cluster-vars.yml \
        --dry-run=client -o yaml | kubectl apply -f -

The pod sees the new file within a minute or two (``kubectl exec -n <namespace> fabric-ansible -- cat /vars/no-expose-vars.yml``). Then run ``01-create-ordering-organization-components.yml`` and ``02-create-endorsing-organization-components.yml`` again in the pod, as in step 7 of `Running the organization playbooks inside the cluster`_.

Exposing the console later
--------------------------

The console URL and its certificate do not change, so you can expose the console without redeploying it. Either:

- Run the console installation again with ``expose_console: true``. The class of its Ingress becomes ``nginx`` again:

  .. highlight:: none

  ::

      ansible-playbook install-oss.yml -e @no-expose-vars.yml -e expose_console=true

- Or route the console URL yourself to the console Service, port ``3000``, with TLS passthrough. With the nginx ingress controller:

  .. code-block:: yaml

      ---
      apiVersion: networking.k8s.io/v1
      kind: Ingress
      metadata:
        name: <console_name>-exposed
        namespace: <namespace>
        annotations:
          nginx.ingress.kubernetes.io/ssl-passthrough: "true"
          nginx.ingress.kubernetes.io/backend-protocol: HTTPS
      spec:
        ingressClassName: nginx
        rules:
          - host: <namespace>-<console_name>-console.<exposed_domain>
            http:
              paths:
                - path: /
                  pathType: ImplementationSpecific
                  backend:
                    service:
                      name: <console_name>
                      port: {number: 3000}

  A Gateway API ``TLSRoute`` to the same Service and port works the same way.

Removing the network
--------------------

Run the playbooks that ``build_network.sh destroy`` runs, in the pod. They also delete the Services of the endpoints:

.. highlight:: none

::

    kubectl exec -n <namespace> fabric-ansible -- bash -c '
      set -e
      cd /home/hlf-user/fabric-ansible-collection/tutorial
      for playbook in 97-delete-endorsing-organization-components.yml \
          99-delete-ordering-organization-components.yml; do
        ansible-playbook "$playbook" -e @/vars/no-expose-vars.yml -e @/vars/in-cluster-vars.yml
      done'

Then delete the pod, its rights and the Secret:

::

    kubectl delete -f fabric-ansible.yml
    kubectl delete secret fabric-ansible-vars -n <namespace>
