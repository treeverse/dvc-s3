import locale
from functools import cached_property

from dvc.testing.cloud import Cloud
from dvc.testing.path_info import CloudURLInfo


class S3(Cloud, CloudURLInfo):
    def __init__(self, url: str, config=None):
        super().__init__(url)
        self._config = config or {}

    def __truediv__(self, key):
        ret = super().__truediv__(key)
        ret._config = self._config
        ret._s3 = self._s3
        return ret

    @property
    def config(self):
        ret = {"url": str(self)}
        config_map = {
            "access_key_id": "aws_access_key_id",
            "secret_access_key": "aws_secret_access_key",
            "endpointurl": "endpoint_url",
        }
        for key, config_key in config_map.items():
            value = self._config.get(config_key)
            if value is not None:
                ret[key] = value
        return ret

    @cached_property
    def _s3(self):
        import boto3

        return boto3.client("s3", **self._config)

    def is_file(self):
        from botocore.exceptions import ClientError

        if self.path.endswith("/"):
            return False

        try:
            self._s3.head_object(Bucket=self.bucket, Key=self.path)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise
            return False

        return True

    def is_dir(self):
        path = (self / "").path
        resp = self._s3.list_objects(Bucket=self.bucket, Prefix=path)
        return bool(resp.get("Contents"))

    def exists(self):
        return self.is_file() or self.is_dir()

    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        assert mode == 0o777
        assert parents

    def write_bytes(self, contents):
        self._s3.put_object(Bucket=self.bucket, Key=self.path, Body=contents)

    def unlink(self, missing_ok: bool = False) -> None:
        if not self.exists():
            if not missing_ok:
                raise FileNotFoundError(str(self))
            return
        self._s3.delete_object(Bucket=self.bucket, Key=self.path)

    def rmdir(self, recursive: bool = True) -> None:
        if not self.is_dir():
            raise NotADirectoryError(str(self))

        path = (self / "").path
        resp = self._s3.list_objects(Bucket=self.bucket, Prefix=path)
        entries = resp.get("Contents")
        if not entries:
            return

        if not recursive:
            raise OSError(f"Not recursive and directory not empty: {self}")

        self._s3.delete_objects(
            Bucket=self.bucket, Delete={"Objects": [{"Key": e["Key"]} for e in entries]}
        )

    def read_bytes(self):
        data = self._s3.get_object(Bucket=self.bucket, Key=self.path)
        return data["Body"].read()

    def read_text(self, encoding=None, errors=None):
        if not encoding:
            encoding = locale.getpreferredencoding(False)
        assert errors is None
        return self.read_bytes().decode(encoding)

    @property
    def fs_path(self):
        return self.bucket + "/" + self.path.lstrip("/")
