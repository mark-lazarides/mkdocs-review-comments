from mkdocs_review_comments.serve import api_url


def test_api_url_follows_the_dev_addr_host():
    assert api_url("127.0.0.1", 8803) == "http://127.0.0.1:8803"
    assert api_url("0.0.0.0", 9000) == "http://0.0.0.0:9000"
