FROM python:3.11-buster as builder
COPY requirements.txt requirements.txt
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim-buster
LABEL maintainer="bomzheg <bomzheg@gmail.com>" \
      description="Karma Telegram Bot"
ENV VIRTUAL_ENV=/opt/venv
COPY --from=builder $VIRTUAL_ENV $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
VOLUME /log
VOLUME /db_data
VOLUME /config
WORKDIR "."
EXPOSE 3000
VOLUME /config
COPY app app
ENTRYPOINT ["python3", "-m", "app", "-p"]
