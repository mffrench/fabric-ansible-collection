#
# SPDX-License-Identifier: Apache-2.0
#
# Smart contract server (chaincode as a service), built from the source of the
# tutorial package: the peers dial it instead of building the chaincode.
FROM node:18-alpine AS source
ARG SOURCE_PACKAGE=fabcar@1.0.0.tgz
COPY ${SOURCE_PACKAGE} /tmp/package.tgz
RUN mkdir -p /tmp/code \
    && tar -xzf /tmp/package.tgz -C /tmp \
    && tar -xzf /tmp/code.tar.gz -C /tmp/code

FROM node:18-alpine
WORKDIR /usr/src/app
COPY --from=source /tmp/code/src/package.json /tmp/code/src/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=source /tmp/code/src/ ./
USER node
ENV CHAINCODE_SERVER_ADDRESS=0.0.0.0:9999
EXPOSE 9999
CMD ["sh", "-c", "exec ./node_modules/.bin/fabric-chaincode-node server --chaincode-address=\"$CHAINCODE_SERVER_ADDRESS\" --chaincode-id=\"$CHAINCODE_ID\""]
