FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt waitress==3.0.0
COPY . .
ENV FLASK_APP=run.py
EXPOSE 8000
# Tạo database, chạy migration, nạp dữ liệu mẫu (nếu trống) rồi khởi động web server
CMD flask init-db && flask db upgrade && flask seed && waitress-serve --port=8000 run:app
