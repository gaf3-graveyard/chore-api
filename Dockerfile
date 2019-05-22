FROM resin/raspberry-pi-alpine-python:3.6.1

RUN apk add git

COPY entry.sh /usr/bin/entry.sh

RUN mkdir -p /opt/nandy-io

WORKDIR /opt/nandy-io

ADD requirements.txt .

RUN pip install -r requirements.txt

ADD bin bin
ADD lib lib
ADD test test

ENV PYTHONPATH "/opt/nandy-io/lib:/opt/nandy-io/test:${PYTHONPATH}"

CMD "/opt/nandy-io/bin/api.py"
