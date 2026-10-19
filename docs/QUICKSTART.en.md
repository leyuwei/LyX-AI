# LyX AI quick start

1. Extract the complete Windows package. Save and close LyX and LyX AI.
2. Run `Install.cmd`, then launch **LyX AI - Start LyX** from the Windows Start Menu. Existing profiles/keys/templates are retained. The app is installed under `%LOCALAPPDATA%\LyXAI`.
3. Select main-body prose and choose **AI Writing Assistant…**. The menu follows the LyX UI language through a user-level gettext overlay. Old launchers may need signing out/in once to refresh `LYX_LOCALEDIR`.
4. Surrounding body context is read automatically from the live buffer, including unsaved edits; notes/footnotes are excluded. Adjust the radius or append manual context using the before/after menus.

   **Target passage / Before / After** are buttons with character counts. Click to inspect or edit in a dialog, then **Save**; **Cancel** keeps the original. The main interface uses a white background, including under a dark system palette.
5. Open **Configure models**, set your endpoint, protocol, key, model and optional reasoning/timeouts. Relay services can use any of the three supported protocols.
6. Preview the request, then send. Only the target should be revised; surrounding prose is reference material.

Structured LyX import excludes note/footnote/margin/block insets from selections spanning main-body prose. Do not select text from inside an opened note or footnote: a clipboard fragment may lose its parent type. Plain text pasted manually cannot be filtered reliably.

7. Open the reading preview for offline Markdown/LaTeX. A single `[REVISED]…[/REVISED]` block is extracted into the editable replacement tab. Review it and click **Apply at LyX position** in the global bottom toolbar, available from every tab. Native math supports inline, single-line displayed and multiline align/aligned equations, preserving native labels and numbering. One Ctrl+Z in LyX undoes it.

Reply language, selected and edited prompts, model, context settings (including 1200 characters), window size and panel/tab positions are saved automatically. Small windows use scrollable panels and a wrapping toolbar; hover over the one-line status message for full details. Preview tab switches reuse the same window and browser.

Ten prompt templates are available. Upgrading appends new presets without replacing user edits. The assistant UI language is saved immediately and restored on the next launch.

While AI is responding, you may select a different passage, click a new caret position, or edit the same document. Apply uses the latest selection (replace) or caret (insert), and can be used again at another position. Switching documents, unresolved tracked changes and mixed paragraph layouts are refused. References such as `\eqref`, `\ref` and `\cite` become native objects. Applying replaces the entire selection, including selected notes, footnotes and other non-body objects; one undo restores them. Select complete math objects from the body, not portions inside formulas. Markdown complex layouts are not reconstructed on writeback.

Settings use Windows DPAPI or macOS Keychain. For macOS installation, see [the macOS guide](INSTALL.macOS.md). Live context uses a temporary local snapshot deleted after reading. Native LyX clipboard/paste/undo and offline formula rendering have been tested. Real provider accounts and desktop context-menu clicks still need short acceptance. See [upgrade instructions](UPGRADE.zh-CN.md).

Use **History…** to search, load, continue or delete conversations. Sent targets, context, questions, answers and reasoning summaries are stored locally in `history.sqlite3` beside the settings, without credentials. Standalone startup restores the last conversation. A loaded history never restores an old native LyX selection as a writeback target.

History opens on **AI reply**, displaying only the answer for the chosen turn. Use the turn selector to inspect earlier replies and follow-ups; **User question**, **Reasoning / summary** and **Full conversation** are separate tabs. Failed turns show received partial replies or an empty-answer message, alongside the failure status. Existing saved histories work without conversion.

Theorem/Lemma layouts are preserved. LaTeX structures and formatting commands use the native importer; ERT source areas keep real LaTeX source for typesetting. Enable a matching Theorems module in the current document first; try `examples/regions-demo.lyx`.

Manual menu removal:

```powershell
& "$env:LOCALAPPDATA\LyXAI\LyXAI.exe" --uninstall
```

For source installation, use Python 3.12, install `requirements.txt`, then run `python main.py --configure` and `python main.py --install`. Keep the source directory and Python environment in place after installing its menu.
