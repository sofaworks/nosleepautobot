FROM python:3.10-slim-bullseye

RUN apt-get update && apt-get install -y curl
RUN curl -1sLf 'https://repositories.timber.io/public/vector/cfg/setup/bash.deb.sh' | bash
RUN apt-get update && apt-get -y upgrade && apt-get install -y vector

RUN mkdir -p /zeus
WORKDIR /zeus
COPY . .
COPY deploy/vector/vector.toml /etc/vector/vector.toml

RUN pip install -r requirements.txt supervisor
CMD ["supervisord", "-c", "/zeus/supervisor.conf"]
