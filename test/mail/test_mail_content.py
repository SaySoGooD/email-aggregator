from src.main import mail_content


def test_script_element_and_its_contents_are_dropped():
    out = mail_content.scrub("<p>hi</p><script>alert(1)</script><p>bye</p>")
    assert "alert" not in out
    assert "<script" not in out
    assert "hi" in out and "bye" in out


def test_inline_event_handlers_are_dropped():
    out = mail_content.scrub('<img src="cid:x" onerror="alert(1)">')
    assert "onerror" not in out
    assert "alert" not in out


def test_javascript_urls_are_dropped_but_the_link_text_survives():
    out = mail_content.scrub('<a href="javascript:alert(1)">click</a>')
    assert "javascript" not in out
    assert "click" in out


def test_http_and_cid_urls_are_kept():
    out = mail_content.scrub('<a href="https://example.com/x">e</a><img src="cid:1">')
    assert "https://example.com/x" in out
    assert "cid:1" in out


def test_data_urls_are_limited_to_images():
    assert "data:image/png" in mail_content.scrub('<img src="data:image/png;base64,AA">')
    assert "data:text/html" not in mail_content.scrub('<a href="data:text/html,x">y</a>')


def test_iframe_and_object_subtrees_are_dropped():
    out = mail_content.scrub('<iframe src="https://evil"><b>x</b></iframe><i>keep</i>')
    assert "iframe" not in out and "evil" not in out
    assert "keep" in out


def test_text_is_re_escaped_so_it_cannot_become_markup():
    out = mail_content.scrub("&lt;script&gt;alert(1)&lt;/script&gt;")
    assert "<script" not in out
    assert "&lt;script&gt;" in out


def test_style_element_keeps_its_css_unescaped():
    out = mail_content.scrub("<style>a > b { color: red }</style>")
    assert "a > b" in out


def test_document_denies_scripts_and_remote_loads_by_default():
    doc = mail_content.document("<p>x</p>", None)
    assert "script-src 'none'" in doc
    assert "img-src data: cid:" in doc


def test_document_allows_remote_images_only_when_asked():
    doc = mail_content.document("<p>x</p>", None, allow_remote=True)
    assert "img-src http: https: data: cid:" in doc
    assert "script-src 'none'" in doc  # never relaxed


def test_plain_text_body_is_escaped():
    doc = mail_content.document(None, "<b>not markup</b>")
    assert "&lt;b&gt;not markup&lt;/b&gt;" in doc


def test_remote_content_detection_ignores_plain_links():
    assert not mail_content.has_remote_content('<a href="https://example.com">x</a>')
    assert mail_content.has_remote_content('<img src="https://tracker/p.gif">')
