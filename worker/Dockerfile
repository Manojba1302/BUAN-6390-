FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/worker

# tesseract is the OCR fallback for scans the PDF carries no text for
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr libgl1 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "worker.main"]
