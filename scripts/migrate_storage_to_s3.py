"""Copy every object from the Supabase `media` bucket to the S3 bucket, keeping the same keys.

Database rows store keys (e.g. {owner}/{asset}/source.mp4), not URLs, so once the objects
exist in S3 under the same keys, existing videos, thumbnails, voice audio and exports keep
working after switching STORAGE_BACKEND to s3. Objects already in S3 with the same size are
skipped, so the script is safe to re-run.

    python scripts/migrate_storage_to_s3.py            # dry run: list what would be copied
    python scripts/migrate_storage_to_s3.py --copy     # copy

Needs SUPABASE_URL, SUPABASE_SECRET_KEY, S3_BUCKET, AWS_REGION and AWS keys in .env.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media_service import storage  # noqa: E402
from media_service.config import AWS_REGION, MEDIA_BUCKET, S3_BUCKET  # noqa: E402

PAGE = 1000


def walk(prefix: str = ""):
    """Every object key in the Supabase bucket (folders have no id/metadata)."""
    bucket = storage.admin().storage.from_(MEDIA_BUCKET)
    offset = 0
    while True:
        entries = bucket.list(prefix, {"limit": PAGE, "offset": offset}) or []
        for e in entries:
            name = e.get("name") if isinstance(e, dict) else getattr(e, "name", None)
            if not name:
                continue
            key = f"{prefix}/{name}" if prefix else name
            meta = e.get("metadata") if isinstance(e, dict) else getattr(e, "metadata", None)
            if meta:                                    # a file
                yield key, int(meta.get("size") or 0), meta.get("mimetype") or "application/octet-stream"
            else:                                       # a folder
                yield from walk(key)
        if len(entries) < PAGE:
            return
        offset += PAGE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--copy", action="store_true", help="actually copy (default is a dry run)")
    args = ap.parse_args()
    if not (S3_BUCKET and AWS_REGION):
        print("Set S3_BUCKET and AWS_REGION in .env first.", file=sys.stderr)
        return 2
    s3 = storage.s3()
    s3.head_bucket(Bucket=S3_BUCKET)

    todo, skipped, total_bytes, failed = [], 0, 0, []
    for key, size, ctype in walk():
        try:
            head = s3.head_object(Bucket=S3_BUCKET, Key=key)
            if int(head["ContentLength"]) == size:
                skipped += 1
                continue
        except Exception as e:
            if not storage._not_found(e):
                raise
        todo.append((key, size, ctype))
        total_bytes += size

    print(f"{len(todo)} object(s) to copy ({total_bytes / 1e6:.1f} MB), {skipped} already in s3://{S3_BUCKET}.")
    if not args.copy:
        for key, size, _ in todo[:20]:
            print(f"  would copy {key} ({size / 1e6:.2f} MB)")
        if len(todo) > 20:
            print(f"  … and {len(todo) - 20} more")
        print("Dry run. Re-run with --copy to copy.")
        return 0

    sb = storage.admin().storage.from_(MEDIA_BUCKET)
    for i, (key, size, ctype) in enumerate(todo, 1):
        try:
            s3.put_object(Bucket=S3_BUCKET, Key=key, Body=sb.download(key), ContentType=ctype)
            print(f"[{i}/{len(todo)}] {key}")
        except Exception as e:
            failed.append(key)
            print(f"[{i}/{len(todo)}] FAILED {key}: {type(e).__name__}: {e}", file=sys.stderr)
    print(f"Copied {len(todo) - len(failed)}, failed {len(failed)}.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
