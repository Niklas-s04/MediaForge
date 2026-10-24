FROM clamav/clamav-debian:1.5.3

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /scratch/clamav /opt/clamav \
    && chown -R clamav:clamav /scratch
COPY --chown=clamav:clamav --chmod=0644 clamd.conf /etc/clamav/clamd.conf
COPY --chown=clamav:clamav --chmod=0644 freshclam.conf /etc/clamav/freshclam.conf
COPY --chmod=0644 gateway.py /opt/clamav/gateway.py
RUN chmod 0755 /opt /opt/clamav
USER clamav
# Fail the build if the runtime user cannot read files from a restrictive host context.
RUN python3 -c "from pathlib import Path; [Path(p).read_bytes() for p in ('/opt/clamav/gateway.py', '/etc/clamav/clamd.conf', '/etc/clamav/freshclam.conf')]"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/opt/clamav/gateway.py"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=6m --retries=3 CMD ["python3", "/opt/clamav/gateway.py", "--healthcheck"]
