FROM python:3.12-slim

WORKDIR /app

COPY web/backend/requirements.txt /app/web/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/web/backend/requirements.txt

COPY . /app

RUN pip install --no-cache-dir -e /app

WORKDIR /app/web/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
