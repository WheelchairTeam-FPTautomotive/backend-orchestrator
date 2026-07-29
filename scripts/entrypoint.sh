#!/bin/bash
set -e

# Runtime permission fix for bind-mounted host directories.
# The container starts as root briefly so it can ensure the non-root
# app user owns the log directory, then it drops privileges and runs
# the application process.

chown -R appuser:appuser /app/logs

exec gosu appuser "$@"
