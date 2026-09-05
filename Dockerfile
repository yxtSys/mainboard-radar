FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY quant/ quant/
COPY webapp/server.py webapp/server.py
COPY webapp/static/ webapp/static/
COPY webapp/data/ webapp/data/

ENV PORT=7860
EXPOSE 7860

CMD ["python", "webapp/server.py"]
