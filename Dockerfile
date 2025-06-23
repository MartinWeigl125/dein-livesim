FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY live_data_insert.py .

CMD ["python", "live_data_insert.py"]
