"""Điểm khởi chạy ứng dụng: python run.py  (hoặc: flask run)"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
