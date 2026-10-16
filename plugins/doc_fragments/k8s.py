#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type


class ModuleDocFragment(object):

    # Options of every k8s_* module: the Kubernetes API.
    DOCUMENTATION = r'''
options:
    namespace:
        description:
            - The Kubernetes namespace of the components, where the Jobs run.
        type: str
        required: true
    kubeconfig:
        description:
            - The kubeconfig file to use. Defaults to the K8S_AUTH_KUBECONFIG or KUBECONFIG
              environment variables, then C(~/.kube/config); in a pod, the service account of the pod.
        type: path
    context:
        description:
            - The kubeconfig context to use. Defaults to the K8S_AUTH_CONTEXT environment variable,
              then the current context.
        type: str
requirements:
    - kubernetes (Python library)
'''

    # Options of the k8s_* modules that run a Kubernetes Job.
    JOBS = r'''
options:
    images:
        description:
            - The images of the Job containers.
        type: dict
        default: {}
        suboptions:
            fabric_ca:
                description:
                    - The image with C(fabric-ca-client). Defaults to C(hyperledger/fabric-ca:1.5.15).
                type: str
            fabric_tools:
                description:
                    - The image with C(peer), C(configtxlator) and C(jq). Defaults to C(hyperledger/fabric-tools:2.5.15).
                type: str
            kubectl:
                description:
                    - The image with C(kubectl). Defaults to C(alpine/k8s:1.31.0).
                type: str
    image_pull_policy:
        description:
            - The pull policy of the Job images.
        type: str
        default: IfNotPresent
        choices:
            - Always
            - IfNotPresent
            - Never
    image_pull_secrets:
        description:
            - The Secrets to pull the Job images with.
        type: list
        elements: str
        default: []
    host_aliases:
        description:
            - Entries added to C(/etc/hosts) in the Job pod, for the URLs published by the console
              that do not resolve in the cluster.
        type: list
        elements: dict
        default: []
        suboptions:
            ip:
                description:
                    - The IP address, for example the cluster IP of the Service of a component.
                type: str
                required: true
            hostnames:
                description:
                    - The host names to resolve to I(ip).
                type: list
                elements: str
                required: true
    job_resources:
        description:
            - The resources of each Job container. Defaults to requests of 100m CPU and 128Mi
              memory, and limits of 500m CPU and 512Mi memory.
        type: dict
    job_timeout:
        description:
            - The timeout, in seconds, to wait for the Job.
        type: int
        default: 300
    job_cleanup:
        description:
            - When to delete the Job. A Job that is kept is deleted one hour after it finished.
            - The Secret with the Job inputs is always deleted.
        type: str
        default: on_success
        choices:
            - always
            - on_success
            - never
notes:
    - The Job reaches the components from inside the cluster, at the URLs published by the console.
      They must resolve in the cluster (cluster DNS, or I(host_aliases)).
    - The secrets go to the Job in a Secret that is deleted with the Job, never in its specification.
      The pod logs only hold public data (IDs, certificates).
'''

    # Options of the k8s_* modules that look components up in the console.
    CONSOLE = r'''
options:
    api_endpoint:
        description:
            - The URL for the Fabric operations console.
            - Only required to look components up by name.
        type: str
    api_authtype:
        description:
            - C(ibmcloud) - Authenticate to the IBM Support for Hyperledger Fabric console using IBM Cloud
              authentication. You must provide a valid API key using I(api_key).
            - C(basic) - Authenticate to the Fabric operations console using basic authentication.
              You must provide both a valid API key using I(api_key) and API secret using I(api_secret).
        type: str
        choices:
            - ibmcloud
            - basic
    api_key:
        description:
            - The API key for the Fabric operations console.
        type: str
    api_secret:
        description:
            - The API secret for the Fabric operations console.
            - Only required when I(api_authtype) is C(basic).
        type: str
    api_timeout:
        description:
            - The timeout, in seconds, to use when interacting with the Fabric operations console.
        type: int
        default: 60
    api_token_endpoint:
        description:
            - The IBM Cloud IAM token endpoint to use when using IBM Cloud authentication.
            - Only required when I(api_authtype) is C(ibmcloud), and you are using IBM internal staging servers for testing.
        type: str
        default: https://iam.cloud.ibm.com/identity/token
'''

    # Options of the k8s_* modules that sign with the organization administrator.
    ADMIN = r'''
options:
    msp_id:
        description:
            - The MSP ID of the organization administrator that signs.
        type: str
        required: true
    name_prefix:
        description:
            - The prefix of the Kubernetes objects of the organization administrator, published by
              M(k8s_identity_bootstrap) (I(<name_prefix>-admin-key), I(<name_prefix>-admin-cert),
              I(<name_prefix>-ca-certs)). Defaults to I(namespace).
        type: str
'''

    # Options of the k8s_* modules that approve or commit a chaincode definition.
    CHAINCODE_DEFINITION = r'''
options:
    channel:
        description:
            - The name of the channel.
        type: str
        required: true
    name:
        description:
            - The name of the chaincode.
        type: str
        required: true
    version:
        description:
            - The version of the chaincode.
        type: str
        required: true
    sequence:
        description:
            - The sequence number of the chaincode definition.
        type: int
        required: true
    endorsement_policy:
        description:
            - The endorsement policy of the chaincode, as a signature policy, for example
              C(OR('Org1MSP.peer','Org2MSP.peer')).
            - Defaults to the C(Endorsement) policy of the channel.
        type: str
    endorsement_policy_ref:
        description:
            - The endorsement policy of the chaincode, as the name of a channel policy, for example
              C(/Channel/Application/Endorsement). Mutually exclusive with I(endorsement_policy).
        type: str
    init_required:
        description:
            - Whether the chaincode must be initialized before it is used.
        type: bool
        default: false
'''
