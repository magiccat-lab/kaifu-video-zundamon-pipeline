#!/usr/bin/env bash
# VOICEVOX エンジン (既定 127.0.0.1:50021) を使う時だけ起こし、終わったら止める。
#
# 手で起こしたエンジンが動きっぱなしになってメモリを持ち続けるのを避けるため、使う間だけ起こす。
# systemd の一時ユニット voicevox-engine-<port> (user unit) で起こすので、端末が落ちても残らず、
# RuntimeMaxSec (既定 4 時間) で止め忘れても必ず落ちる。
#
# 必須 (start の時): VOICEVOX_DIR = VOICEVOX ENGINE を展開した dir (その中の run を起こす)
# 任意: VOICEVOX_PORT (既定 50021) ・ VOICEVOX_MAX_RUNTIME (既定 4h)
#
#   scripts/voicevox.sh start    起こして /version が返るまで待つ (もう動いていれば何もしない)
#   scripts/voicevox.sh stop     止める (手で起こした物もポートから PID を引いて止める)
#   scripts/voicevox.sh status   動いているか ・ メモリ
set -euo pipefail

PORT="${VOICEVOX_PORT:-50021}"
DIR="${VOICEVOX_DIR:-}"
MAX="${VOICEVOX_MAX_RUNTIME:-4h}"
UNIT="voicevox-engine-${PORT}"
URL="http://127.0.0.1:${PORT}/version"

up() { curl -s -m 2 "$URL" >/dev/null 2>&1; }

port_pid() {
  # 見つからない時も 0 で返す (set -e で黙って落ちないように)
  ss -ltnp 2>/dev/null | awk -v p=":${PORT}" '$4 ~ p"$" {print}' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true
}

case "${1:-status}" in
  start)
    if [ -z "$DIR" ]; then
      echo "VOICEVOX_DIR is not set (the directory that contains the engine's 'run' executable)" >&2
      exit 2
    fi
    if up; then
      echo "already running on ${PORT} ($(curl -s -m 2 "$URL"))"
      exit 0
    fi
    systemd-run --user --unit="$UNIT" --collect --property=RuntimeMaxSec="$MAX" \
      --working-directory="$DIR" "$DIR/run" --host 127.0.0.1 --port "$PORT" >/dev/null
    for _ in $(seq 1 90); do
      if up; then
        echo "started ${UNIT} (stops by itself after ${MAX}): $(curl -s -m 2 "$URL")"
        exit 0
      fi
      sleep 1
    done
    echo "VOICEVOX did not answer on ${PORT} within 90s; see: journalctl --user -u ${UNIT}" >&2
    systemctl --user stop "$UNIT" 2>/dev/null || true
    exit 1
    ;;
  stop)
    if systemctl --user is-active --quiet "$UNIT"; then
      systemctl --user stop "$UNIT"
    fi
    pid="$(port_pid)"
    if [ -n "$pid" ]; then
      # 手で起こした物 (ユニットの外) はポートから引いた PID だけを止める (pkill -f は自分の shell に当たる)
      kill "$pid"
      for _ in $(seq 1 20); do up || break; sleep 0.5; done
    fi
    if up; then
      echo "still answering on ${PORT}" >&2
      exit 1
    fi
    echo "stopped (port ${PORT} free)"
    ;;
  status)
    if up; then
      pid="$(port_pid)"
      rss="$(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.1fGB", $1/1048576}')"
      managed="unmanaged"
      systemctl --user is-active --quiet "$UNIT" && managed="unit ${UNIT}"
      echo "running on ${PORT}: pid ${pid} ${rss} (${managed})"
    else
      echo "not running on ${PORT}"
    fi
    ;;
  *)
    echo "usage: $0 start|stop|status" >&2
    exit 2
    ;;
esac
