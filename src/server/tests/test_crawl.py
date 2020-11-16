from uuid import uuid4
import re
from unittest import mock
from datetime import datetime, timezone
from os import environ
import gzip
from urllib.parse import urlsplit

import requests
import responses
from freezegun import freeze_time
import pytest

import quarchive as sut
from quarchive import file_storage
from quarchive.data.functions import upsert_url, set_bookmark
from quarchive.data.models import CrawlRequest, CrawlResponse, SQLAUrl
from quarchive.value_objects import URL
from quarchive import crawler
from .conftest import random_string, make_bookmark

pytestmark = pytest.mark.crawler


@freeze_time("2018-01-03")
@pytest.mark.parametrize("status_code", [200, 404, 500])
def test_crawl_when_response_is_recieved(
    session, http_client, status_code, mock_s3, requests_mock
):
    url = URL.from_string("http://example.com/" + random_string())
    upsert_url(session, url)

    requests_mock.add(
        responses.GET, url.to_string(), body=b"hello", status=status_code, stream=True
    )

    crawl_uuid = crawler.crawl_url(session, http_client, url)

    request = session.query(CrawlRequest).get(crawl_uuid)
    response = session.query(CrawlResponse).get(crawl_uuid)

    assert request.requested == datetime(2018, 1, 3, tzinfo=timezone.utc)
    assert request.got_response
    assert response.status_code == status_code
    assert response.crawl_uuid == crawl_uuid
    assert response.headers == {"content-type": "text/plain"}

    s3_obj = (
        file_storage.get_s3()
        .Object(environ["QM_RESPONSE_BODY_BUCKET_NAME"], str(response.body_uuid))
        .get()
    )
    response_body = s3_obj["Body"].read()
    assert response_body == gzip.compress(b"hello")


def test_crawl_when_no_response(session, http_client, requests_mock):
    url = URL.from_string("http://example.com/" + random_string())
    upsert_url(session, url)

    requests_mock.add(
        responses.GET,
        url.to_string(),
        body=requests.exceptions.ConnectTimeout("connect timeout"),
    )

    crawl_uuid = crawler.crawl_url(session, http_client, url)

    request = session.query(CrawlRequest).get(crawl_uuid)
    response = session.query(CrawlResponse).get(crawl_uuid)
    assert request is not None
    assert response is None


def test_ensure_crawled_only_runs_once(session, http_client, mock_s3, requests_mock):
    url = URL.from_string("http://example.com/" + random_string())
    upsert_url(session, url)

    requests_mock.add(responses.GET, url.to_string(), body=b"hello", stream=True)

    crawler.ensure_url_is_crawled(session, http_client, url)

    s, n, p, q, f = urlsplit(url.to_string())
    resp_query = (
        session.query(CrawlResponse)
        .join(CrawlRequest)
        .join(SQLAUrl)
        .filter(
            SQLAUrl.scheme == s,
            SQLAUrl.netloc == n,
            SQLAUrl.path == p,
            SQLAUrl.query == q,
            SQLAUrl.fragment == f,
        )
    )
    assert resp_query.count() == 1
    crawler.ensure_url_is_crawled(session, http_client, url)

    # Assert again
    assert resp_query.count() == 1


def test_request_crawls_for_uncrawled_urls(
    session, bg_worker, mock_s3, test_user, requests_mock
):
    bookmark = make_bookmark()
    set_bookmark(session, test_user.user_uuid, bookmark)
    session.commit()
    url = bookmark.url

    requests_mock.add(responses.GET, re.compile(r".*"), body=b"hello", stream=True)
    crawler.request_crawls_for_uncrawled_urls(session)

    resp_query = (
        session.query(CrawlResponse)
        .join(CrawlRequest)
        .join(SQLAUrl)
        .filter(
            SQLAUrl.scheme == url.scheme,
            SQLAUrl.netloc == url.netloc,
            SQLAUrl.path == url.path,
            SQLAUrl.query == url.query,
            SQLAUrl.fragment == url.fragment,
        )
    )
    assert resp_query.count() == 1
