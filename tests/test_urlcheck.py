from shared.urlcheck import is_allowed_video_url, is_playlist_url


def test_allows_https_youtube():
    assert is_allowed_video_url("https://www.youtube.com/watch?v=abc123")
    assert is_allowed_video_url("https://youtu.be/abc123")


def test_allows_https_instagram():
    assert is_allowed_video_url("https://www.instagram.com/reel/abc123/")


def test_rejects_non_https_scheme():
    assert not is_allowed_video_url("http://www.youtube.com/watch?v=abc123")
    assert not is_allowed_video_url("file:///etc/passwd")
    assert not is_allowed_video_url("ftp://youtube.com/x")


def test_rejects_disallowed_host():
    assert not is_allowed_video_url("https://evil.example.com/watch?v=abc")
    assert not is_allowed_video_url("https://169.254.169.254/latest/meta-data/")


def test_rejects_lookalike_host():
    # host must match exactly, not just contain "youtube.com" as a substring
    assert not is_allowed_video_url("https://youtube.com.evil.example/watch?v=abc")


def test_rejects_malformed_url():
    assert not is_allowed_video_url("not a url")
    assert not is_allowed_video_url("")


def test_playlist_url_detects_list_param():
    assert is_playlist_url("https://www.youtube.com/playlist?list=PL123")
    assert is_playlist_url("https://www.youtube.com/watch?v=abc&list=PL123")


def test_playlist_url_rejects_plain_video():
    assert not is_playlist_url("https://www.youtube.com/watch?v=abc123")
    assert not is_playlist_url("https://youtu.be/abc123")


def test_playlist_url_rejects_instagram():
    assert not is_playlist_url("https://www.instagram.com/reel/abc123/?list=x")


def test_playlist_url_rejects_disallowed_host():
    assert not is_playlist_url("https://evil.example.com/playlist?list=PL123")
