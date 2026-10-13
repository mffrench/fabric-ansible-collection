#
# SPDX-License-Identifier: Apache-2.0
#


def fabric_domain_kind(domain, namespace, cluster_domain='cluster.local'):
    """Classify a console domain against the Kubernetes cluster domain.

    The operator builds every component FQDN as <ns>-<name>-<role>.<domain>.

    - 'external': the domain is outside the cluster domain. Component FQDNs are
      resolved by external DNS (or by a CoreDNS rewrite) and routed through an
      ingress.
    - 'internal': the domain is <namespace>.svc.<cluster_domain>. Component
      FQDNs have the shape of Kubernetes Service FQDNs, so they only resolve if a
      Service named <ns>-<name>-<role> exists in <namespace>.
    - 'invalid': any other domain inside the cluster domain (for example
      svc.<cluster_domain> or <other-ns>.svc.<cluster_domain>). Component FQDNs
      built from it can never resolve.
    """
    domain = str(domain).strip().lower().rstrip('.')
    zone = str(cluster_domain).strip().lower().rstrip('.')
    if domain != zone and not domain.endswith('.' + zone):
        return 'external'
    if domain == '{0}.svc.{1}'.format(str(namespace).strip().lower(), zone):
        return 'internal'
    return 'invalid'


class FilterModule(object):

    def filters(self):
        return {
            'fabric_domain_kind': fabric_domain_kind,
        }
