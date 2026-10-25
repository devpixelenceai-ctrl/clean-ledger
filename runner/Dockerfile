# Clean Ledger fleet runner image: one throwaway container per repository.
#
# Contains Claude Code, the analysis tools (pinned) and the Clean Ledger plugin
# installed from this repository. Holds no repository and no credentials: the
# fleet mounts one prepared clone at /work/project and an evidence folder at
# /out, and passes ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN by name.
#
# Build from the repository root:
#   docker build -f runner/Dockerfile --build-arg PLUGIN_COMMIT=$(git rev-parse --short HEAD) \
#     -t clean-ledger-runner:latest .

FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.302
ARG LIZARD_VERSION=1.24.2
ARG SEMGREP_VERSION=1.182.1
ARG JSCPD_VERSION=5.4.2
ARG PLUGIN_COMMIT=unknown

LABEL org.opencontainers.image.title="clean-ledger-runner" \
      clean-ledger.plugin-commit="${PLUGIN_COMMIT}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends git python3 python3-venv python3-pip ca-certificates coreutils \
 && rm -rf /var/lib/apt/lists/*

# Analysis tools in their own virtualenv; only the commands go on PATH.
RUN python3 -m venv /opt/tools \
 && /opt/tools/bin/pip install --no-cache-dir "lizard==${LIZARD_VERSION}" "semgrep==${SEMGREP_VERSION}" \
 && ln -s /opt/tools/bin/lizard /usr/local/bin/lizard \
 && ln -s /opt/tools/bin/semgrep /usr/local/bin/semgrep \
 && npm install -g --no-fund --no-audit "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" "jscpd@${JSCPD_VERSION}" \
 && npm cache clean --force

RUN useradd --create-home --shell /bin/bash builder \
 && mkdir -p /work/project /out /opt/clean-ledger \
 && chown -R builder:builder /work /out /opt/clean-ledger

COPY --chown=builder:builder . /opt/clean-ledger
COPY --chown=builder:builder runner/container/ /usr/local/bin/

USER builder
WORKDIR /work/project
RUN git config --global user.name "Clean Ledger Fleet" \
 && git config --global user.email "fleet@localhost.invalid" \
 && git config --global --add safe.directory /work/project \
 && claude plugin marketplace add /opt/clean-ledger \
 && claude plugin install clean-ledger@clean-ledger-marketplace \
 && claude plugin list

CMD ["fleet-run"]
