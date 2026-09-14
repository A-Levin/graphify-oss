"""Tests for files that do not end with a newline.

In C and C++, if the .h file does not end with a newline '\n' an error
is throwed even if the file is valid. In order to avoid this, a new line
char is added only if the original file does not end with it.

In this test we will make sure this works.
"""

from graphify.extract import extract, extract_c, extract_cpp

TEST_HEADER_1 = """\
#define A 8
#define AA 3"""

TEST_HEADER_2 = """\
#define A 8

int foo(int bar) { return bar; }

int foo2(void) { return 0; }

#define AA 1"""

TEST_HEADER_3 = """\
#pragma once

#define A 4"""


def write(path, text):
    path.write_bytes(text.encode("utf-8"))
    return path


def stderr_of(tmp_path, path, capsys):
    extract([path], root=tmp_path)
    return capsys.readouterr().err


def test_c_header_without_newline(tmp_path, capsys):
    path = write(tmp_path / "test_header.h", TEST_HEADER_1)
    assert "partially extracted" not in stderr_of(tmp_path, path, capsys)


def test_cpp_header_without_newline(tmp_path, capsys):
    path = write(tmp_path / "test_header.hpp", TEST_HEADER_3)
    assert "partially extracted" not in stderr_of(tmp_path, path, capsys)


def test_c_header_with_newline(tmp_path, capsys):
    path = write(tmp_path / "test_header.h", TEST_HEADER_1 + "\n")
    assert "partially extracted" not in stderr_of(tmp_path, path, capsys)


def test_no_parse_errors(tmp_path):
    assert extract_c(write(tmp_path / "test_header.h", TEST_HEADER_1)).get("parse_errors") is None
    assert extract_cpp(write(tmp_path / "test_header.hpp", TEST_HEADER_3)).get("parse_errors") is None


def test_functions_are_still_found(tmp_path):
    path = write(tmp_path / "test_header.h", TEST_HEADER_2)
    labels = [node["label"] for node in extract_c(path)["nodes"]]
    assert "foo()" in labels
    assert "foo2()" in labels


def test_empty_file(tmp_path):
    path = write(tmp_path / "test_header.c", "")
    assert extract_c(path).get("parse_errors") is None


# --- Additional coverage (#3513 follow-up) ---------------------------------
#
# The cases above pin the reported symptom on .h/.hpp. The ones below widen
# that in two directions: every C/C++-family extension rather than headers
# only, the shapes where the unterminated directive is not the literal last
# line, and — most importantly — the guarantee that a file which really is
# broken still gets reported.

import pytest  # noqa: E402

from graphify.extract import extract_c, extract_cpp  # noqa: E402,F811

_C_EXTENSIONS = (".h", ".c")
_CPP_EXTENSIONS = (".hpp", ".cpp", ".cc", ".cxx", ".cu", ".cuh", ".metal")


def _extract_by_suffix(path):
    return extract_cpp(path) if path.suffix in _CPP_EXTENSIONS else extract_c(path)


@pytest.mark.parametrize("ext", _C_EXTENSIONS + _CPP_EXTENSIONS)
def test_every_c_family_extension_without_newline(tmp_path, ext):
    """Not header-specific: the spurious error reproduced on every extension
    routed to extract_c/extract_cpp, sources included."""
    path = write(tmp_path / f"valid{ext}", TEST_HEADER_1)
    result = _extract_by_suffix(path)
    assert result.get("parse_errors") is None, (
        f"{ext}: valid file with no trailing newline reported as having a "
        f"syntax error: {result.get('parse_errors')!r}")


@pytest.mark.parametrize("ext,content", [
    (".c", b"int f(void){return 1;}\n#define A 1"),
    (".cpp", b"struct P{int x;};\nint g(void){return 0;}\n#include <a.h>"),
])
def test_supplied_newline_shifts_no_node_or_edge(tmp_path, ext, content):
    """The newline is appended past the last real token, so it must not move a
    single node or edge: the same path with and without the trailing byte has
    to yield identical nodes and edges."""
    path = tmp_path / f"f{ext}"
    path.write_bytes(content)
    without_nl = _extract_by_suffix(path)
    path.write_bytes(content + b"\n")
    with_nl = _extract_by_suffix(path)
    without_nl.pop("parse_errors", None)
    with_nl.pop("parse_errors", None)
    assert without_nl["nodes"] == with_nl["nodes"]
    assert without_nl["edges"] == with_nl["edges"]


@pytest.mark.parametrize("ext,extractor", [(".c", extract_c), (".cpp", extract_cpp)])
def test_a_genuine_syntax_error_is_still_flagged(tmp_path, ext, extractor):
    """Supplying the missing newline must not swallow an actual syntax error
    that happens to sit before a trailing directive."""
    path = tmp_path / f"broken{ext}"
    path.write_bytes(b"int f( { return 1; }\n#define A 1")
    assert extractor(path).get("parse_errors") is not None, (
        f"{ext}: a genuinely broken file is no longer flagged")


def test_an_unterminated_conditional_is_still_flagged(tmp_path):
    """An `#if` with no matching `#endif` has nothing to do with the missing
    newline and must keep being reported."""
    path = tmp_path / "broken.c"
    path.write_bytes(b"#if FOO\nint x;\n")
    assert extract_c(path).get("parse_errors") is not None


@pytest.mark.parametrize("ext,extractor", [(".c", extract_c), (".cpp", extract_cpp)])
def test_backslash_continued_macro_at_eof(tmp_path, ext, extractor):
    """A multi-line macro via line continuation, unterminated — a common shape
    for the last macro in a header. Here the offending physical line does not
    itself start with `#`."""
    path = tmp_path / f"valid{ext}"
    path.write_bytes(b"#define MAX(a,b) \\\n  ((a) > (b) ? (a) : (b))")
    assert extractor(path).get("parse_errors") is None


def test_utf8_bom_before_trailing_directive(tmp_path):
    """A UTF-8 BOM at the start of the file must not defeat the fix at the end
    of it. Control: the same bytes plus a newline were already clean, so the
    BOM is the variable."""
    path = tmp_path / "valid.c"
    path.write_bytes(b"\xef\xbb\xbf#define A 8")
    assert extract_c(path).get("parse_errors") is None
    path.write_bytes(b"\xef\xbb\xbf#define A 8\n")
    assert extract_c(path).get("parse_errors") is None


def test_comment_before_trailing_directive(tmp_path):
    """A block comment ahead of the final unterminated directive."""
    path = tmp_path / "valid.c"
    path.write_bytes(b"int a;\n/* guard */ #define A 1")
    assert extract_c(path).get("parse_errors") is None
