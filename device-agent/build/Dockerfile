# Builds the device agent's Windows installer (.msi) on Linux, so the PC needs no build tools: msitools writes
# the .msi, osslsigncode signs it for Windows when there is a certificate. The build context is the
# repository root; Dockerfile.dockerignore next to this file lets in the nine source files and nothing else.
#
# Two things are downloaded while the image is built, both pinned, both checked against a hash:
#   - Python's embeddable build for Windows, from python.org;
#   - the Windows wheels of `cryptography` and what it needs, from PyPI (requirements.txt).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends msitools wixl osslsigncode unzip curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG PYTHON_VERSION=3.12.10
ARG PYTHON_SHA256=4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3
RUN curl -fsSLo /tmp/python.zip https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip \
    && echo "${PYTHON_SHA256}  /tmp/python.zip" | sha256sum -c - \
    && mkdir -p /src/python && unzip -q /tmp/python.zip -d /src/python && rm /tmp/python.zip

COPY device-agent/build/requirements.txt /tmp/requirements.txt
RUN pip download --no-cache-dir --require-hashes -r /tmp/requirements.txt -d /tmp/wheels \
        --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312 --abi abi3 --abi none --only-binary=:all: \
    && mkdir -p /src/lib && for w in /tmp/wheels/*.whl; do unzip -q -o "$w" -d /src/lib; done && rm -rf /tmp/wheels \
    && pip install --no-cache-dir cryptography==44.0.0

COPY shadow-filer/fleet.py shadow-filer/apps.py shadow-filer/services.py shadow-filer/network.py shadow-filer/compliance.py /src/shared/
COPY device-agent/agent.py device-agent/winsvc.py device-agent/selfupdate.py device-agent/release.py /src/own/
COPY device-agent/build/make_msi.py /src/build/make_msi.py
ENTRYPOINT ["python", "/src/build/make_msi.py"]
