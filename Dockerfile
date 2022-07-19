FROM debian:bullseye
ENV LANG C.UTF-8
WORKDIR /hiv-survdb
RUN apt-get update && apt-get -y install curl bzip2 unzip dos2unix sqlite3 jq pigz default-mysql-client
RUN curl -fsSL https://github.com/github-release/github-release/releases/download/v0.10.0/linux-amd64-github-release.bz2 -o github-release.bz2 && \
    bzip2 -d github-release.bz2 && \
    mv github-release /usr/bin/github-release && \
    chmod +x /usr/bin/github-release
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
RUN curl -fsSL https://github.com/shenwei356/csvtk/releases/download/v0.24.0/csvtk_linux_amd64.tar.gz -o csvtk.tar.gz && \
    tar -zxf csvtk.tar.gz && \
    mv csvtk /usr/bin/csvtk && \
    chmod +x /usr/bin/csvtk
RUN apt-get -y install nodejs
RUN npm install --location=global @dbml/cli
RUN curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o awscliv2.zip && \
    unzip awscliv2.zip && aws/install && rm -rf awscliv2.zip aws
RUN apt-get -y install git
RUN mkdir -p /local
