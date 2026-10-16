#
# SPDX-License-Identifier: Apache-2.0
#

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import base64
import json
import logging
import os
import re
import time

from ansible.module_utils.basic import AnsibleModule, missing_required_lib

KUBERNETES_IMPORT_ERR = None
try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    HAS_KUBERNETES = True
except ImportError as e:
    HAS_KUBERNETES = False
    KUBERNETES_IMPORT_ERR = str(e)

# A Job container hands a value back to the module by printing a line
#   FAC_RESULT <key> <value>
# A key can be printed more than once: every value is kept, in order.
# Only public data (IDs, certificates) may be printed this way: the pod logs
# can be read by anyone allowed to read logs in the namespace.
RESULT_PREFIX = 'FAC_RESULT '

# Files handed to a Job (enrollment secrets, certificates, configuration) are
# stored in a Secret that only lives as long as the Job, mounted here.
INPUT_DIR = '/fac/input'

MANAGED_BY_LABEL = 'app.kubernetes.io/managed-by'
MANAGED_BY = 'fabric-ansible-collection'
OPERATION_LABEL = 'fabric-ansible-collection/operation'

DEFAULT_IMAGES = dict(
    fabric_ca='hyperledger/fabric-ca:1.5.15',
    fabric_tools='hyperledger/fabric-tools:2.5.15',
    kubectl='alpine/k8s:1.31.0',
)

DEFAULT_JOB_RESOURCES = dict(
    requests=dict(cpu='100m', memory='128Mi'),
    limits=dict(cpu='500m', memory='512Mi'),
)

# Waiting reasons that do not go away on their own.
STUCK_REASONS = ('ErrImagePull', 'ImagePullBackOff', 'InvalidImageName', 'CreateContainerConfigError')


