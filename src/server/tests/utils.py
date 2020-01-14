from typing import Iterable

from quarchive import Bookmark

from .conftest import working_cred_headers


def sync_bookmarks(client, bookmarks: Iterable[Bookmark]):
    response = client.post(
        "/sync",
        json={"bookmarks": [bookmark.to_json() for bookmark in bookmarks]},
        headers=working_cred_headers,
    )
    assert response.status_code == 200
