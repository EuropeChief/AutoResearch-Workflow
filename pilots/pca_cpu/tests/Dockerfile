ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY . /tests/
RUN mkdir -p /logs/verifier /workspace/solution && chmod 700 /tests/private /logs/verifier && chmod 600 /tests/private/labels.json && chmod 700 /tests/grader.py /tests/test.sh && chmod 644 /tests/candidate_runner.py
WORKDIR /tmp
ENTRYPOINT []
CMD ["bash", "/tests/test.sh"]