class K8sModule(AnsibleModule):
    """Module of the k8s_* modules. Unlike BlockchainModule, it needs neither the
    Fabric SDK nor the Fabric binaries on the Ansible host: Fabric runs in the Jobs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not HAS_KUBERNETES:
            self.fail_json(msg=missing_required_lib('kubernetes'), exception=KUBERNETES_IMPORT_ERR)
        self.logger = None
        filename = os.environ.get('IBP_ANSIBLE_LOG_FILENAME')
        if filename:
            logging.basicConfig(filename=filename, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
            self.logger = logging.getLogger(self._name)

    def json_log(self, msg):
        # Called by the console client, as on BlockchainModule.
        if self.logger:
            self.logger.debug(json.dumps(msg, indent=4))


def k8s_connection_argument_spec():
    """Options of every module that talks to the Kubernetes API."""
    return dict(
        namespace=dict(type='str', required=True),
        kubeconfig=dict(type='path'),
        context=dict(type='str'),
    )


def k8s_job_argument_spec():
    """Options of every module that runs a Kubernetes Job."""
    spec = k8s_connection_argument_spec()
    spec.update(
        images=dict(type='dict', default=dict(), options=dict(
            fabric_ca=dict(type='str'),
            fabric_tools=dict(type='str'),
            kubectl=dict(type='str'),
        )),
        image_pull_policy=dict(type='str', default='IfNotPresent', choices=['Always', 'IfNotPresent', 'Never']),
        image_pull_secrets=dict(type='list', elements='str', default=list()),
        host_aliases=dict(type='list', elements='dict', default=list(), options=dict(
            ip=dict(type='str', required=True),
            hostnames=dict(type='list', elements='str', required=True),
        )),
        job_resources=dict(type='dict'),
        job_timeout=dict(type='int', default=300),
        job_cleanup=dict(type='str', default='on_success', choices=['always', 'on_success', 'never']),
    )
    return spec


def k8s_name(display_name):
    """Name the operator gives to the Kubernetes objects of a component: the
    console display name in lower case, without the characters other than a-z
    and 0-9 (for example, "Org1 CA" becomes "org1ca")."""
    return re.sub('[^a-z0-9]', '', display_name.lower())


def parse_results(text):
    """Collect the FAC_RESULT lines of a log, as {key: [values]}."""
    results = dict()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(RESULT_PREFIX):
            continue
        key, _, value = line[len(RESULT_PREFIX):].partition(' ')
        if key:
            results.setdefault(key, list()).append(value.strip())
    return results


def get_api_client(module):
    """Kubernetes API client: the kubeconfig (and context) of the module
    options or of the K8S_AUTH_KUBECONFIG / K8S_AUTH_CONTEXT variables, as for
    the kubernetes.core modules; the in-cluster configuration when Ansible runs
    in a pod and no kubeconfig is given."""
    if not HAS_KUBERNETES:
        module.fail_json(msg=missing_required_lib('kubernetes'), exception=KUBERNETES_IMPORT_ERR)
    kubeconfig = module.params.get('kubeconfig') or os.environ.get('K8S_AUTH_KUBECONFIG')
    context = module.params.get('context') or os.environ.get('K8S_AUTH_CONTEXT')
    try:
        in_cluster = os.environ.get('KUBERNETES_SERVICE_HOST') and not (kubeconfig or context or os.environ.get('KUBECONFIG'))
        if in_cluster:
            configuration = client.Configuration()
            config.load_incluster_config(client_configuration=configuration)
            return client.ApiClient(configuration)
        return config.new_client_from_config(config_file=kubeconfig, context=context)
    except Exception as e:
        module.fail_json(msg=f'Failed to load the Kubernetes configuration: {e}')


def image(module, name):
    return (module.params.get('images') or dict()).get(name) or DEFAULT_IMAGES[name]


def container(module, name, image_name, script, env=None, volume_mounts=None):
    """A container that runs a POSIX shell script with -e."""
    return dict(
        name=name,
        image=image(module, image_name),
        imagePullPolicy=module.params['image_pull_policy'],
        command=['sh', '-ec'],
        args=[script],
        env=[dict(name=k, value=str(v)) for k, v in (env or dict()).items()],
        volumeMounts=list(volume_mounts or list()),
        resources=module.params.get('job_resources') or DEFAULT_JOB_RESOURCES,
    )


def pod_spec(module, containers, init_containers=None, volumes=None, service_account=None):
    """Pod of a Job. The pod only gets a service account token when it needs one
    (to publish a Secret)."""
    spec = dict(
        restartPolicy='Never',
        containers=containers,
        volumes=list(volumes or list()),
    )
    if init_containers:
        spec['initContainers'] = init_containers
    if service_account:
        spec['serviceAccountName'] = service_account
    else:
        spec['automountServiceAccountToken'] = False
    if module.params.get('image_pull_secrets'):
        spec['imagePullSecrets'] = [dict(name=s) for s in module.params['image_pull_secrets']]
    if module.params.get('host_aliases'):
        spec['hostAliases'] = [dict(ip=a['ip'], hostnames=a['hostnames']) for a in module.params['host_aliases']]
    return spec


class K8sJobError(Exception):

    def __init__(self, msg, logs=None):
        super().__init__(msg)
        self.logs = logs or dict()


class K8sJob:
    """Runs one Kubernetes Job to completion and hands back what its containers
    printed. The Job gets its inputs from a short-lived Secret, mounted at
    /fac/input in every container."""

    def __init__(self, module, api_client, operation):
        self.module = module
        self.namespace = module.params['namespace']
        self.operation = operation
        self.core = client.CoreV1Api(api_client)
        self.batch = client.BatchV1Api(api_client)

    def labels(self):
        return {MANAGED_BY_LABEL: MANAGED_BY, OPERATION_LABEL: self.operation}

    def run(self, spec, inputs=None):
        """Run the pod spec as a Job. inputs is a dict of file name: content.
        Returns (results, logs): the FAC_RESULT values ({key: [values]}) and
        the logs of each container ({container: text})."""
        timeout = self.module.params['job_timeout']
        cleanup = self.module.params['job_cleanup']
        secret_name = None
        job_name = None
        succeeded = False
        try:
            if inputs:
                secret_name = self._create_input_secret(inputs)
                self._mount_inputs(spec, secret_name)
            job_name = self._create_job(spec, timeout)
            if secret_name:
                self._own_secret(secret_name, job_name)
            state, reason = self._wait(job_name, timeout)
            logs = self._logs(job_name)
            text = '\n'.join(logs.values())
            if state != 'succeeded':
                raise K8sJobError(f'Job {self.namespace}/{job_name} {state}: {reason}', logs)
            succeeded = True
            return parse_results(text), logs
        finally:
            if secret_name:
                self._delete_quietly(self.core.delete_namespaced_secret, secret_name)
            if job_name and (cleanup == 'always' or (cleanup == 'on_success' and succeeded)):
                self._delete_quietly(self.batch.delete_namespaced_job, job_name, propagation_policy='Background')

    def _create_input_secret(self, inputs):
        # Text files go as they are, binary files (bytes) base64 encoded. A Secret
        # holds at most 1 MiB.
        secret = self.core.create_namespaced_secret(self.namespace, dict(
            apiVersion='v1',
            kind='Secret',
            metadata=dict(generateName=f'fac-{self.operation}-input-', labels=self.labels()),
            type='Opaque',
            stringData={k: v for k, v in inputs.items() if not isinstance(v, bytes)},
            data={k: base64.b64encode(v).decode('ascii') for k, v in inputs.items() if isinstance(v, bytes)},
        ))
        return secret.metadata.name

    @staticmethod
    def _mount_inputs(spec, secret_name):
        spec.setdefault('volumes', list()).append(dict(
            name='fac-input',
            secret=dict(secretName=secret_name, defaultMode=0o400),
        ))
        for c in spec.get('initContainers', list()) + spec['containers']:
            c.setdefault('volumeMounts', list()).append(dict(name='fac-input', mountPath=INPUT_DIR, readOnly=True))

    def _create_job(self, spec, timeout):
        job = self.batch.create_namespaced_job(self.namespace, dict(
            apiVersion='batch/v1',
            kind='Job',
            metadata=dict(generateName=f'fac-{self.operation}-', labels=self.labels()),
            spec=dict(
                backoffLimit=0,
                activeDeadlineSeconds=timeout,
                ttlSecondsAfterFinished=3600,
                template=dict(metadata=dict(labels=self.labels()), spec=spec),
            ),
        ))
        return job.metadata.name

    def _own_secret(self, secret_name, job_name):
        # If the module dies before its own cleanup, the Job TTL removes the
        # Job and the garbage collector then removes the input Secret.
        job = self.batch.read_namespaced_job(job_name, self.namespace)
        self.core.patch_namespaced_secret(secret_name, self.namespace, dict(metadata=dict(ownerReferences=[dict(
            apiVersion='batch/v1', kind='Job', name=job_name, uid=job.metadata.uid,
        )])))

    def _wait(self, job_name, timeout):
        deadline = time.time() + timeout
        while True:
            job = self.batch.read_namespaced_job_status(job_name, self.namespace)
            status = job.status
            if status.succeeded:
                return 'succeeded', None
            if status.failed:
                return 'failed', self._conditions(status) or 'a container exited with an error'
            for condition in status.conditions or list():
                if condition.type == 'Failed' and condition.status == 'True':
                    return 'failed', f'{condition.reason}: {condition.message}'
            stuck = self._stuck_reason(job_name)
            if stuck:
                return 'failed', stuck
            if time.time() > deadline:
                return 'timed out', f'not finished after {timeout} seconds'
            time.sleep(2)

    @staticmethod
    def _conditions(status):
        # dict: the same reason can be in two conditions (FailureTarget, Failed).
        reasons = dict.fromkeys(f'{c.reason}: {c.message}' for c in status.conditions or list() if c.status == 'True')
        return '; '.join(reasons)

    def _pods(self, job_name):
        return self.core.list_namespaced_pod(self.namespace, label_selector=f'job-name={job_name}').items

    def _stuck_reason(self, job_name):
        for pod in self._pods(job_name):
            statuses = (pod.status.init_container_statuses or list()) + (pod.status.container_statuses or list())
            for s in statuses:
                waiting = s.state and s.state.waiting
                if waiting and waiting.reason in STUCK_REASONS:
                    return f'container {s.name}: {waiting.reason}: {waiting.message}'
        return None

    def _logs(self, job_name):
        logs = dict()
        for pod in self._pods(job_name):
            names = [c.name for c in pod.spec.init_containers or list()] + [c.name for c in pod.spec.containers]
            for name in names:
                try:
                    # Raw response: the deserialized one is str(bytes) in recent clients.
                    response = self.core.read_namespaced_pod_log(pod.metadata.name, self.namespace, container=name, _preload_content=False)
                    logs[name] = response.data.decode('utf-8', errors='replace')
                except ApiException:
                    pass
        return logs

    def _delete_quietly(self, delete, name, **kwargs):
        try:
            delete(name, self.namespace, **kwargs)
        except ApiException as e:
            if e.status != 404:
                self.module.warn(f'Failed to delete {name} in {self.namespace}: {e.reason}')


def fail_with_job_logs(module, e, **kwargs):
    """fail_json with the logs of the failed Job (secrets in module options are
    masked by Ansible, like in any module output)."""
    logs = getattr(e, 'logs', None)
    if logs:
        kwargs['job_logs'] = logs
    module.fail_json(msg=str(e), **kwargs)


def get_object(read, name, namespace):
    """Read a namespaced object, None if it does not exist."""
    try:
        return read(name, namespace)
    except ApiException as e:
        if e.status == 404:
            return None
        raise


def apply_config_map(core, namespace, name, data, labels=None):
    """Create or replace the ConfigMap. Returns True if it changed."""
    current = get_object(core.read_namespaced_config_map, name, namespace)
    body = dict(apiVersion='v1', kind='ConfigMap',
                metadata=dict(name=name, labels=labels or {MANAGED_BY_LABEL: MANAGED_BY}),
                data=data)
    if current is None:
        core.create_namespaced_config_map(namespace, body)
        return True
    if (current.data or dict()) == data:
        return False
    body['metadata']['labels'] = dict(current.metadata.labels or dict(), **body['metadata']['labels'])
    core.replace_namespaced_config_map(name, namespace, body)
    return True


def ensure_service_account(api_client, namespace, name, rules):
    """Service account of a Job pod, with a Role that only has the given rules.
    Returns True if something changed."""
    core = client.CoreV1Api(api_client)
    rbac = client.RbacAuthorizationV1Api(api_client)
    labels = {MANAGED_BY_LABEL: MANAGED_BY}
    changed = False
    if get_object(core.read_namespaced_service_account, name, namespace) is None:
        core.create_namespaced_service_account(namespace, dict(metadata=dict(name=name, labels=labels)))
        changed = True
    role = dict(apiVersion='rbac.authorization.k8s.io/v1', kind='Role', metadata=dict(name=name, labels=labels), rules=rules)
    current = get_object(rbac.read_namespaced_role, name, namespace)
    if current is None:
        rbac.create_namespaced_role(namespace, role)
        changed = True
    elif api_client.sanitize_for_serialization(current.rules) != rules:
        rbac.replace_namespaced_role(name, namespace, role)
        changed = True
    if get_object(rbac.read_namespaced_role_binding, name, namespace) is None:
        rbac.create_namespaced_role_binding(namespace, dict(
            metadata=dict(name=name, labels=labels),
            roleRef=dict(apiGroup='rbac.authorization.k8s.io', kind='Role', name=name),
            subjects=[dict(kind='ServiceAccount', name=name, namespace=namespace)],
        ))
        changed = True
    return changed
