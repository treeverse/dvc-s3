dvc-s3
======

s3 plugin for dvc

Configuration
-------------

``dvc-s3`` appends a ``dvc-s3/<version>`` token to the S3 ``User-Agent`` so its
traffic is identifiable on S3 server-side request logs. When the package
metadata is unavailable (source / frozen installs) the token falls back to
``dvc-s3/dev``.

Code constructing the filesystem directly may pass ``user_agent_extra`` to
append one or more additional product tokens (for example,
``downstream/1.2.3``; space-separated tokens are valid ``User-Agent`` syntax).
The value must be a string, ASCII-only, free of control characters, and is
whitespace-trimmed; invalid values raise ``ConfigError``.

Tests
-----

By default tests will be run against moto.
To run against real S3, set ``DVC_TEST_AWS_REPO_BUCKET`` with an AWS bucket name.
