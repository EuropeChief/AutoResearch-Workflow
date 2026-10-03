ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY starter/ /workspace/starter/
COPY public_eval.py /workspace/public_eval/evaluate.py
RUN mkdir -p /workspace/solution && cp /workspace/starter/* /workspace/solution/ && chown -R 65534:65534 /workspace/solution && chmod -R a-w /workspace/starter /workspace/public_eval
WORKDIR /workspace/solution
USER 65534:65534
ENTRYPOINT []
CMD ["python", "/workspace/public_eval/evaluate.py"]
