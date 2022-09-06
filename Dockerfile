FROM python:3.10-slim-bullseye

RUN apt-get update && apt-get install -y bash tmux curl

RUN mkdir -p /zeus
WORKDIR /zeus
COPY . .

RUN pip install -r requirements.txt supervisor
CMD supervisord -c /zeus/supervisor.conf
