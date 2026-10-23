"""Apply scripts/s3-cors.json to the S3 bucket (same as `aws s3api put-bucket-cors`, no AWS CLI needed).

    python scripts/set_s3_cors.py

Uses S3_BUCKET, AWS_REGION and the AWS keys from .env. The browser uploads to and plays from the
bucket directly, so it needs this rule; edit AllowedOrigins in the JSON for other sites.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from media_service import storage  # noqa: E402
from media_service.config import S3_BUCKET  # noqa: E402


def main() -> int:
    if not S3_BUCKET:
        print("S3_BUCKET is missing from .env.", file=sys.stderr)
        return 2
    rules = json.loads((ROOT / "scripts" / "s3-cors.json").read_text(encoding="utf-8"))
    s3 = storage.s3()
    try:
        s3.put_bucket_cors(Bucket=S3_BUCKET, CORSConfiguration=rules)
    except Exception as e:
        print(f"Couldn't set CORS on {S3_BUCKET}: {type(e).__name__}: {e}", file=sys.stderr)
        if "AccessDenied" in str(e):
            print("This IAM user lacks s3:PutBucketCORS. Paste the CORSRules array in the S3 console instead: "
                  "bucket -> Permissions -> Cross-origin resource sharing (CORS) -> Edit.", file=sys.stderr)
        return 1
    applied = s3.get_bucket_cors(Bucket=S3_BUCKET)["CORSRules"]
    print(f"CORS set on {S3_BUCKET}:")
    for r in applied:
        print(f"  origins {r['AllowedOrigins']}  methods {r['AllowedMethods']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
