# k8s_endpoint_services

Internal role of the Hyperledger Fabric Ansible Collection, called by the `endorsing_organization` and
`ordering_organization` roles when a component is not exposed (`expose_ca`, `expose_peer` or
`expose_orderer` set to `false`).

The operator advertises every endpoint of a component as `<namespace>-<CR name>-<endpoint>.<domain>:443`.
This role creates one ClusterIP Service per endpoint, named `<namespace>-<CR name>-<endpoint>`, mapping
port 443 to the endpoint's container port. The operator's own Services are not modified.

See `docs/source/roles/k8s_endpoint_services.rst`.

## License

Apache-2.0
