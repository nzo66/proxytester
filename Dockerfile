FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY app.py /app/

RUN pip install Flask

EXPOSE 7860

CMD ["python", "app.py"]
