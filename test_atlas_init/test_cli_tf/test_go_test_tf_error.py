from __future__ import annotations

import pytest

from atlas_init.cli_tf.go_test_tf_error import GoTestErrorClass


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("Error: OUT_OF_CAPACITY The requested region is currently out of capacity", GoTestErrorClass.OUT_OF_CAPACITY),
        ("Error: HTTP 500 Internal Server Error occurred", GoTestErrorClass.FLAKY_500),
        ("UNEXPECTED_ERROR occurred during the request", GoTestErrorClass.FLAKY_500),
        ("503 Service Unavailable error from the server", GoTestErrorClass.FLAKY_500),
        ("dial tcp: lookup mongodb.com failed", GoTestErrorClass.FLAKY_CLIENT),
        ("i/o timeout while connecting to server", GoTestErrorClass.FLAKY_CLIENT),
        ("dial tcp: lookup failed", GoTestErrorClass.FLAKY_CLIENT),
        ("mongodbatlas: failed to retrieve authentication checksums for provider", GoTestErrorClass.PROVIDER_DOWNLOAD),
        ("Error: Failed to install provider github.com: bad response", GoTestErrorClass.PROVIDER_DOWNLOAD),
        ("timeout while waiting for resource to be ready", GoTestErrorClass.TIMEOUT),
        ("context deadline exceeded during operation", GoTestErrorClass.TIMEOUT),
        ("OUT_OF_CAPACITY_ERROR", GoTestErrorClass.OUT_OF_CAPACITY),
    ],
)
def test_auto_classification_positive_cases(output: str, expected: GoTestErrorClass):
    assert GoTestErrorClass.auto_classification(output) == expected


@pytest.mark.parametrize(
    "output",
    [
        "dial tcp: something else",
        "dial tcp without lookup",
        "Some completely unrelated error message",
        "",
        "out_of_capacity",
    ],
)
def test_auto_classification_returns_none(output: str):
    assert GoTestErrorClass.auto_classification(output) is None


def test_auto_classification_first_match_wins():
    output = "OUT_OF_CAPACITY HTTP 500 error occurred"
    assert GoTestErrorClass.auto_classification(output) == GoTestErrorClass.OUT_OF_CAPACITY
