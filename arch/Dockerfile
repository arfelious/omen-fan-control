FROM archlinux:latest

RUN pacman -Syu --noconfirm && \
    pacman -S --noconfirm \
        base-devel \
        sudo \
        python-build \
        python-installer \
        python-hatchling \
        dkms \
    && \
    pacman -Scc --noconfirm && \
    pacman-key --init && \
    pacman-key --populate archlinux && \
    useradd -m builder && \
    echo 'builder ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers

USER builder
WORKDIR /src
