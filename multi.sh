#!/bin/sh
set -eu

usage() { printf "USAGE: %s NICK\n" "$0" >&2; }
if [ "$#" -ne 1 ]; then usage; exit 1; fi

case "$1" in -*) usage; exit 0 ;; esac
nick="$1"; shift

if type stdbuf >/dev/null 2>&1; then
    line_buffered() { stdbuf -oL -eL "$@"; }
else
    line_buffered() { "$@"; }
fi

for i in `cat ips`;  do
    file="pipeline-$i.py"
    sed 's/^\(\s\+\)\(#\s*\)\(.*\)%BIND_ADDRESS%/\1\3'"$i"'/' pipeline.py >"$file"
    printf "%s\n" "$file"
    line_buffered nohup run-pipeline "$file" --disable-web-server "$nick" >"$i.log" 2>&1 &
done
