FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir --default-timeout=1000 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY . .

CMD ["python", "main.py"]
