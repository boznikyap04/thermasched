"""Upload results: open zipped run folders in this browser session, without results/."""

from __future__ import annotations

import streamlit as st

from dashboard import data, state

UPLOADER_N = "uploader_n"       # bumped after an import to clear the uploader
LAST_IMPORT = "last_import"     # (run keys, scenarios, problems) shown after the rerun


def _import(files) -> None:
    keys, scenarios, problems = [], [], []
    for f in files:
        res = state.import_upload(f)
        keys += [r.key for r in res.runs]
        scenarios += [s for s in res.scenarios if s not in scenarios]
        problems += [f"**{f.name}**: {p}" for p in res.problems]
    st.session_state[LAST_IMPORT] = (keys, scenarios, problems)
    st.session_state[UPLOADER_N] = st.session_state.get(UPLOADER_N, 0) + 1
    if keys:
        st.session_state[state.PENDING_RUN] = keys[0]
    st.rerun()


def _last_import() -> None:
    keys, scenarios, problems = st.session_state.get(LAST_IMPORT, ([], [], []))
    if keys:
        listed = "\n".join(f"- `{k}`" for k in keys)
        st.success(f"Opened {len(keys)} run{'s' if len(keys) != 1 else ''}:\n{listed}",
                   icon="✅")
        if scenarios:
            st.caption("Server names and clock times from the zip for: "
                       + ", ".join(f"`{s}`" for s in scenarios))
        if state.OVERVIEW_PAGE is not None:
            st.page_link(state.OVERVIEW_PAGE, label="Open in Run summary",
                         icon=":material/arrow_forward:")
    for p in problems:
        st.error(p, icon="⚠️")


def _how_to() -> None:
    with st.expander("How do I make the zip?"):
        st.markdown(
            "A run folder is the folder that contains `summary.json` (with `baseline/` and "
            "`optimized/` next to it).\n\n"
            "- **Mac**: right-click the run folder › **Compress**.\n"
            "- **Windows**: right-click the run folder › **Send to** › "
            "**Compressed (zipped) folder** (Windows 11: **Compress to ZIP file**).\n\n"
            "You can also zip a scenario folder with several runs in it, or the whole "
            "`results` folder: every run inside is opened. Zips made with the "
            "**Download run (.zip)** button in the sidebar open as they are.\n\n"
            "Uploading a run again replaces the earlier upload, so you can keep "
            "re-uploading a run while it changes.")


def _remove(ref=None) -> None:
    st.session_state.pop(LAST_IMPORT, None)
    state.remove_upload(ref)


def _uploaded_list() -> None:
    runs = state.uploaded_runs()
    if not runs:
        return
    st.subheader("Uploaded in this session")
    for ref in runs:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f":material/upload_file: `{ref.key}`", width="stretch")
            st.button("Remove", key=f"rm_{ref.key}", icon=":material/delete:",
                      on_click=_remove, args=(ref,))
    st.button("Remove all uploads", icon=":material/delete_sweep:",
              on_click=_remove)


def render() -> None:
    st.title("Upload results")
    st.caption("Open run folders shared as .zip files, such as the zips the solver and "
               "batch notebooks write to `exports/`. Uploads are only visible in this browser "
               "tab and are not saved; they are gone when you close or reload the tab.")
    st.info("**To keep a run on this site for everyone**, send its zip to the project "
            "owner, who adds it to the site's results.", icon=":material/forward_to_inbox:")
    if not state.discover_runs():
        st.info(f"There are no runs under `{data.RESULTS_DIR}` yet. Upload a zipped run "
                "folder here.", icon="📭")

    files = st.file_uploader("Zipped run folders", type="zip", accept_multiple_files=True,
                             key=f"uploader_{st.session_state.get(UPLOADER_N, 0)}")
    if files:
        with st.spinner("Unpacking…"):
            _import(files)
    _last_import()
    _how_to()
    _uploaded_list()
