FROM node:22-bookworm-slim AS pi-cli
RUN npm install --global --ignore-scripts @earendil-works/pi-coding-agent@1.1.0

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=pi-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=pi-cli /usr/local/bin/pi /usr/local/bin/pi
COPY --from=pi-cli /usr/local/lib/node_modules/@earendil-works /usr/local/lib/node_modules/@earendil-works
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --timeout=120 --retries=10 -r requirements.txt
RUN ln -sfn /usr/local/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js /usr/local/bin/pi
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY scripts ./scripts
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
