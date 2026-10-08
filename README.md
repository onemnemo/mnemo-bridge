# Mnemo Bridge

Import and export notes between [Mnemo](https://github.com/onemnemo/mnemo) and external services.

Mnemo Bridge handles conversions that require API access rather than a file-based importer. It runs locally and preserves note structure and formatting wherever the destination supports it.

**Supported integrations:** [Notion](https://www.notion.so) (bidirectional). More integrations are planned.

<p align="center">
  <img src="docs/screenshots/choose-pages.png" alt="Choosing Notion pages to export" width="49%">
  <img src="docs/screenshots/exported.png" alt="A finished export with the steps to import it in Mnemo" width="49%">
</p>

## Download

Get the latest version from [GitHub Releases](https://github.com/onemnemo/mnemo-bridge/releases/latest).

| Platform | File |
| --- | --- |
| Windows | `MnemoBridge-win-Setup.exe` |
| macOS (Apple Silicon) | `MnemoBridge-osx-Setup.pkg` |
| Linux | `MnemoBridge.AppImage` |

Windows builds are currently unsigned. Linux users may need `libfuse2` and must make the AppImage executable with `chmod +x`.

Installed versions check for updates on startup and ask before installing.

## Notion

Move pages between Mnemo and Notion, including nested pages, images, tables, equations, callouts, colours, and other formatting.

- **Notion → Mnemo:** Export pages and databases as a `.mnemo` package, then import it through **Notes → Import**.
- **Mnemo → Notion:** Create Notion pages directly, including images and nested notes.

### Connect

1. Create an integration at [notion.so/my-integrations](https://www.notion.so/my-integrations) and copy its secret.
2. In Notion, open a top-level page and select **⋯ → Connections → your integration**. Repeat for other top-level pages you want to access.
3. Enter the secret in Mnemo Bridge.

When enabled, **Remember** stores the secret in your system keychain, falling back to `~/.mnemo-bridge/config.json` if no keychain is available.

Exporting to Notion requires permission to insert content into the destination page.

### Compatibility

Most note content transfers in both directions:

- Rich text, headings, lists, checklists, links, and colours
- Tables, columns, callouts, code, and equations
- Images, captions, and nested pages

Some features need special handling:

| Feature | Behaviour |
| --- | --- |
| Databases | Exported as folders of notes, with properties converted to tags or tables |
| Page covers | Included with `--covers` |
| Toggles | Content preserved, collapsed state lost |
| Attachments | Non-image files become links |
| Notion-only features | Views, filters, formulas, relations, and unsupported blocks aren't preserved |
| Folders | Converted to parent pages in Notion |

Notion supports only three heading levels and has different colour and table limitations. Equations exceeding its 1,000-character limit become code blocks.

Skipped or converted content is reported in the export warnings. Custom colour mappings are supported through `--color-map FILE`.

## Command line

The CLI supports the same conversions as the desktop app.

```bash
pip install -r requirements.txt
export NOTION_TOKEN=ntn_...
```

On PowerShell, set the token using `$env:NOTION_TOKEN = "ntn_..."`.

**Notion → Mnemo**

```bash
# Export accessible pages
python -m mnemo_bridge notion pull -o notes.mnemo

# Export specific content
python -m mnemo_bridge notion pull --page PAGE_URL --covers
python -m mnemo_bridge notion pull --database DATABASE_ID
```

**Mnemo → Notion**

```bash
python -m mnemo_bridge notion push notes.mnemo --parent PARENT_PAGE_URL
```

Use `python -m mnemo_bridge --help` to see all commands and options.

### Things to know

- **Caching:** Notion API responses are cached in `.notion-cache/`. Use `--no-cache` to fetch updated content.
- **Reimporting:** Exported notes retain their Notion IDs. Use Mnemo's **Overwrite** import policy to update existing notes.
- **Interrupted uploads:** Pages already created in Notion remain there. Remove them before retrying to prevent duplicates.

## Development

Run the desktop app from source:

```bash
pip install -r requirements-gui.txt
python -m mnemo_bridge gui
```

Run tests or build the app:

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -t .
pyinstaller mnemo-bridge.spec
```

Tests run offline and validate generated packages against Mnemo's `BlockJsonConverter`.

### Structure

```text
mnemo_bridge/
├── mnemo.py       # Note model
├── package.py     # .mnemo package handling
├── cli.py         # CLI commands
├── updates.py     # App updates
├── gui/           # Desktop interface
└── sources/
    └── notion/    # Notion API and converters
```

Each integration lives under `sources/` and uses the shared Mnemo package format. To add one, implement its converter, register its CLI commands, and add the corresponding GUI flow.

### Releases

Releases are built through [GitHub Actions](.github/workflows/release.yml) for Windows, macOS, and Linux using [Velopack](https://velopack.io).

Update `__version__` in `mnemo_bridge/__init__.py` and push a matching tag:

```bash
git tag v1.2.0
git push origin v1.2.0
```

The workflow runs tests, builds installers, and publishes the release. macOS signing requires the organization's Apple credentials; Windows signing is not yet configured.

Pre-release versions are excluded from automatic updates unless enabled in `updates.py`. The `MnemoBridge` pack ID must remain unchanged for updates to work.

## Troubleshooting

| Problem | Solution |
| --- | --- |
| No Notion pages found | Connect the integration to each top-level page |
| Mnemo rejects the package | Tables require Mnemo from mid-2026 or later |
| Database missing | Try `--notion-version 2025-09-03` for databases with multiple data sources |
| Notion returns 404 | Connect the integration to the destination parent page |

## License

[Apache-2.0](LICENSE)