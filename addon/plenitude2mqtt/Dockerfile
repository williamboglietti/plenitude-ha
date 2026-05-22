ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python 3.12+ and dependencies
RUN apk add --no-cache python3 py3-pip

# Install runtime Python deps
COPY service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# Copy service code
COPY service /opt/plenitude2mqtt/service
COPY run.sh /

RUN chmod a+x /run.sh

CMD ["/run.sh"]
