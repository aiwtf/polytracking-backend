<<<<<<< HEAD
# Use python:3.9-slim as base image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements first to leverage cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Command to run the application
# Render sets the PORT environment variable automatically
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
=======
# 使用 Python 3.13
FROM python:3.13-slim

WORKDIR /app

# 安裝套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製程式碼
COPY . .

# 暴露 Render 需要的 port
EXPOSE 10000

# 啟動 FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
>>>>>>> 11db5788de2a15efac177cdec7d3ba2b0219c043
