#!/bin/sh
set -e

# When Railway mounts a volume at /app/data, it's owned by root.
# Fix ownership so the non-root "app" user can write to it.
if [ -d /app/data ]; then
  chown -R app:app /app/data
fi

exec gosu app python bot.py
