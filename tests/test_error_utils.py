from wled_album_art_under_test.error_utils import safe_error_text


def test_safe_error_text_redacts_http_urls_and_query_tokens() -> None:
    result = safe_error_text("download failed for https://music.example/cover.jpg?token=secret status=401")
    assert "music.example" not in result
    assert "token=secret" not in result
    assert "[redacted URL]" in result
    assert "status=401" in result


def test_safe_error_text_caps_long_messages() -> None:
    assert len(safe_error_text("x" * 900)) == 500
