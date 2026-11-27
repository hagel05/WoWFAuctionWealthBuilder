# Scanner + API for a server such as TrueNAS. Mount a volume at /data.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY wowflip ./wowflip
RUN pip install --no-cache-dir .
ENV WOWFLIP_DATA_DIR=/data \
    WOWFLIP_REPORT_DIR=/data/reports \
    WOWFLIP_ITEM_OVERRIDE_CSV=/data/items_override.csv \
    WOWFLIP_CONFIG=/data/config.toml \
    PYTHONUNBUFFERED=1
VOLUME /data
# API for the sync helpers on your PCs (see README, "In-game addon").
EXPOSE 8787
CMD ["wowflip", "serve", "--with-scanner"]
