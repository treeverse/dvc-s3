import os

import pytest

from dvc.fs import ConfigError
from dvc_s3 import S3FileSystem

bucket_name = "bucket-name"
prefix = "some/prefix"
url = f"s3://{bucket_name}/{prefix}"
key_id = "key-id"
key_secret = "key-secret"
session_token = "session-token"


@pytest.fixture(autouse=True, name="grants")
def fixture_grants():
    return {
        "grant_read": "id=read-permission-id,id=other-read-permission-id",
        "grant_read_acp": "id=read-acp-permission-id",
        "grant_write_acp": "id=write-acp-permission-id",
        "grant_full_control": "id=full-control-permission-id",
    }


def test_verify_ssl_default_param():
    config = {"url": url}
    fs = S3FileSystem(**config)

    assert "client_kwargs" not in fs.fs_args

    config = {
        "url": url,
        "endpointurl": "https://my.custom.s3:1234",
    }
    fs = S3FileSystem(**config)

    assert "verify" not in fs.fs_args["client_kwargs"]


def test_s3_config_credentialpath(monkeypatch):
    environment = {}
    monkeypatch.setattr(os, "environ", environment)

    config = {"url": url, "credentialpath": "somewhere"}
    S3FileSystem(**config).fs_args  # noqa: B018
    assert environment["AWS_SHARED_CREDENTIALS_FILE"] == "somewhere"
    environment.clear()

    config = {"url": url, "configpath": "somewhere"}
    S3FileSystem(**config).fs_args  # noqa: B018
    assert environment["AWS_CONFIG_FILE"] == "somewhere"
    environment.clear()

    config = {
        "url": url,
        "credentialpath": "somewhere",
        "configpath": "elsewhere",
    }
    S3FileSystem(**config).fs_args  # noqa: B018
    assert environment["AWS_SHARED_CREDENTIALS_FILE"] == "somewhere"
    assert environment["AWS_CONFIG_FILE"] == "elsewhere"
    environment.clear()


def test_ssl_verify_bool_param():
    config = {"url": url, "ssl_verify": False}
    fs = S3FileSystem(**config)

    assert fs.fs_args["client_kwargs"]["verify"] == config["ssl_verify"]


def test_ssl_verify_path_param():
    config = {"url": url, "ssl_verify": "/path/to/custom/cabundle.pem"}
    fs = S3FileSystem(**config)

    assert fs.fs_args["client_kwargs"]["verify"] == config["ssl_verify"]


def test_ssl_verify_none_param():
    config = {"url": url, "ssl_verify": None}
    fs = S3FileSystem(**config)

    assert "client_kwargs" not in fs.fs_args

    config = {
        "url": url,
        "endpointurl": "https://my.custom.s3:1234",
        "ssl_verify": None,
    }
    fs = S3FileSystem(**config)

    assert "verify" not in fs.fs_args["client_kwargs"]


def test_grants():
    config = {
        "url": url,
        "grant_read": "id=read-permission-id,id=other-read-permission-id",
        "grant_read_acp": "id=read-acp-permission-id",
        "grant_write_acp": "id=write-acp-permission-id",
        "grant_full_control": "id=full-control-permission-id",
    }
    fs = S3FileSystem(**config)

    extra_args = fs.fs_args["s3_additional_kwargs"]
    assert (
        extra_args["GrantRead"] == "id=read-permission-id,id=other-read-permission-id"
    )
    assert extra_args["GrantReadACP"] == "id=read-acp-permission-id"
    assert extra_args["GrantWriteACP"] == "id=write-acp-permission-id"
    assert extra_args["GrantFullControl"] == "id=full-control-permission-id"


def test_grants_mutually_exclusive_acl_error(grants):
    for grant_option, grant_value in grants.items():
        config = {"url": url, "acl": "public-read", grant_option: grant_value}

        fs = S3FileSystem(**config)
        with pytest.raises(ConfigError):
            fs.fs_args  # noqa: B018


def test_sse_kms_key_id():
    fs = S3FileSystem(url=url, sse_kms_key_id="key")
    assert fs.fs_args["s3_additional_kwargs"]["SSEKMSKeyId"] == "key"


def test_key_id_and_secret():
    fs = S3FileSystem(
        url=url,
        access_key_id=key_id,
        secret_access_key=key_secret,
        session_token=session_token,
    )
    assert fs.fs_args["key"] == key_id
    assert fs.fs_args["secret"] == key_secret
    assert fs.fs_args["token"] == session_token


def test_default_user_agent_extra():
    fs = S3FileSystem(url=url)
    ua = fs.fs_args["config_kwargs"]["user_agent_extra"]
    # "dvc-s3/<version>" in normal installs; "dvc-s3/dev" when package
    # metadata is missing (source-only / frozen-binary cases).
    assert ua.startswith("dvc-s3/")
    assert " " not in ua  # no extra token appended by default


def test_user_agent_extra_appends_user_value():
    fs = S3FileSystem(url=url, user_agent_extra="downstream/1.2.3")
    ua = fs.fs_args["config_kwargs"]["user_agent_extra"]
    assert ua.startswith("dvc-s3/")
    assert ua.endswith(" downstream/1.2.3")


def test_user_agent_extra_strips_whitespace():
    fs = S3FileSystem(url=url, user_agent_extra="  downstream/1.2.3  ")
    ua = fs.fs_args["config_kwargs"]["user_agent_extra"]
    assert ua.endswith(" downstream/1.2.3")
    assert "  " not in ua


def test_user_agent_extra_rejects_control_chars():
    with pytest.raises(ConfigError):
        _ = S3FileSystem(
            url=url, user_agent_extra="downstream/1.2.3\r\nX-Evil: 1"
        ).fs_args


def test_user_agent_extra_rejects_non_string():
    with pytest.raises(ConfigError):
        _ = S3FileSystem(url=url, user_agent_extra=123).fs_args


def test_user_agent_extra_rejects_non_ascii():
    with pytest.raises(ConfigError):
        _ = S3FileSystem(url=url, user_agent_extra="downstream/1.2.3 🚀").fs_args


def test_user_agent_extra_on_the_wire(s3_config, s3_bucket):
    fs = S3FileSystem(
        url=f"s3://{s3_bucket}",
        endpointurl=s3_config["endpoint_url"],
        access_key_id=s3_config["aws_access_key_id"],
        secret_access_key=s3_config["aws_secret_access_key"],
        user_agent_extra="downstream/1.2.3",
    )
    fs.fs.ls(s3_bucket)  # warm up so the client/session is created

    captured = []

    def _capture(request, **_):
        captured.append(request.headers.get("User-Agent"))

    events = fs.fs.s3.meta.events
    events.register_first("before-send.s3", _capture)
    try:
        fs.fs.ls(s3_bucket, refresh=True)  # force a real request (bypass dircache)
    finally:
        events.unregister("before-send.s3", _capture)

    assert captured, "no request reached the wire"
    ua = captured[0]
    ua = ua.decode() if isinstance(ua, bytes) else ua
    assert ua, "request had no User-Agent header"
    assert "dvc-s3/" in ua
    assert "downstream/1.2.3" in ua


def test_user_agent_extra_dev_fallback(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    import dvc_s3

    def _raise(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(dvc_s3, "version", _raise)
    dvc_s3._user_agent_extra.cache_clear()
    try:
        assert dvc_s3._user_agent_extra() == "dvc-s3/dev"
    finally:
        dvc_s3._user_agent_extra.cache_clear()
