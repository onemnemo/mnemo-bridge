# Contributing

Thanks for helping people move their notes. Mnemo Bridge is part of the Mnemo project and follows [Mnemo's contributing guide](https://github.com/onemnemo/mnemo/blob/main/CONTRIBUTING.md) and [coding standard](https://github.com/onemnemo/mnemo/blob/main/coding-standard.md). The points below are specific to this repository.

## Tests

```bash
python -m unittest discover -s tests -t .
```

The tests need no network and no Notion key. Every API call is faked, and it should stay that way.

`tests/test_mnemo.py` and `tests/test_package.py` check the output against what Mnemo's `BlockJsonConverter` and `wire.ts` read. Only change them after checking the Mnemo source, because they are what catches a format change before it breaks someone's import.

## Where changes go

- **A Notion block type:** a handler in `sources/notion/convert.py` (or `convert_layout.py` and `convert_links.py`) and a test in `test_convert.py`.
- **A Mnemo block type:** a payload constructor in `mnemo.py`, a handler in `sources/notion/reverse.py`, and tests in both directions. Mnemo's reader throws on an unknown payload kind, so payloads are only built through `mnemo.py`.
- **Colours:** `sources/notion/colors.py` for Notion to Mnemo and `sources/notion/reverse_text.py` for Mnemo to Notion. A note that goes to Mnemo and back must keep its colours.
- **API behaviour:** `sources/notion/client.py`. Writes are never cached, and never retried after a timeout or a server error, because Notion may already have applied them.
- **A new source:** see "Adding a source" in the [README](README.md#adding-a-source).
- **The app:** `mnemo_bridge/gui/web/` is plain HTML, CSS and JavaScript with no build step. All conversion logic stays in Python.

## Rules

1. **Nothing is dropped without a trace.** A block that can't be carried becomes a link or a placeholder, and the warnings name it.
2. **Output is deterministic.** Ids come from source ids through `mnemo.stable_id`, so exporting again updates notes instead of duplicating them.
3. **One bad item costs only itself.** Catch at the item level, warn, and continue.

## House style

- Commit subjects are `type(scope): subject`, lowercase and imperative. Scopes here are `pull`, `push`, `notion`, `gui`, `cli`, `release` and `repo`.
- No em or en dashes in code, comments, commits or copy. CI checks for them.
- Comment the why, and only when the code doesn't already say it.
- No `TODO`, `FIXME` or `HACK`. Open an issue instead.
- Keep files under about 400 lines. Add a module rather than grow one.

## Pull requests

- The tests pass.
- New behaviour has a test that fails without the change.
- Changes people will notice are in the README.

Contributions are licensed under Apache-2.0, the same as Mnemo.
