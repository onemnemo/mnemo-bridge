"""Table and column handlers for BlockConverter."""

from __future__ import annotations

from ... import mnemo
from ...mnemo import Block, plain
from .richtext import convert_rich_text, rich_text_to_plain


class LayoutHandlers:
    """Mixin: needs `colors`, `stats`, `warnings`, `_children`, `_kids` and `convert_children_of`."""

    def _table(self, notion, data, depth):
        rows_notion = self._children(notion.get("id") or "") if notion.get("has_children") else []
        width = int(data.get("table_width") or 0)
        rows: list[Block] = []
        for row_index, row_notion in enumerate(rows_notion):
            if row_notion.get("type") != "table_row":
                continue
            cells_data = (row_notion.get("table_row") or {}).get("cells") or []
            width = max(width, len(cells_data))
            cells = [
                Block(
                    type=mnemo.TABLE_CELL,
                    spans=convert_rich_text(cell, self.colors),
                    payload=mnemo.table_cell_payload(),
                    id=mnemo.stable_id("cell", row_notion.get("id") or "", str(cell_index)),
                )
                for cell_index, cell in enumerate(cells_data)
            ]
            if not cells:
                cells = [
                    Block(
                        type=mnemo.TABLE_CELL,
                        payload=mnemo.table_cell_payload(),
                        id=mnemo.stable_id("cell", row_notion.get("id") or "", "0"),
                    )
                ]
            rows.append(
                Block(
                    type=mnemo.TABLE_ROW,
                    spans=[plain("")],
                    children=cells,
                    id=mnemo.stable_id("row", row_notion.get("id") or "", str(row_index)),
                )
            )

        if not rows:
            self.stats.drop("table")
            self.warnings.append("a table had no rows and was skipped")
            return []

        # Mnemo indexes cells by column, so every row needs the full width.
        for row in rows:
            row_id = row.id
            while len(row.children) < width:
                row.children.append(
                    Block(
                        type=mnemo.TABLE_CELL,
                        payload=mnemo.table_cell_payload(),
                        id=mnemo.stable_id("pad", row_id, str(len(row.children))),
                    )
                )

        # Notion's has_column_header means the first row holds the column labels
        # and has_row_header means the first column holds the row labels. Mnemo
        # stores a flag per row and per column.
        header_rows = [i == 0 and bool(data.get("has_column_header")) for i in range(len(rows))]
        header_columns = [i == 0 and bool(data.get("has_row_header")) for i in range(max(width, 1))]
        return [
            Block(
                type=mnemo.TABLE,
                spans=[plain("")],
                payload=mnemo.table_payload([], header_rows, header_columns),
                children=rows,
                id=mnemo.stable_id("block", notion.get("id") or ""),
            )
        ]

    def _table_row(self, notion, data, depth):
        cells = (data.get("cells") or [])
        text = " | ".join(rich_text_to_plain(cell) for cell in cells)
        return [Block(type=mnemo.TEXT, spans=[plain(text)], id=mnemo.stable_id("block", notion.get("id") or ""))]

    def _column_list(self, notion, data, depth):
        columns_notion = self._children(notion.get("id") or "") if notion.get("has_children") else []
        columns_notion = [c for c in columns_notion if c.get("type") == "column"]
        if not columns_notion:
            return []

        contents = [self.convert_children_of(column.get("id") or "", depth) for column in columns_notion]
        ratios = [
            float((column.get("column") or {}).get("width_ratio") or 0) or 1.0 / len(columns_notion)
            for column in columns_notion
        ]

        if len(contents) == 1:
            return contents[0]
        return [self._split(contents, ratios, notion.get("id") or "", 0)]

    def _split(
        self, contents: list[list[Block]], ratios: list[float], notion_id: str, index: int
    ) -> Block:
        """
        Builds a right-nested chain of two-column splits.

        Mnemo's TwoColumn holds exactly two cells, so N columns become N-1 nested
        splits. Each level's ratio is the left column's share of the width still
        remaining, which keeps the widths proportional to Notion's.
        """
        left, rest = contents[0], contents[1:]
        remaining = sum(ratios) or 1.0
        ratio = max(0.1, min(0.9, (ratios[0] or 0.0) / remaining))
        right_blocks = (
            rest[0] if len(rest) == 1 else [self._split(rest, ratios[1:], notion_id, index + 1)]
        )
        return Block(
            type=mnemo.TWO_COLUMN,
            spans=[plain("")],
            payload=mnemo.two_column_payload(ratio),
            children=[
                self._column_group(left, notion_id, index, "l"),
                self._column_group(right_blocks, notion_id, index, "r"),
            ],
            id=mnemo.stable_id("block", notion_id, str(index)),
        )

    def _column_group(self, blocks: list[Block], notion_id: str, index: int, side: str) -> Block:
        # Mnemo seeds a Text block into an empty column cell on the first edit;
        # seeding here gives the same shape.
        return Block(
            type=mnemo.COLUMN_GROUP,
            spans=[plain("")],
            children=blocks or [Block(type=mnemo.TEXT, id=mnemo.stable_id("seed", notion_id, str(index), side))],
            id=mnemo.stable_id("col", notion_id, str(index), side),
        )

    def _column(self, notion, data, depth):
        return self._kids(notion, depth)
