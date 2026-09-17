FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

USER root
WORKDIR /var/task

COPY requirements.txt /var/task/requirements.txt
RUN --mount=type=secret,id=dependency-env --mount=type=secret,id=dependency-apt \
    set -a; if [ ! -f /run/secrets/dependency-env ]; then :; else . /run/secrets/dependency-env; fi; set +a; pip install --no-cache-dir -r /var/task/requirements.txt

COPY booker /var/task/booker
COPY bookings.yaml /var/task/bookings.yaml

ENV BOOKINGS_PATH=/var/task/bookings.yaml
ENV PYTHONPATH=/var/task
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

USER pwuser
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["booker.handler.lambda_handler"]
