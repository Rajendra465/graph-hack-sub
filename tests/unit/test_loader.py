import pytest

from codebook.loader import DataError, Link, parse_strength, select, strength_member


def test_parse_tab_separated_strength_table():
    lines = ["cue\tresponse\tR123\tN\tR123.Strength\n", "ocean\twave\t41\t297\t0.138\n", "ocean\tsea\t60\t297\t0.202\n"]
    links = list(parse_strength(lines))
    assert links == [Link("ocean", "wave", 41, 0.138), Link("ocean", "sea", 60, 0.202)]


def test_parse_quoted_comma_separated_table():
    lines = ['"cue","response","R1","N","R1.Strength"\n', '"Ocean","Wave","4","100","0.04"\n']
    assert list(parse_strength(lines)) == [Link("ocean", "wave", 4, 0.04)]


def test_parse_rejects_a_table_without_the_columns():
    with pytest.raises(DataError):
        list(parse_strength(["a,b,c\n", "1,2,3\n"]))


def test_strength_member_prefers_r123():
    names = ["SWOW-EN18/strength.SWOW-EN.R1.20180827.csv", "SWOW-EN18/strength.SWOW-EN.R123.20180827.csv",
             "SWOW-EN18/SWOW-EN.R100.20180827.csv"]
    assert strength_member(names).endswith("R123.20180827.csv")


def test_select_drops_rare_multiword_and_self_links_and_marks_clue_words():
    links = [Link("ocean", "wave", 41, 0.138), Link("ocean", "ice cream", 9, 0.03),
             Link("ocean", "ocean", 5, 0.02), Link("ocean", "kelp", 1, 0.003), Link("wave", "hand", 12, 0.04)]
    words, rows = select(links, clue_list=["ocean", "hand"], pool=["wave", "bank"])
    by_word = {w[0]: w for w in words}
    assert rows == [["ocean", "wave", 0.138, 41], ["wave", "hand", 0.04, 12]]
    assert by_word["ocean"] == ["ocean", True, True, False]
    assert by_word["hand"] == ["hand", False, False, False]     # in the clue list but never a cue
    assert by_word["bank"] == ["bank", False, False, True]      # board word without links still gets a node
