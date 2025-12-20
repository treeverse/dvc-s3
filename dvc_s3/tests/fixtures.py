import os
import uuid
from urllib.request import Request, urlopen

import pytest
from boto3.session import boto3
from moto.server import ThreadedMotoServer

from .cloud import S3


@pytest.fixture(scope="session")
def s3_server():
    server = ThreadedMotoServer("127.0.0.1", 0, verbose=False)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="session")
def s3_config(s3_server) -> dict:
    host, port = s3_server.get_host_and_port()
    return {
        "endpoint_url": f"http://{host}:{port}",
        "aws_access_key_id": "testing",
        "aws_secret_access_key": "testing",
    }


@pytest.fixture
def s3_client(s3_config):
    return boto3.client("s3", **s3_config)


@pytest.fixture(autouse=True)
def reset_s3_fixture(s3_config):
    req = Request(f"{s3_config['endpoint_url']}/moto-api/reset", method="POST")
    try:
        yield
    finally:
        urlopen(req)


@pytest.fixture
def s3_bucket(s3_client) -> str:
    bucket = "test-bucket"
    s3_client.create_bucket(Bucket=bucket)
    return bucket


@pytest.fixture
def s3_versioned_bucket(s3_client) -> str:
    bucket = "test-bucket-versioned"
    s3_client.create_bucket(Bucket=bucket)
    s3_client.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
    )
    return bucket


@pytest.fixture
def make_s3(request):
    def _make_s3():
        if bucket := os.environ.get("DVC_TEST_AWS_REPO_BUCKET"):
            return S3(f"s3://{bucket}/dvc_test_caches/{uuid.uuid4()}")
        config = request.getfixturevalue("s3_config")
        bucket = request.getfixturevalue("s3_bucket")
        return S3(f"s3://{bucket}", config=config)

    return _make_s3


@pytest.fixture
def make_s3_version_aware(request):
    def _make_s3():
        if bucket := os.environ.get("DVC_TEST_AWS_REPO_BUCKET_VERSIONED"):
            return S3(f"s3://{bucket}/dvc_test_caches/{uuid.uuid4()}")
        config = request.getfixturevalue("s3_config")
        bucket = request.getfixturevalue("s3_versioned_bucket")
        return S3(f"s3://{bucket}", config=config)

    return _make_s3


@pytest.fixture
def s3(make_s3):
    return make_s3()


@pytest.fixture
def cloud(make_cloud):
    return make_cloud(typ="s3")


@pytest.fixture
def remote(make_remote):
    return make_remote(name="upstream", typ="s3")


@pytest.fixture
def remote_version_aware(make_remote_version_aware):
    return make_remote_version_aware(name="upstream", typ="s3")


@pytest.fixture
def remote_worktree(make_remote_worktree):
    return make_remote_worktree(name="upstream", typ="s3")


@pytest.fixture
def workspace(make_workspace):
    return make_workspace(name="workspace", typ="s3")
