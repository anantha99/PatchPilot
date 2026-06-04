FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    TMPDIR=/workspace/tmp \
    TEMP=/workspace/tmp \
    TMP=/workspace/tmp \
    PYTEST_DEBUG_TEMPROOT=/workspace/tmp/pytest

WORKDIR /workspace

COPY pyproject.toml README.md ./
COPY patchpilot ./patchpilot
RUN python -m pip install --upgrade pip \
    && python -m pip install -e ".[dev]"

COPY tests ./tests
COPY fixtures ./fixtures
COPY docs ./docs
COPY PRD.md PRODUCT.md assignment.md ./

RUN mkdir -p /workspace/tmp /workspace/tmp/pytest

CMD ["python", "-m", "pytest", "-q"]
