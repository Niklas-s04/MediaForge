FROM clamav/clamav-debian:1.5.3

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /scratch/clamav /opt/clamav \
    && chown -R clamav:clamav /scratch
COPY --chown=clamav:clamav clamd.conf /etc/clamav/clamd.conf
COPY --chown=clamav:clamav freshclam.conf /etc/clamav/freshclam.conf
COPY gateway.py /opt/clamav/gateway.py
USER clamav
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/opt/clamav/gateway.py"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=6m --retries=3 CMD ["python3", "/opt/clamav/gateway.py", "--healthcheck"]
