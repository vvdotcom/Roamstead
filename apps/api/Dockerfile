FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
RUN pip install --no-cache-dir . \
    && addgroup --system --gid 10001 roamstead \
    && adduser --system --uid 10001 --ingroup roamstead --no-create-home roamstead \
    && mkdir -p /app/data \
    && chown -R roamstead:roamstead /app/data
USER roamstead
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
