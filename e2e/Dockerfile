# Clean Ledger end-to-end test image.
#
# Holds: Claude Code, the analysis tools (pinned to the versions the plugin is
# tested with), the Clean Ledger plugin installed from this repository, and a
# clone of the test project with its git remote removed so nothing can be
# pushed. No credentials are baked in; the API key is passed at `docker run`.
#
# Build with `./e2e/run.sh build` (it uses the repository root as context).

FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.302
ARG LIZARD_VERSION=1.24.2
ARG SEMGREP_VERSION=1.182.1
ARG JSCPD_VERSION=5.4.2
ARG TEST_REPO=https://github.com/prettytable/prettytable.git
ARG TEST_REF=3.18.0
ARG PLUGIN_COMMIT=unknown

LABEL org.opencontainers.image.title="clean-ledger-e2e" \
      clean-ledger.plugin-commit="${PLUGIN_COMMIT}" \
      clean-ledger.test-repo="${TEST_REPO}@${TEST_REF}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends git python3 python3-venv ca-certificates coreutils \
 && rm -rf /var/lib/apt/lists/*

# Analysis tools in their own virtualenv; only the tool commands go on PATH,
# so the project's own dependencies never mix with Semgrep's.
RUN python3 -m venv /opt/tools \
 && /opt/tools/bin/pip install --no-cache-dir "lizard==${LIZARD_VERSION}" "semgrep==${SEMGREP_VERSION}" \
 && ln -s /opt/tools/bin/lizard /usr/local/bin/lizard \
 && ln -s /opt/tools/bin/semgrep /usr/local/bin/semgrep \
 && npm install -g --no-fund --no-audit "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" "jscpd@${JSCPD_VERSION}" \
 && npm cache clean --force

RUN useradd --create-home --shell /bin/bash builder \
 && mkdir -p /work /out /opt/clean-ledger \
 && chown builder:builder /work /out /opt/clean-ledger

COPY --chown=builder:builder . /opt/clean-ledger
COPY --chown=builder:builder e2e/container/ /usr/local/bin/

USER builder
WORKDIR /work
ENV PATH=/work/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1

RUN git config --global user.name "Clean Ledger E2E" \
 && git config --global user.email "e2e@localhost.invalid" \
 && git config --global init.defaultBranch main \
 && git config --global advice.detachedHead false

# Test project: full history (churn needs it), a local `main` at the tag,
# and no remote, so a push has nowhere to go.
RUN git clone --quiet "${TEST_REPO}" project \
 && cd project \
 && git checkout --quiet -B main "${TEST_REF}" \
 && git remote remove origin \
 && git rev-parse HEAD > /work/base-commit.txt

# The project's dependencies in a project virtualenv (first on PATH).
RUN python3 -m venv /work/venv \
 && /work/venv/bin/pip install --no-cache-dir -e "/work/project[tests]"

# Install the plugin the way a user would, from a local marketplace.
RUN claude plugin marketplace add /opt/clean-ledger \
 && claude plugin install clean-ledger@clean-ledger-marketplace \
 && claude plugin list

WORKDIR /work/project
CMD ["e2e-smoke"]
