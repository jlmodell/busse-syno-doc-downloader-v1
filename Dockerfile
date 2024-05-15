FROM tiangolo/uvicorn-gunicorn-fastapi:latest

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

EXPOSE 8742

COPY . .

CMD ["uvicorn", "--host", "0.0.0.0", "--port", "8742", "main:app"]