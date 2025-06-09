FROM python:slim-bookworm

RUN apt-get update && apt-get install -y curl
RUN apt-get update && apt-get -y upgrade && apt-get install build-essential -y && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /zeus
WORKDIR /zeus
COPY . .

RUN pip install -r requirements.txt supervisor
CMD ["supervisord", "-c", "/zeus/supervisor.conf"]
