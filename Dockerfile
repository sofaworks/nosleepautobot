FROM python:slim-bookworm

RUN apt-get update && apt-get install -y curl
RUN bash -c "$(curl -1sLf 'https://setup.vector.dev')"
RUN apt-get update && apt-get -y upgrade && apt-get install -y vector && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /zeus
WORKDIR /zeus
COPY . .
COPY deploy/vector/vector.toml /etc/vector/vector.toml

RUN pip install -r requirements.txt supervisor
CMD ["supervisord", "-c", "/zeus/supervisor.conf"]
