"""Copy completed, explicitly named Voice Designer jobs into isolated training data.

GET requests only; this neither submits jobs nor changes the live assistant.
Output is immutable and must be kept outside Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen


JOB_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}$")
SAMPLE_NAME = re.compile(r"^sample-[0-9]{2}\.wav$")


def get(url: str, host: str) -> bytes:
    request = Request(url, headers={"Host": host})
    with urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--host", default="server")
    parser.add_argument("--positive-job", action="append", default=[])
    parser.add_argument("--negative-job", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    ids = args.positive_job + args.negative_job
    if not args.positive_job or not args.negative_job or len(ids) != len(set(ids)):
        parser.error("provide distinct positive and negative job IDs")
    if any(not JOB_ID.fullmatch(job_id) for job_id in ids):
        parser.error("invalid job ID")
    if args.output_dir.exists():
        parser.error("output directory already exists; never overwrite training data")
    base_url = args.base_url.rstrip("/")
    jobs = json.loads(get(f"{base_url}/api/jobs", args.host))["jobs"]
    by_id = {job["id"]: job for job in jobs}
    for job_id in ids:
        job = by_id.get(job_id)
        if job is None or job.get("state") != "completed" or not job.get("samples"):
            parser.error(f"job is missing, incomplete or empty: {job_id}")
        text = job.get("request", {}).get("text", "").strip().casefold()
        if job_id in args.positive_job and text != "nova":
            parser.error(f"positive job does not say Nova: {job_id}")
        if job_id in args.negative_job and text not in {"nora", "noah"}:
            parser.error(f"negative job has unexpected text: {job_id}")
        if any(not SAMPLE_NAME.fullmatch(sample.get("filename", "")) for sample in job["samples"]):
            parser.error(f"job has unexpected sample filenames: {job_id}")

    args.output_dir.mkdir(parents=True, mode=0o700)
    records = []
    for label, job_ids in (("positive", args.positive_job), ("negative", args.negative_job)):
        target_dir = args.output_dir / label
        target_dir.mkdir(mode=0o700)
        for job_id in job_ids:
            job = by_id[job_id]
            for sample in job["samples"]:
                filename = sample["filename"]
                data = get(f"{base_url}/api/jobs/{job_id}/files/{filename}", args.host)
                if not data.startswith(b"RIFF") or b"WAVE" not in data[:16]:
                    raise ValueError(f"not a WAV: {job_id}/{filename}")
                target = target_dir / f"{job_id}_{filename}"
                target.write_bytes(data)
                records.append({
                    "file": str(target.relative_to(args.output_dir)),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "job_id": job_id,
                    "description": job["request"]["description"],
                    "text": job["request"]["text"],
                    "seed": sample.get("seed"),
                })
    (args.output_dir / "provenance.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for label in ("positive", "negative"):
        print(f"{label}_count={sum(item['file'].startswith(label + '/') for item in records)}")
    print(f"distinct_sha256={len({item['sha256'] for item in records})}")


if __name__ == "__main__":
    main()
