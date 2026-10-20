# LyX AI quick start

1. Extract the complete Windows package. Save and close LyX and LyX AI.
2. Run `Install.cmd`, then launch **LyX AI - Start LyX** from the Windows Start Menu. Existing profiles/keys/templates are retained. The app is installed under `%LOCALAPPDATA%\LyXAI`.
3. Select main-body prose and choose **AI Writing Assistant…**. The menu follows the LyX UI language through a user-level gettext overlay. Old launchers may need signing out/in once to refresh `LYX_LOCALEDIR`.
4. Surrounding body context is read automatically from the live buffer, including unsaved edits; notes/footnotes are excluded. Adjust the radius or append manual context using the before/after menus.

   **Target passage / Before / After** are buttons with character counts. Click to inspect or edit in a dialog, then **Save**; **Cancel** keeps the original. The main interface uses a white background, including under a dark system palette.
5. Open **Configure models**, set your endpoint, protocol, key, model and optional reasoning/timeouts. Relay services can use any of the three supported protocols.
6. Preview the request, then send. Only the target should be revised; surrounding prose is reference material.

Structured LyX import excludes only note/footnote/margin-note contents from selections spanning main-body prose. It includes labels, ERT source, figures, captions, tables and box contents. Do not select text from inside an opened note or footnote: a clipboard fragment may lose its parent type. Plain text pasted manually cannot be filtered reliably.

7. Open the reading preview for offline Markdown/LaTeX. A single `[REVISED]…[/REVISED]` block is extracted into the editable replacement tab. Review it and click **Apply at LyX position** in the global bottom toolbar, available from every tab. Native math supports inline, single-line displayed and multiline align/aligned equations, preserving native labels and numbering. One Ctrl+Z in LyX undoes it.

Reply language, selected and edited prompts, model, context settings (including 1200 characters), window size and panel/tab positions are saved automatically. Small windows use scrollable panels and a wrapping toolbar; hover over the one-line status message for full details. Preview tab switches reuse the same window and browser.

Ten built-in prompt templates are available in the purple task panel. Editing one immediately creates a custom template; further edits update that custom item automatically. Switching back to a built-in restores its original content. Built-in content comes from the app, while only custom prompt contents persist. Legacy preset edits are kept as custom items on upgrade. The assistant UI language is saved immediately and restored on the next launch.

While AI is responding, you may select a different passage, click a new caret position, or edit the same document. Apply uses the latest selection (replace) or caret (insert), and can be used again at another position. Switching documents and unresolved tracked changes are refused. Mixed Theorem/Proof/body layouts are supported: corresponding plain-text paragraphs keep their individual layouts, while explicit LaTeX environments allow added or removed paragraphs. Requests supply environment boundaries and embedded source automatically. LaTeX commands and mixed latex/tex fences are converted in a temporary directory before native paste. Class-provided theorem modules are respected, including IEEEtran; failed conversion leaves the document unchanged. If unstructured text changes a mixed target's paragraph count, it is applied as body text with an explicit status notice; use LaTeX environments to retain theorem/proof boundaries. Try a copy of `examples/mixed-layouts-demo.lyx`.

References such as `\eqref`, `\ref` and `\cite` become native objects. Applying replaces the entire selection. Native preservation tokens restore selected annotations without sending their contents to AI; omitted annotations may be removed, and one undo restores the original. Select complete math objects from the body, not portions inside formulas. Markdown complex layouts are not reconstructed on writeback.

The prompt configuration format is upgraded automatically; the original encrypted configuration is backed up as `config.before-template-migration.json` on its first save. Restore an old configuration backup before rolling back to an older assistant. Profiles and history are retained.

Settings use Windows DPAPI or macOS Keychain. For macOS installation, see [the macOS guide](INSTALL.macOS.md). Live context uses a temporary local snapshot deleted after reading. Native LyX clipboard/paste/undo and offline formula rendering have been tested. Real provider accounts and desktop context-menu clicks still need short acceptance. See [upgrade instructions](UPGRADE.zh-CN.md).

Use **History…** to search, load, continue or delete conversations. Sent targets, context, questions, answers and reasoning summaries are stored locally in `history.sqlite3` beside the settings, without credentials. Standalone startup restores the last conversation. A loaded history never restores an old native LyX selection as a writeback target.

History opens on **AI reply**, displaying only the answer for the chosen turn. Use the turn selector to inspect earlier replies and follow-ups; **User question**, **Reasoning / summary** and **Full conversation** are separate tabs. Failed turns show received partial replies or an empty-answer message, alongside the failure status. Existing saved histories work without conversion.

Theorem/Lemma layouts are preserved. LaTeX structures and formatting commands use the native importer; ERT source areas keep real LaTeX source for typesetting. Use theorem layouts built into the document class or enable a matching Theorems module first; try `examples/regions-demo.lyx`.

Figures, captions, table cells, boxes, labels and embedded source are included in requests. Keep every `\lyxaiobject{…}` token verbatim and in its relative position: it restores an existing native resource or complex object. Ordinary table cells, captions and box text are editable. Existing table borders/widths, box and float settings and corresponding paragraph spacing are retained when their structure matches. Merged-cell and other complex native objects remain intact; their internal text is currently read-only reference material. Try `examples/objects-demo.lyx` with `examples/sample.png` beside it. All built-in prompts include these preservation rules; custom prompts receive the same rules in actual requests.

For upgrades, extract the complete new package into a new folder, close both apps, then run its `Install.cmd`. Install all runtime files together. Settings and history are retained. Conversion uses tex2lyx from the installed LyX and never modifies LyX's installation. Missing labels/resources or failed conversion are reported before a paste; no LyX import dialog is launched.

Manual menu removal:

```powershell
& "$env:LOCALAPPDATA\LyXAI\LyXAI.exe" --uninstall
```

For source installation, use Python 3.12, install `requirements.txt`, then run `python main.py --configure` and `python main.py --install`. Keep the source directory and Python environment in place after installing its menu.

Module compatibility is resolved from class/module declarations rather than class-name exceptions: provided/excluded modules, symmetric exclusions, dependency order, alternative dependencies, defaults and user-removed defaults. Invalid combinations fail before writeback with named reasons, without modifying the document settings. Real converter checks cover 18 successful cases across article/book, journal classes, Beamer/Powerdot, non-theorem modules and a temporary custom Observation module; four invalid pairs are rejected. This does not imply exhaustive support for all third-party classes or macros.
