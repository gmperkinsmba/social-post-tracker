# Viral Content Lab

**Mac app install**

Build on macOS with Python 3.12, then install the owned app:

```sh
python3.12 -m venv .desktop-venv
.desktop-venv/bin/python -m pip install -r requirements-desktop.lock.txt
.desktop-venv/bin/python build_desktop.py
.desktop-venv/bin/python install_desktop.py
```

Open `~/Applications/Viral Content Lab.app` in Finder. Close its window or press Command-Q to quit. The app includes Python and uses an ad-hoc signature; it has no Developer ID signature or notarization. Drafts stay in `~/.viral-content-lab/workspace.json`. To remove the app, move it from Applications to Trash. The runtime data stays until you remove that folder yourself.

For optional browser development, run `python3 server.py` and open `http://127.0.0.1:8322`. The desktop app starts and stops its own local server.

First principle: Help small businesses learn which messages reach their audiences. Link each draft to reviewed claims and comparable results.

Viral Content Lab keeps audience briefs, draft reviews, and post results together. The bakery and its numbers are synthetic examples. Three fixed templates suggest openings. There is no AI writing, analytics service, or publishing connection.

## Run

Requires Python 3.10 or newer. No third-party packages are needed.

```sh
python3 server.py
```

Open http://127.0.0.1:8322. The server accepts local connections only. Set `VCL_PORT` to use another port. Set `VCL_RUNTIME_DIR` to choose where private data lives. By default, data stays outside this checkout in `~/.viral-content-lab/workspace.json`. Only your user account can read it.

## Use

Enter an audience, source notes, and a hypothesis. Pick one of three sample openings, then edit the draft. The review lists each sentence and estimates its reading grade. Add a source or mark it as an inference. The review stays tied to that draft and its source notes. Edit either, and the app clears the review. Export includes the draft and its review notes. Open claims stay marked, so you can keep working.

Add results with the platform, post age, cohort, count base, and evidence type. The app shows these details with each count. It marks results as matched only when platform, cohort, count base, and age agree. Manual entries are not checked. Bakery results are synthetic.

Settings explains local storage and external connections. There are no API keys or external connections to configure. Reset restores the synthetic demo. No action publishes or sends content.

## Verify

```sh
python3 -m unittest discover -s tests -v
```

## Limits

The claim list is a review aid. It does not check facts. You review each sentence. Reading grade is an estimate. You enter results by hand. There is no platform API. The app does not predict reach or virality.

## License

Original code is released under the MIT License. See `LICENSE`.
