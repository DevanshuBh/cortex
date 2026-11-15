# The image Coder-agent code runs in. Nothing but the Python standard library; no shell utilities needed.
FROM python:3.13.18-slim
RUN rm -rf /usr/bin/apt* /usr/bin/dpkg* /usr/bin/su /usr/bin/passwd /usr/bin/chsh /usr/bin/chfn /usr/bin/newgrp \
    /usr/bin/gpasswd /usr/bin/mount /usr/bin/umount && find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "-"]
