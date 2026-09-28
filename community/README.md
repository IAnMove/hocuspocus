# Community repository seed

`repo-seed/` is the initial content of the separate public repository
`IAnMove/hocuspocus-community` (not created yet). Copy it to the root of that
repository, enable GitHub Pages (source: GitHub Actions) and add the
`template-submission` label.

- `site/index.html`: static catalogue page (search, editor and tag filters, download).
- `.github/workflows/publish.yml`: validates `templates/**.hptemplate` with
  `scripts/community_index.py` from this repository and publishes `index.json`,
  previews, packages and the page to GitHub Pages.
- `.github/ISSUE_TEMPLATE/submit-template.yml` + `.github/workflows/submission.yml` +
  `.github/scripts/submission.py`: people submit a template through an issue form
  (attach the `.hptemplate` renamed to `.zip`); a bot validates it with the app's
  importer and opens the pull request. Publishing happens only when a maintainer merges.

Workflows inside this subfolder do not run in the main repository.
See [TEMPLATE_LIBRARY_PLAN](../docs/development/TEMPLATE_LIBRARY_PLAN_2026-09-28.md).
