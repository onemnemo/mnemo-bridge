"""The writer's handling of Notion's request rules and refusals, against a fake API."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mnemo_bridge import mnemo as m
from mnemo_bridge.sources.notion.client import NotionError
from mnemo_bridge.package import write_package
from mnemo_bridge.sources.notion.push import NotionWriter

from .test_reverse import FakeWriterClient


class StrictClient(FakeWriterClient):
    """The fake, plus deletes and the refusals the real API makes."""

    def __init__(self, refuse=lambda block: False, refuse_icon=False):
        super().__init__()
        self.deleted = []
        self.refuse = refuse
        self.refuse_icon = refuse_icon

    def create_page(self, parent_page_id, title, *, icon_emoji=None, children=None):
        if icon_emoji and self.refuse_icon:
            raise NotionError("400 invalid emoji", 400)
        return super().create_page(parent_page_id, title, icon_emoji=icon_emoji, children=children)

    def append_children(self, block_id, children):
        if any(self.refuse(child) for child in children):
            raise NotionError("400 validation_error", 400)
        if block_id.startswith("col") and any(c.get("type") == "column_list" for c in children):
            raise NotionError("400 columns cannot nest", 400)
        return super().append_children(block_id, children)

    def delete_block(self, block_id):
        self.deleted.append(block_id)


def text(value):
    return m.Block(type=m.TEXT, spans=[m.plain(value)])


def table(rows):
    cell = lambda t: m.Block(type=m.TABLE_CELL, spans=[m.plain(t)], payload=m.table_cell_payload())
    return m.Block(
        type=m.TABLE,
        payload=m.table_payload([], [False] * rows, [False]),
        children=[m.Block(type=m.TABLE_ROW, children=[cell(str(i))]) for i in range(rows)],
    )


def split(left, right):
    return m.Block(
        type=m.TWO_COLUMN,
        payload=m.two_column_payload(0.5),
        children=[m.Block(type=m.COLUMN_GROUP, children=left), m.Block(type=m.COLUMN_GROUP, children=right)],
    )


def push(notes, client, folders=()):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.mnemo"
        write_package(path, notes, list(folders), {}, app_version="t")
        return NotionWriter(client).push_package(str(path), "root")  # type: ignore[arg-type]


def contents(client):
    """Every paragraph's text, in the order it was written."""
    out = []

    def walk(blocks):
        for child in blocks:
            if child.get("type") == "paragraph" and child["paragraph"]["rich_text"]:
                out.append(child["paragraph"]["rich_text"][0]["text"]["content"])
            for column in child.get("column_list", {}).get("children", []):
                walk(column["column"]["children"])

    for _parent, children in client.appends:
        walk(children)
    return out


class Columns(unittest.TestCase):
    def test_table_first_in_a_column_goes_in_after_a_placeholder(self):
        client = StrictClient()
        push([m.Note(note_id="n1", title="N", blocks=[split([table(2)], [text("right")])])], client)
        column_list = client.appends[0][1][0]
        first_cell = column_list["column_list"]["children"][0]["column"]["children"][0]
        self.assertEqual(first_cell["type"], "paragraph")  # the placeholder, not the table
        table_append = next(c for _p, cs in client.appends for c in cs if c["type"] == "table")
        self.assertEqual(len(table_append["table"]["children"]), 2)
        self.assertEqual(len(client.deleted), 1)

    def test_nested_split_is_laid_out_in_sequence(self):
        client = StrictClient()
        inner = split([text("a")], [text("b")])
        result = push([m.Note(note_id="n1", title="N", blocks=[split([text("left")], [inner])])], client)
        self.assertIn("a", contents(client))
        self.assertIn("b", contents(client))
        self.assertFalse(any("partially written" in w for w in result.warnings))

    def test_only_one_block_per_column_rides_with_the_column_list(self):
        client = StrictClient()
        push([m.Note(note_id="n1", title="N", blocks=[split([text("1"), text("2")], [text("3")])])], client)
        column_list = client.appends[0][1][0]
        for column in column_list["column_list"]["children"]:
            self.assertEqual(len(column["column"]["children"]), 1)
        self.assertEqual(contents(client), ["1", "3", "2"])  # 2 follows into its column
        self.assertEqual(client.deleted, [])

    def test_sub_page_in_a_column_is_created_on_the_page(self):
        client = StrictClient()
        parent = m.Note(note_id="n1", title="Parent", blocks=[
            split([m.Block(type=m.PAGE, payload=m.page_payload("n2"))], [text("x")]),
        ])
        child = m.Note(note_id="n2", title="Child", parent_note_id="n1", blocks=[text("in")])
        result = push([parent, child], client)
        self.assertEqual(client.pages[1]["parent"], client.pages[0]["id"])
        self.assertTrue(any("column or list" in w for w in result.warnings))


class Limits(unittest.TestCase):
    def test_long_table_sends_rows_past_one_hundred_afterwards(self):
        client = StrictClient()
        push([m.Note(note_id="n1", title="N", blocks=[table(250)])], client)
        first = client.appends[0][1][0]
        self.assertEqual(len(first["table"]["children"]), 100)
        later = [len(cs) for parent, cs in client.appends[1:]]
        self.assertEqual(later, [100, 50])

    def test_a_batch_never_exceeds_a_thousand_blocks(self):
        client = StrictClient()
        push([m.Note(note_id="n1", title="N", blocks=[table(100) for _ in range(30)])], client)
        for _parent, children in client.appends:
            total = sum(1 + len(c.get("table", {}).get("children", [])) for c in children)
            self.assertLessEqual(total, 1000)

    def test_heading_children_follow_the_heading(self):
        client = StrictClient()
        heading = m.Block(type=m.HEADING1, spans=[m.plain("H")], children=[text("under")])
        push([m.Note(note_id="n1", title="N", blocks=[heading])], client)
        appended = client.appends[0][1]
        self.assertEqual([b["type"] for b in appended], ["heading_1", "paragraph"])


class Refusals(unittest.TestCase):
    def test_one_refused_block_costs_only_itself(self):
        bad = lambda block: block.get("type") == "paragraph" and any(
            r["text"]["content"] == "bad" for r in block["paragraph"]["rich_text"]
        )
        client = StrictClient(refuse=bad)
        result = push([m.Note(note_id="n1", title="N", blocks=[text("a"), text("bad"), text("c")])], client)
        self.assertEqual(contents(client), ["a", "c"])
        self.assertTrue(any("refused a paragraph" in w for w in result.warnings))

    def test_refused_icon_still_creates_the_page(self):
        client = StrictClient(refuse_icon=True)
        result = push([m.Note(note_id="n1", title="N", emoji="🫠", blocks=[text("x")])], client)
        self.assertEqual(result.pages_created, 1)
        self.assertEqual(contents(client), ["x"])
        self.assertTrue(any("icon" in w for w in result.warnings))

    def test_sub_folder_listed_first_still_nests(self):
        client = StrictClient()
        folders = [
            m.Folder(folder_id="child", name="Child", parent_id="parent", order=0),
            m.Folder(folder_id="parent", name="Parent", order=1),
        ]
        push([], client, folders)
        by_title = {p["title"]: p for p in client.pages}
        self.assertEqual(by_title["Child"]["parent"], by_title["Parent"]["id"])


if __name__ == "__main__":
    unittest.main()
