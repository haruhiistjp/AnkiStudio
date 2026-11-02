#!/usr/bin/env python3
"""Synthesize the planned clips with the Gemini Batch API.

The Batch API runs the whole set server-side at 50% of the live price, which
matters at this size: 7,179 clips would otherwise be ~12 hours of polling a
10 requests/minute ceiling.

    python tts_batch.py --limit 8        # pilot
    python tts_batch.py                  # everything still missing

Work is chunked so a failed job only costs one chunk. Raw WAVs are cached,
so re-running resumes where it stopped.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "_work_audio"
RAW = WORK / "raw"
BATCH = WORK / "batch"
KEY = (Path.home() / ".config" / "gcloud" / "gemini.key").read_text().strip()

MODEL = "gemini-3.8-flash-tts"
LANG = "sr-RS"
POLL = 20.0
DONE = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


def request_for(clip: dict) -> dict:
    return {
        "contents": [{"parts": [{"text": clip["text"]}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "languageCode": LANG,
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": clip["voice"]}},
            },
        },
    }


def write_jsonl(clips: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for clip in clips:
            fh.write(
                json.dumps({"key": clip["key"], "request": request_for(clip)}, ensure_ascii=False)
                + "\n"
            )


def field(obj, name):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def run_batch(client: genai.Client, clips: list[dict], tag: str) -> tuple[int, int]:
    BATCH.mkdir(parents=True, exist_ok=True)
    input_path = BATCH / f"{tag}.jsonl"
    result_path = BATCH / f"{tag}.result.jsonl"

    if not input_path.exists():
        write_jsonl(clips, input_path)
        print(f"  wrote {input_path.name} ({len(clips)} requests, {input_path.stat().st_size / 1e6:.1f} MB)")

    if not result_path.exists():
        uploaded = client.files.upload(
            file=str(input_path),
            config=types.UploadFileConfig(display_name=tag, mime_type="jsonl"),
        )
        print(f"  uploaded {uploaded.name}")

        job = client.batches.create(
            model=MODEL, src=uploaded.name, config={"display_name": tag}
        )
        print(f"  job {job.name} created, polling every {POLL:.0f}s")

        started = time.time()
        while True:
            job = client.batches.get(name=job.name)
            state = field(field(job, "state"), "name") or str(field(job, "state"))
            if state in DONE:
                break
            done = field(job, "batch_stats")
            print(f"    {state} after {time.time() - started:.0f}s {done or ''}", flush=True)
            time.sleep(POLL)

        if state != "JOB_STATE_SUCCEEDED":
            err = field(job, "error")
            raise SystemExit(f"batch {tag} ended in {state}: {err}")

        dest = field(field(job, "dest"), "file_name")
        print(f"  succeeded in {(time.time() - started) / 60:.1f} min, downloading {dest}")
        data = client.files.download(file=dest)
        result_path.write_bytes(data)
        print(f"  saved {result_path.name} ({len(data) / 1e6:.1f} MB)")

    ok = failed = 0
    failures = []
    with result_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            key = obj.get("key")
            response = obj.get("response")
            if not response:
                failed += 1
                failures.append((key, obj.get("error") or obj.get("status")))
                continue
            parts = response["candidates"][0]["content"]["parts"]
            audio = next(
                (base64.b64decode(p["inlineData"]["data"]) for p in parts if "inlineData" in p),
                None,
            )
            if not audio or len(audio) < 2000:
                failed += 1
                failures.append((key, "empty audio"))
                continue
            (RAW / f"{key}.wav").write_bytes(audio)
            ok += 1

    print(f"  decoded {ok} clips, {failed} failed")
    for key, why in failures[:5]:
        print(f"    {key}: {json.dumps(why)[:160]}")
    if failures:
        (BATCH / f"{tag}.failures.json").write_text(
            json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return ok, failed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the first N missing clips")
    ap.add_argument("--chunk", type=int, default=2000)
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    clips = json.loads((WORK / "clips.json").read_text(encoding="utf-8"))
    if args.limit:
        clips = clips[: args.limit]

    pending = [c for c in clips if not (RAW / f"{c['key']}.wav").exists()]
    print(f"{len(clips)} planned, {len(clips) - len(pending)} cached, {len(pending)} to synthesize")
    if not pending:
        return

    client = genai.Client(api_key=KEY)
    total_ok = total_fail = 0
    for i in range(0, len(pending), args.chunk):
        part = pending[i : i + args.chunk]
        tag = f"serbian-{i // args.chunk + 1:02d}-{len(part)}"
        print(f"\nchunk {i // args.chunk + 1}: {len(part)} clips -> {tag}")
        ok, failed = run_batch(client, part, tag)
        total_ok += ok
        total_fail += failed

    print(f"\ndone: {total_ok} ok, {total_fail} failed")
    if total_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
