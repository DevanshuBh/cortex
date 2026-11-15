# sandbox-runner: Python stdlib server plus the Docker CLI (Compose backend) and kubectl (k3s backend).
# With the Docker backend it reaches the host daemon through the mounted socket, which is root-equivalent — so it
# runs nothing but runner.py and exposes one narrow endpoint on the internal network only (docs/threat-model.md).
FROM docker:29.1.3-cli AS cli

FROM python:3.13.18-slim AS kubectl
ARG KUBECTL_VERSION=v1.37.2
ARG TARGETARCH=amd64
ADD https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl /kubectl
ADD https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl.sha256 /kubectl.sha256
RUN echo "$(cat /kubectl.sha256)  /kubectl" | sha256sum -c - && chmod 0755 /kubectl

FROM python:3.13.18-slim
COPY --from=cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=kubectl /kubectl /usr/local/bin/kubectl
COPY runner.py /app/runner.py
WORKDIR /app
EXPOSE 8090
CMD ["python", "-I", "/app/runner.py"]
