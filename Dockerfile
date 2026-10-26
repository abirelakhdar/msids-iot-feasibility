FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared shared
COPY gateway gateway
COPY umms umms
COPY idms idms
COPY dcms dcms
# The IDMS computes request features from the history of the home and runs the
# rule detector through the same interface a trained model would use.
COPY features features
COPY baselines baselines
