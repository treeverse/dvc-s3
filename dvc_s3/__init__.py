import os
import threading
from collections import defaultdict
from typing import Any, ClassVar, Optional
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from funcy import first, wrap_prop

from dvc.utils.objects import cached_property
from dvc_objects.fs.base import ObjectFileSystem
from dvc_objects.fs.errors import ConfigError

_AWS_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".aws", "config")


# https://github.com/aws/aws-cli/blob/5aa599949f60b6af554fd5714d7161aa272716f7/awscli/customizations/s3/utils.py
MULTIPLIERS = {
    "kb": 1024,
    "mb": 1024**2,
    "gb": 1024**3,
    "tb": 1024**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}


def human_readable_to_bytes(value: str) -> int:
    value = value.lower()
    suffix = ""
    if value.endswith(tuple(MULTIPLIERS.keys())):
        size = 2
        size += value[-2] == "i"  # KiB, MiB etc
        value, suffix = value[:-size], value[-size:]

    multiplier = MULTIPLIERS.get(suffix, 1)
    return int(value) * multiplier


# pylint:disable=abstract-method
class S3FileSystem(ObjectFileSystem):
    protocol = "s3"
    REQUIRES: ClassVar[dict[str, str]] = {"s3fs": "s3fs"}
    PARAM_CHECKSUM = "etag"

    VERSION_ID_KEY = "versionId"

    _GRANTS: ClassVar[dict[str, str]] = {
        "grant_full_control": "GrantFullControl",
        "grant_read": "GrantRead",
        "grant_read_acp": "GrantReadACP",
        "grant_write_acp": "GrantWriteACP",
    }

    _TRANSFER_CONFIG_ALIASES: ClassVar[dict[str, str]] = {
        "max_queue_size": "max_io_queue",
        "max_concurrent_requests": "max_concurrency",
        "multipart_threshold": "multipart_threshold",
        "multipart_chunksize": "multipart_chunksize",
    }

    @classmethod
    def split_version(cls, path: str) -> tuple[str, Optional[str]]:
        parts = list(urlsplit(path))
        query = parse_qs(parts[3])
        if cls.VERSION_ID_KEY in query:
            version_id = first(query[cls.VERSION_ID_KEY])
            del query[cls.VERSION_ID_KEY]
            parts[3] = urlencode(query)
        else:
            version_id = None
        return urlunsplit(parts), version_id

    @classmethod
    def join_version(cls, path: str, version_id: Optional[str]) -> str:
        parts = list(urlsplit(path))
        query = parse_qs(parts[3])
        if cls.VERSION_ID_KEY in query:
            raise ValueError("path already includes a version query")
        parts[3] = f"{cls.VERSION_ID_KEY}={version_id}" if version_id else ""
        return urlunsplit(parts)

    @classmethod
    def version_path(cls, path: str, version_id: Optional[str]) -> str:
        path, _ = cls.split_version(path)
        return cls.join_version(path, version_id)

    @classmethod
    def coalesce_version(
        cls, path: str, version_id: Optional[str]
    ) -> tuple[str, Optional[str]]:
        path, path_version_id = cls.split_version(path)
        versions = {ver for ver in (version_id, path_version_id) if ver}
        if len(versions) > 1:
            raise ValueError("Path version mismatch: '{path}', '{version_id}'")
        return path, (versions.pop() if versions else None)

    @classmethod
    def _get_kwargs_from_urls(cls, urlpath: str) -> dict[str, Any]:
        ret = super()._get_kwargs_from_urls(urlpath)
        url_query = ret.get("url_query")
        if url_query is not None:
            parsed = parse_qs(url_query)
            if "versionId" in parsed:
                ret["version_aware"] = True
        return ret

    def _split_s3_config(self, s3_config):
        """Splits the general s3 config into 2 different config
        objects, one for transfer.TransferConfig and other is the
        general session config"""

        config, transfer_config = {}, {}
        for key, value in s3_config.items():
            if key in self._TRANSFER_CONFIG_ALIASES:
                if key in {"multipart_chunksize", "multipart_threshold"}:
                    # cast human readable sizes (like 24MiB) to integers
                    value = human_readable_to_bytes(value)
                else:
                    value = int(value)
                transfer_config[self._TRANSFER_CONFIG_ALIASES[key]] = value
            else:
                config[key] = value

        self._transfer_config = transfer_config
        return config

    def _load_aws_config_file(self, profile):
        from botocore.configloader import load_config

        self._transfer_config = None
        config_path = os.environ.get("AWS_CONFIG_FILE", _AWS_CONFIG_PATH)
        if not os.path.exists(config_path):
            return {}

        config = load_config(config_path)
        profile_config = config["profiles"].get(profile or "default")
        if not profile_config:
            return {}

        s3_config = profile_config.get("s3", {})
        return self._split_s3_config(s3_config)

    def _prepare_credentials(self, **config):
        import base64

        from flatten_dict import flatten, unflatten
        from s3fs.utils import SSEParams

        login_info = defaultdict(dict)

        login_info["version_aware"] = config.get("version_aware", False)

        # credentials
        login_info["key"] = config.get("access_key_id")
        login_info["secret"] = config.get("secret_access_key")
        login_info["token"] = config.get("session_token")

        # session configuration
        login_info["profile"] = config.get("profile")
        login_info["use_ssl"] = config.get("use_ssl", True)
        login_info["anon"] = config.get("allow_anonymous_login")

        # extra client configuration
        client = login_info["client_kwargs"]
        client["region_name"] = config.get("region")
        client["endpoint_url"] = config.get("endpointurl")
        client["verify"] = config.get("ssl_verify")

        # timeout configuration
        config_kwargs = login_info["config_kwargs"]
        config_kwargs["read_timeout"] = config.get("read_timeout")
        config_kwargs["connect_timeout"] = config.get("connect_timeout")

        # encryptions
        additional = login_info["s3_additional_kwargs"]
        sse_customer_key = None
        if config.get("sse_customer_key"):
            if config.get("sse_kms_key_id"):
                raise ConfigError(
                    "`sse_kms_key_id` and `sse_customer_key` AWS S3 config "
                    "options are mutually exclusive"
                )
            sse_customer_key = base64.b64decode(config.get("sse_customer_key"))
        sse_customer_algorithm = config.get("sse_customer_algorithm")
        if not sse_customer_algorithm and sse_customer_key:
            sse_customer_algorithm = "AES256"
        sse_params = SSEParams(
            server_side_encryption=config.get("sse"),
            sse_customer_algorithm=sse_customer_algorithm,
            sse_customer_key=sse_customer_key,
            sse_kms_key_id=config.get("sse_kms_key_id"),
        )
        additional.update(sse_params.to_kwargs())
        additional["ACL"] = config.get("acl")
        for grant_option, grant_key in self._GRANTS.items():
            if config.get(grant_option):
                if additional["ACL"]:
                    raise ConfigError(
                        "`acl` and `grant_*` AWS S3 config options "
                        "are mutually exclusive"
                    )
                additional[grant_key] = config[grant_option]

        # config kwargs
        session_config = login_info["config_kwargs"]
        session_config["s3"] = self._load_aws_config_file(login_info["profile"])

        shared_creds = config.get("credentialpath")
        if shared_creds:
            os.environ.setdefault("AWS_SHARED_CREDENTIALS_FILE", shared_creds)

        if (
            client["region_name"] is None
            and session_config["s3"].get("region_name") is None
            and os.getenv("AWS_REGION") is None
        ):
            # Enable bucket region caching
            login_info["cache_regions"] = config.get("cache_regions", True)

        config_path = config.get("configpath")
        if config_path:
            os.environ.setdefault("AWS_CONFIG_FILE", config_path)

        d = flatten(login_info, reducer="dot")
        return unflatten(
            {key: value for key, value in d.items() if value is not None},
            splitter="dot",
        )

    @wrap_prop(threading.Lock())
    @cached_property
    def fs(self):
        from s3fs import S3FileSystem as _S3FileSystem

        s3_filesystem = _S3FileSystem(**self.fs_args)
        s3_filesystem.connect()

        return s3_filesystem

    @classmethod
    def _strip_protocol(cls, path: str) -> str:
        from fsspec.utils import infer_storage_options

        return infer_storage_options(path)["path"]

    def unstrip_protocol(self, path):
        return "s3://" + path.lstrip("/")
