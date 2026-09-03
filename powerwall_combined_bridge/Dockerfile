ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
    io.hass.name="Powerwall Combined Bridge" \
    io.hass.description="Combined Tesla Powerwall v1r and Shelly EM bridge" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}"

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

RUN \
    apk add --no-cache \
    python3 \
    py3-pip \
    && python3 -m venv "${VIRTUAL_ENV}" \
    && "${VIRTUAL_ENV}/bin/pip" install --no-cache-dir --upgrade pip \
    && "${VIRTUAL_ENV}/bin/pip" install --no-cache-dir \
    pypowerwall==0.17.1

COPY run.sh /
COPY rootfs/ /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]