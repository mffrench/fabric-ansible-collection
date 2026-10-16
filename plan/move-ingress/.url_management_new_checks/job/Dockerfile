# Built in CI from the repository root:
#   docker build -t fabric-ansible-collection:ci .
#   docker build -t ansible-runner:ci -f .github/docker/ansible-runner/Dockerfile .
ARG BASE_IMAGE=fabric-ansible-collection:ci
FROM ${BASE_IMAGE}
# Test-only tools: jq, shasum (TEST_RUN_ID stamping), pip for yq.
USER root
RUN microdnf install -y jq perl-Digest-SHA python3-pip && microdnf clean -y all
USER 7051
# Python yq (run-tests.sh uses `yq -yi`, which mikefarah's yq does not support).
RUN python3.9 -m pip install --user yq
# Writable copy of the tests: run-tests.sh does `cd tutorial` relative to the repo root.
COPY --chown=7051:0 .github/scripts /workspace/.github/scripts
COPY --chown=7051:0 tutorial /workspace/tutorial
USER root
RUN chmod -R g=u /workspace
USER 7051
WORKDIR /workspace
ENTRYPOINT [ "/docker-entrypoint.sh" ]
CMD [ ".github/scripts/run-tests.sh" ]
