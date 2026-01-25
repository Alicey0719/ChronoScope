FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Tokyo

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY chrono_scope.py .

CMD ["python3", "chrono_scope.py"]