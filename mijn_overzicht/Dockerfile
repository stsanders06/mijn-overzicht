ARG BUILD_FROM
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /opt/app

COPY app/requirements.txt /opt/app/requirements.txt

RUN apk add --no-cache tzdata nginx \
    && pip3 install --no-cache-dir --break-system-packages -r /opt/app/requirements.txt

COPY app /opt/app
COPY rootfs /

RUN chmod a+x /usr/bin/mijn-overzicht

ARG BUILD_ARCH
ARG BUILD_VERSION=0.1.7
ENV ADDON_VERSION=${BUILD_VERSION}
LABEL \
    io.hass.name="Mijn Overzicht" \
    io.hass.description="Persoonlijk overzicht, alleen via de browser" \
    io.hass.type="addon" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.version="${BUILD_VERSION}"

CMD ["/usr/bin/mijn-overzicht"]
