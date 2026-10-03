FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime
COPY vendor/ /opt/pilot-codex/
ENV PATH="/opt/pilot-codex/bin:/opt/pilot-codex/codex-path:/opt/conda/bin:/usr/local/bin:/usr/bin:/bin"
ENV HOME="/tmp/pilot-home"
ENV PYTHONDONTWRITEBYTECODE="1"
COPY evaluate.py /opt/pilot/evaluate.py
RUN mkdir -p /opt/pilot/private-marker && chmod 700 /opt/pilot/private-marker && chmod 555 /opt/pilot/evaluate.py
ENTRYPOINT []
CMD ["python3", "--version"]
