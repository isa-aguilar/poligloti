"""Minimal CLI to exercise the conversation loop without the frontend.

    python -m backend.cli --lang de
    python -m backend.cli --user sam --lang en --api http://127.0.0.1:8100

Inside the session:
    <text>             send a text turn
    :audio <path>      send an audio turn (WAV)
    :quit  or  Ctrl-D  close the session (triggers the post-session pass)
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

from . import config

C_USER = "\033[36m"
C_TEACHER = "\033[32m"
C_CORR = "\033[33m"
C_VOCAB = "\033[35m"
C_DIM = "\033[2m"
C_OFF = "\033[0m"


def _play(audio_bytes: bytes) -> None:
    if not audio_bytes:
        return
    suffix = ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(audio_bytes)
        path = fh.name
    system = platform.system()
    players = {
        "Darwin": ["afplay", path],
        "Linux": ["aplay", "-q", path],
    }
    cmd = players.get(system)
    if not cmd:
        return
    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print(f"{C_DIM}(could not play audio: {cmd[0]} not found){C_OFF}")
    finally:
        Path(path).unlink(missing_ok=True)


def _render_turn(data: dict, client: httpx.Client, api: str) -> None:
    print(f"\n{C_TEACHER}Teacher:{C_OFF} {data['reply']}")

    if data.get("corrections"):
        print(f"{C_CORR}  Corrections:{C_OFF}")
        for c in data["corrections"]:
            line = (
                f"    {c['original']} -> {c['corrected']}"
                if c["original"]
                else f"    {c['corrected']}"
            )
            if c.get("note"):
                line += f"  ({c['note']})"
            print(f"{C_CORR}{line}{C_OFF}")

    if data.get("new_vocab"):
        print(f"{C_VOCAB}  Vocab:{C_OFF}")
        for v in data["new_vocab"]:
            line = f"    {v['term']}"
            if v.get("translation"):
                line += f" = {v['translation']}"
            if v.get("example"):
                line += f"  ({v['example']})"
            print(f"{C_VOCAB}{line}{C_OFF}")

    if data.get("suggested_followup"):
        print(f"{C_DIM}  > {data['suggested_followup']}{C_OFF}")

    if data.get("audio_url"):
        try:
            resp = client.get(api + data["audio_url"], timeout=30)
            if resp.status_code == 200:
                _play(resp.content)
        except httpx.HTTPError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="poligloti teacher CLI")
    ap.add_argument("--user", default="alex", help="user_id (default: alex)")
    ap.add_argument(
        "--lang", required=True, help="target language (" + ", ".join(config.SUPPORTED_LANGS) + ")"
    )
    ap.add_argument("--mode", type=int, default=1, help="teaching mode (1-9)")
    ap.add_argument("--api", default=f"http://127.0.0.1:{config.PORT}", help="backend base URL")
    ap.add_argument("--audio", help="WAV file to send as the first turn")
    args = ap.parse_args()
    api = args.api.rstrip("/")

    client = httpx.Client(timeout=180)

    try:
        resp = client.post(
            f"{api}/session/start",
            json={"user_id": args.user, "target_language": args.lang, "mode": args.mode},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Could not start the session: {exc}", file=sys.stderr)
        return 1

    session_id = resp.json()["session_id"]
    print(f"{C_DIM}Session {session_id} started ({args.user} / {args.lang}, mode {args.mode}).")
    print(f"Type to talk. ':audio <path>' for audio. ':quit' or Ctrl-D to close.{C_OFF}")

    def send_text(text: str) -> None:
        r = client.post(f"{api}/turn", data={"session_id": session_id, "text": text})
        r.raise_for_status()
        _render_turn(r.json(), client, api)

    def send_audio(path: str) -> None:
        p = Path(path).expanduser()
        if not p.is_file():
            print(f"{C_DIM}File not found: {p}{C_OFF}")
            return
        with p.open("rb") as fh:
            r = client.post(
                f"{api}/turn",
                data={"session_id": session_id},
                files={"audio": (p.name, fh, "audio/wav")},
            )
        r.raise_for_status()
        _render_turn(r.json(), client, api)

    try:
        if args.audio:
            send_audio(args.audio)
        while True:
            try:
                line = input(f"\n{C_USER}You:{C_OFF} ").strip()
            except EOFError:
                break
            if not line:
                continue
            if line in (":quit", ":q", ":exit"):
                break
            if line.startswith(":audio "):
                send_audio(line[len(":audio ") :].strip())
                continue
            try:
                send_text(line)
            except httpx.HTTPError as exc:
                print(f"{C_DIM}Turn failed: {exc}{C_OFF}")
    finally:
        try:
            end = client.post(f"{api}/session/end", json={"session_id": session_id})
            if end.status_code == 200:
                info = end.json()
                print(
                    f"\n{C_DIM}Session closed. Turns: {info.get('turns')}. "
                    f"progress.md updated: {info.get('progress_updated')}. "
                    f"new vocab: {info.get('vocab_added')}.{C_OFF}"
                )
        except httpx.HTTPError:
            pass
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
