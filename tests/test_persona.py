from ai import persona


def test_placeholders_and_headings_do_not_count():
    assert not persona.has_content("# comment\n昵称：<<你的昵称>>\n我说话的样子：\n- <<口头禅>>")
    assert persona.has_content("昵称：Emma\n我说话的样子：\n- 笑死")


def test_render_leaves_json_braces_alone():
    out = persona.render('hi {{me}} {"a": 1} {{missing}}', me="Emma")
    assert out == 'hi Emma {"a": 1} {{missing}}'


def test_every_prompt_exists_in_both_languages():
    names = {p.stem for p in (persona.PROMPT_DIR / "zh").glob("*.txt")}
    assert names == {p.stem for p in (persona.PROMPT_DIR / "en").glob("*.txt")}
    for lang in ("zh", "en"):
        for name in names - {"banned", "judge", "learn", "consolidate"}:
            text = (persona.PROMPT_DIR / lang / f"{name}.txt").read_text()
            assert "{{me}}" in text, (lang, name)
