dvc-s3
======

s3 plugin for dvc

Write options
-------------

These remote options control how objects are written to S3. Each one is
optional; when an option is not set, nothing is sent and the bucket or
provider default applies.

``storage_class``
    Storage class for uploaded objects (boto3 ``StorageClass``), for example
    ``STANDARD_IA``, ``GLACIER_IR`` or a provider-specific class such as
    ``COLD``. Default: not set.

``requester_pays``
    Set to ``true`` to send ``RequestPayer=requester``, which is required for
    requester-pays buckets. Accepts ``true``/``false``, ``1``/``0``,
    ``yes``/``no``, ``on``/``off``. Default: ``false``.

``object_tags``
    Tags applied to uploaded objects, as a URL-encoded query string
    (boto3 ``Tagging``), for example ``env=prod&team=ml``. Default: not set.

``extra_s3_args``
    A JSON object of any other boto3 S3 write parameters. Keys here override
    the named options above. Invalid JSON, or JSON that is not an object,
    raises a ``ConfigError``. Default: not set.

Example:

.. code-block:: bash

    dvc remote modify myremote storage_class STANDARD_IA
    dvc remote modify myremote requester_pays true
    dvc remote modify myremote object_tags "env=prod&team=ml"
    dvc remote modify myremote extra_s3_args '{"ChecksumAlgorithm": "SHA256"}'

.. note::

    DVC validates remote options against its own config schema, so
    ``dvc remote modify`` accepts these keys only with a DVC version whose
    S3 schema includes them.

Tests
-----

By default tests will be run against moto.
To run against real S3, set ``DVC_TEST_AWS_REPO_BUCKET`` with an AWS bucket name.
