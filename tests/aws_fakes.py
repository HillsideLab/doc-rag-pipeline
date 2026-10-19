"""Small fakes of the boto3 clients used by the pipeline. No network, no AWS configuration."""

import io
from typing import Any

from botocore.exceptions import ClientError


class FakeS3:
    """S3 kept in a dict. Raises the same ClientError codes as real S3 for missing keys."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = dict(objects or {})

    def put_object(self, Bucket: str, Key: str, Body: bytes, **_: Any) -> None:
        self.objects[Key] = Body

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}


class DeniedS3(FakeS3):
    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if Key.startswith("textract-cache/"):
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        return super().get_object(Bucket, Key)


class FakeTextract:
    """Replays a script of GetDocumentAnalysis responses and records every call."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.responses = list(responses or [])
        self.start_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def start_document_analysis(self, **kwargs: Any) -> dict[str, Any]:
        self.start_calls.append(kwargs)
        return {"JobId": "job-1"}

    def get_document_analysis(self, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append(kwargs)
        return self.responses.pop(0)


class FakeTable:
    """Stands in for a boto3 DynamoDB Table resource. Records every update_item call."""

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        return {}


class FakeSecrets:
    """Stands in for the Secrets Manager client. Counts reads so caching can be tested."""

    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0

    def get_secret_value(self, SecretId: str) -> dict[str, Any]:
        self.calls += 1
        return {"SecretString": self.value}
