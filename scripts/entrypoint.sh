#!/bin/bash
set -e

# No runtime filesystem permission fixes are required.
# The container runs as a non-root user and emits all logs to stdout,
# so there is no local log directory to chown. Any remaining arguments
# are passed directly to the application process.

exec "$@"
