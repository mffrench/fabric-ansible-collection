#!/bin/sh
# Return the IP address that should be used as the Kind API server address and
# as the base for the nip.io ingress domain.
#
# On Linux the Docker bridge gateway (from inside a container) is the correct
# address because Kind port-mappings are bound to the host network interface.
#
# On macOS (Darwin) Docker Desktop maps Kind's host-ports to the loopback
# interface (127.0.0.1) rather than to the Docker bridge, so 127.0.0.1 is
# the only address from which the host can reach the ingress.

if [ "$(uname)" = "Darwin" ]; then
    echo "127.0.0.1"
else
    cat <<EOF | docker run --rm -i alpine:latest sh
apk add --no-cache iproute2 >/dev/null
ip -4 route show default | cut -d' ' -f3
EOF
fi