"""Shared test fixtures."""

import io

import pytest


class FakeS3:
    """In-memory subset of the boto3 S3 client used by the pipeline and the host cron."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []

    def put_object(self, Bucket, Key, Body, **kw):  # noqa: N803 - boto3 signature
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode()
        self.puts.append(Key)

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise RuntimeError("An error occurred (NoSuchKey) when calling the GetObject operation")
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)

    def get_paginator(self, name):
        objects = self.objects

        class P:
            def paginate(self, Bucket, Prefix):  # noqa: N803
                yield {"Contents": [{"Key": k} for k in sorted(objects) if k.startswith(Prefix)]}

        return P()


@pytest.fixture
def fake_s3():
    return FakeS3()
