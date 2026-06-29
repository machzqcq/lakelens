FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.7.2 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
# Lock still carries entries from the removed `databricks` optional group;
# `uv sync --no-dev` (no --extra) won't install them. Don't pass --frozen
# here — pyproject.toml's manifest hash changed, so let uv refresh the lock.
RUN uv sync --no-dev

COPY . .

CMD ["uv", "run", "--frozen", "--no-sync", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
