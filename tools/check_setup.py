"""Check that the CI secrets work, without printing their values (SPEC Â§9, Â§16).

    python -m tools.check_setup secrets   # which secrets are set (names only) and whether their format looks right
    python -m tools.check_setup r2        # put / get / delete a probe object in the bucket
    python -m tools.check_setup gee       # initialise Earth Engine with the service account and run a tiny computation

Exit code 0 = OK. Messages describe the problem in general terms only.
"""

import json
import os
import re
import sys
import uuid

REQUIRED = ["GEE_SERVICE_ACCOUNT_JSON", "R2_ENDPOINT", "R2_KEY", "R2_SECRET", "R2_BUCKET"]
ENDPOINT_RE = re.compile(r"^https://[0-9a-f]{32}\.(eu\.|fedramp\.)?r2\.cloudflarestorage\.com/?$")
BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def check_secrets() -> None:
    missing = [n for n in REQUIRED if not os.environ.get(n, "").strip()]
    for n in REQUIRED:
        print(f"{n}: {'set' if n not in missing else 'MISSING'}")
    problems = []
    endpoint = os.environ.get("R2_ENDPOINT", "").strip()
    if endpoint and not ENDPOINT_RE.match(endpoint):
        problems.append(
            "R2_ENDPOINT should look like https://<32-hex account id>.r2.cloudflarestorage.com "
            "(no bucket name or path at the end)"
        )
    bucket = os.environ.get("R2_BUCKET", "").strip()
    if bucket and not BUCKET_RE.match(bucket):
        problems.append("R2_BUCKET should be just the bucket name, e.g. lepszapogoda-data (not a URL)")
    key = os.environ.get("R2_KEY", "").strip()
    if key and not re.fullmatch(r"[0-9a-f]{32}", key):
        problems.append("R2_KEY should be the 32-hex 'Access Key ID' of an R2 API token (not the token value)")
    secret = os.environ.get("R2_SECRET", "").strip()
    if secret and not re.fullmatch(r"[0-9a-f]{64}", secret):
        problems.append("R2_SECRET should be the 64-hex 'Secret Access Key' of the same R2 API token")
    sa = os.environ.get("GEE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa:
        try:
            info = json.loads(sa)
            if info.get("type") != "service_account" or "private_key" not in info:
                problems.append("GEE_SERVICE_ACCOUNT_JSON is JSON but not a service account key file")
        except ValueError:
            problems.append("GEE_SERVICE_ACCOUNT_JSON is not valid JSON (paste the whole key file)")
    for p in problems:
        print(f"PROBLEM: {p}")
    if missing or problems:
        fail(f"{len(missing)} missing, {len(problems)} format problems")
    print("OK")


def check_r2() -> None:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"].strip(),
        aws_access_key_id=os.environ["R2_KEY"].strip(),
        aws_secret_access_key=os.environ["R2_SECRET"].strip(),
        region_name="auto",
    )
    bucket = os.environ["R2_BUCKET"].strip()
    key = f"_setup_check/{uuid.uuid4().hex}.txt"
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=b"lepszapogoda setup check")
        print("put: OK")
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        print("get: OK" if body == b"lepszapogoda setup check" else "get: content mismatch")
        s3.delete_object(Bucket=bucket, Key=key)
        print("delete: OK")
        n = s3.list_objects_v2(Bucket=bucket, MaxKeys=5).get("KeyCount", 0)
        print(f"list: OK ({n} objects visible)")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "?")
        hints = {
            "NoSuchBucket": "bucket name does not exist in this account",
            "AccessDenied": "token lacks Object Read & Write on this bucket",
            "InvalidAccessKeyId": "R2_KEY not recognised (wrong value or token deleted)",
            "SignatureDoesNotMatch": "R2_SECRET does not match R2_KEY",
        }
        fail(f"R2 error {code}: {hints.get(code, 'see Cloudflare R2 docs')}")
    except BotoCoreError as e:
        fail(f"R2 connection problem ({type(e).__name__}) - check R2_ENDPOINT")
    print("OK")


def check_r2_readonly() -> None:
    """Host token (R2_KEY_RO/R2_SECRET_RO): list and get must work, put must be refused."""
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    for name in ("R2_ENDPOINT", "R2_BUCKET", "R2_KEY_RO", "R2_SECRET_RO"):
        print(f"{name}: {'set' if os.environ.get(name, '').strip() else 'MISSING'}")
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ["R2_ENDPOINT"].strip(),
            aws_access_key_id=os.environ["R2_KEY_RO"].strip(),
            aws_secret_access_key=os.environ["R2_SECRET_RO"].strip(),
            region_name="auto",
        )
        bucket = os.environ["R2_BUCKET"].strip()
        listing = s3.list_objects_v2(Bucket=bucket, Prefix="pipeline/obs/imgw_raw/", MaxKeys=1)
        print(f"list: OK ({listing.get('KeyCount', 0)} object(s) under pipeline/obs/imgw_raw/)")
        if listing.get("Contents"):
            s3.get_object(Bucket=bucket, Key=listing["Contents"][0]["Key"])["Body"].read(100)
            print("get: OK")
    except KeyError as e:
        fail(f"missing environment variable {e} (is ~/.bash_profile sourced?)")
    except ClientError as e:
        fail(f"R2 error {e.response.get('Error', {}).get('Code', '?')} on read")
    except BotoCoreError as e:
        fail(f"R2 connection problem ({type(e).__name__}) - check R2_ENDPOINT")
    try:
        s3.put_object(Bucket=bucket, Key=f"_setup_check/ro-{uuid.uuid4().hex}.txt", Body=b"must fail")
    except ClientError as e:
        print(f"put: refused as expected ({e.response.get('Error', {}).get('Code', '?')})")
        print("OK")
        return
    fail("put SUCCEEDED - this token can write; create a token with Object Read only")


def check_gee() -> None:
    import ee

    from pipeline.gee.auth import init_ee

    try:
        init_ee()
        n = ee.ImageCollection("NASA/GPM_L3/IMERG_V07").filterDate("2026-09-01", "2026-09-02").size().getInfo()
    except Exception as e:  # noqa: BLE001 - report any auth/permission problem without the traceback
        msg = str(e).split("\n")[0][:300]
        fail(f"Earth Engine: {type(e).__name__}: {msg}")
    print(f"IMERG images on 2026-09-01: {n}")
    print("OK")


if __name__ == "__main__":
    {"secrets": check_secrets, "r2": check_r2, "r2-ro": check_r2_readonly, "gee": check_gee}[sys.argv[1]]()
