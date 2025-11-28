# 使用輕量級 Python 3.9
FROM python:3.9-slim

# 設定工作目錄
WORKDIR /app

# 先複製 requirements.txt 並安裝依賴 (利用 Docker Cache 加速)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製其餘程式碼
COPY . .

# 啟動指令 (讓 Render 動態注入 PORT)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]