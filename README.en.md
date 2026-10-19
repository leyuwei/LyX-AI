# LyX AI

**Give AI the surrounding prose, then apply revised text and editable equations directly in LyX.**

[简体中文](README.md) · **English**

![LyX AI with automatic body context, Markdown and equation preview, and the global Apply button](docs/images/main-en.png)

*Actual application interface with illustrative content. No AI request was sent to create this screenshot.*

## From selection to revision, inside your writing workflow

Select a passage in the LyX document body and open the assistant from the context menu. Surrounding prose is collected automatically. Review the context, choose a prompt and model, read the suggestions, and apply the revision to the original selection.

**Select prose → Collect context → Ask AI → Preview text and equations → Apply the revision**

| Highlight | What it gives you |
|---|---|
| **Automatic body context** | Reads the live document, including unsaved edits. Collects a configurable amount of surrounding prose while excluding Note, Footnote and other block objects from main-body ranges. |
| **Native equation writeback** | Inline, displayed and multiline align/aligned equations become editable LyX math objects, retaining supported numbering and label structures. |
| **Markdown and math preview** | Read headings, lists, tables and equations in an offline preview before using the revision. |
| **Your models and relay services** | Separate profiles for endpoints, protocols, keys, models, generation settings, reasoning, proxies and timeouts. |
| **Prompts for writing tasks** | Edit or save templates for academic editing, proofreading, concision, logical flow, equations and translation; continue with follow-up questions. |
| **Reviewable, undoable changes** | Inspect the outgoing request, verify the source selection before applying, and undo the replacement in LyX with one action. |

## Connect your own models

![Separate model configuration dialog with provider profiles, protocols, reasoning and timeout settings](docs/images/models-en.png)

*Configuration demonstration with placeholder endpoints and model IDs. No credentials are shown.*

Configuration presets cover OpenAI, Claude, DeepSeek, Kimi, Grok, GLM / BigModel, BigModel Coding, Z.ai and custom relay services. Choose **OpenAI Chat Completions, OpenAI Responses or Claude Messages** to match the protocol your endpoint serves.

Keep official endpoints and relay configurations in separate profiles. Configure generation parameters, reasoning mode and effort, output limits, custom headers and advanced JSON. Available parameters and model access depend on the service you connect to.

## Revise prose and equations together

Applicable revisions are placed in a separate, editable **Replacement** area. Review or edit the passage, preview it, then use **Apply to LyX selection** in the global bottom toolbar, available from every tab.

- Supports inline math, single-line displayed equations and multiline alignment, including standalone `align` and `aligned` environments.
- Keeps the target passage separate from preceding and following context, so the requested editing scope is clear.
- Refuses an overwrite if the document or selection has changed; asks for a narrower target when complex objects such as references or footnotes are included.
- Follows the LyX UI language for context-menu labels. The assistant has its own persistent Chinese/English language setting.

## A local companion with a visible sending scope

Installs in your user directory without modifying LyX program files. Credentials are encrypted with **Windows DPAPI** for the current account. Selections and conversations are not automatically written to configuration files. Automatic context uses a temporary local document snapshot that is deleted after reading.

KaTeX and fonts are bundled for offline preview rendering. When you send a request, the passage and context in the input area go to your configured API. Inspect the complete request beforehand.

## Get started

1. Extract the complete Windows package. Save your work, close LyX and the assistant, and run `Install.cmd`.
2. Launch **LyX AI - Start LyX** from the Windows Start Menu. Select main-body prose and open the assistant from the context menu.
3. Open **Configure models**, enter your endpoint and credentials, and review the context and prompt before sending.
4. Check the revision in the preview, then use the global Apply button. Press **Ctrl+Z** in LyX to undo it.

An overwrite installation retains model profiles, prompts and language preferences. Keep the dependency folders with the executable. Try writeback on a document copy first, and select text from the main document body.

Run from source:

```powershell
python -m pip install -r requirements.txt
python main.py --configure
```

## Learn more

- [English quick start](docs/QUICKSTART.en.md)
- [Installation and removal — Chinese](docs/INSTALL.zh-CN.md) · [Upgrade guide — Chinese](docs/UPGRADE.zh-CN.md)
- [Usage, prompts and model parameters — Chinese](docs/USER-GUIDE.zh-CN.md)
- [Testing, verification and supported scope — Chinese](docs/TESTING.zh-CN.md)
- [Third-party components and licenses](docs/THIRD-PARTY.md)
