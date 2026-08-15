"""Generate browser-rendered DOM-mutation training pairs from real websites.

The shipped model is trained by dataset_generator.py, which synthesises defects
by drawing on static screenshots with OpenCV: a filled rectangle stands in for a
removed element, an HSV shift for a colour regression, a warpAffine translation
for a layout shift. Real defects are nothing like that — the browser re-renders
the whole page, so a removed node reflows everything below it, text re-wraps and
anti-aliasing changes. Measured consequence (2026-08-05): 87.6% on the synthetic
validation set, 22.2% on real pages, with broken-image, font-change and
text-issue all at 0%.

This script closes that gap on the data side. It reuses live_dom_mutation_eval's
mutation machinery — the same JS mutations, the same ground-truth categories —
but keeps the captures instead of scoring and discarding them, producing labelled
pairs that were actually rendered by a browser.

SITES here is deliberately disjoint from live_dom_mutation_eval.SITES. Training
on the evaluation's own pages would leak the test set and inflate every number
that follows; keeping them apart makes the eval a genuine generalisation test —
train on one set of sites, measure on another.

Output: --out-dir holding baseline_N.png / current_N.png (plus the .dom.json
sidecars run_trial writes) and manifest.json listing {baseline, current, label,
url}. The manifest is rewritten after every trial, so an interrupted run is
still usable.

    python scripts/generate_live_training_pairs.py --trials 2200 --max-hours 3
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from live_dom_mutation_eval import CATEGORIES, run_trial  # noqa: E402

# Static documentation/project sites: stable markup, no ad rotation, and varied
# layouts (text-heavy, sidebar-nav, card grid, table-of-contents). Content that
# changes between the baseline and current capture would corrupt the label, so
# news and social pages are deliberately excluded.
#
# Site count is the variable that matters. Measured 2026-08-05: a model fine-
# tuned on 12 sites scored 90% on pages from those 12 and 18% on unseen ones —
# the entire gap was whether it had seen the site, not the architecture, the
# label set, or the preprocessing. Breadth here is what buys generalisation;
# depth per site does not.
#
# None of these may appear in live_dom_mutation_eval.SITES. Training on the
# evaluation's own pages would leak the test set and make every number after it
# meaningless.
#
# Sites tried and deliberately left out, 2026-08-14/15 (two training rounds,
# ~450 live trials): a real per-class accuracy swing traced to which of these
# got sampled, not to model quality.
#   - vuetifyjs.com, and Vue/React/Material component-showcase SPAs like it:
#     any mutation (color, text, missing-element, ...) cascades through the
#     framework's own re-render into a ~30% whole-page visual change, so the
#     ground-truth label stops matching what a reasonable classifier would
#     say from the pixels. Site accuracy measured at 36.8% (7/19) purely from
#     this, versus 90-100% on the plain static sites sampled the same run.
#   - gimp.org (text-issue mutation), krita.org (broken-image mutation),
#     books.toscrape.com (broken-image mutation): the specific mutation
#     produces a real DOM change but 0.0000% pixel difference on these pages
#     every time -- some interaction between the picked element and the
#     page's own CSS makes the edit invisible. Not reproducible in isolation
#     (20 attempts, 2026-08-13), so left as a labelled site+category
#     combination to avoid rather than a code fix.
#   - freepascal.org, inkscape.org, calibre-ebook.com, olive.foundation:
#     frequent Page.goto timeouts (25s) during trials -- flaky enough that a
#     meaningful fraction of any batch drawing from them silently loses
#     samples or (worse) captures a half-loaded page. freepascal.org's font
#     rendering may not have settled before capture on a slow load, which
#     would explain 4/4 misses on that site all mispredicted as
#     "font-change" in the round-2 eval.
SITES = [
    # language / framework documentation
    "https://quotes.toscrape.com/",
    "https://www.gnu.org/",
    "https://sqlite.org/index.html",
    "https://curl.se/",
    "https://nginx.org/en/",
    "https://www.rfc-editor.org/",
    "https://flask.palletsprojects.com/en/stable/",
    "https://getbootstrap.com/docs/5.3/getting-started/introduction/",
    "https://www.debian.org/",
    "https://docs.pytest.org/en/stable/",
    "https://requests.readthedocs.io/en/latest/",
    "https://www.sqlalchemy.org/",
    "https://jinja.palletsprojects.com/en/stable/",
    "https://click.palletsprojects.com/en/stable/",
    "https://werkzeug.palletsprojects.com/en/stable/",
    "https://numpy.org/doc/stable/",
    "https://pandas.pydata.org/docs/",
    "https://scipy.org/",
    "https://matplotlib.org/stable/",
    "https://scikit-learn.org/stable/",
    "https://docs.scipy.org/doc/scipy/",
    "https://pillow.readthedocs.io/en/stable/",
    "https://beautiful-soup-4.readthedocs.io/en/latest/",
    "https://urllib3.readthedocs.io/en/stable/",
    "https://docs.aiohttp.org/en/stable/",
    "https://www.uvicorn.org/",
    "https://www.starlette.io/",
    "https://typer.tiangolo.com/",
    "https://docs.pydantic.dev/latest/",
    "https://peps.python.org/",
    "https://packaging.python.org/en/latest/",
    "https://pip.pypa.io/en/stable/",
    "https://virtualenv.pypa.io/en/latest/",
    "https://setuptools.pypa.io/en/latest/",
    "https://tox.wiki/en/latest/",
    "https://mypy.readthedocs.io/en/stable/",
    "https://black.readthedocs.io/en/stable/",
    "https://flake8.pycqa.org/en/latest/",
    "https://coverage.readthedocs.io/en/latest/",
    "https://sphinx-doc.org/en/master/",
    # other language ecosystems
    "https://go.dev/",
    "https://doc.rust-lang.org/book/",
    "https://www.rust-lang.org/",
    "https://crates.io/",
    "https://kotlinlang.org/",
    "https://www.scala-lang.org/",
    "https://elixir-lang.org/",
    "https://www.erlang.org/",
    "https://clojure.org/",
    "https://www.haskell.org/",
    "https://ocaml.org/",
    "https://nim-lang.org/",
    "https://ziglang.org/",
    "https://www.lua.org/",
    "https://www.ruby-lang.org/en/",
    "https://www.php.net/",
    "https://www.perl.org/",
    "https://julialang.org/",
    "https://www.r-project.org/",
    "https://dart.dev/",
    # web platform / frontend
    "https://vitejs.dev/",
    "https://rollupjs.org/",
    "https://webpack.js.org/",
    "https://eslint.org/",
    "https://prettier.io/",
    "https://www.typescriptlang.org/",
    "https://nodejs.org/en",
    "https://deno.com/",
    "https://bun.sh/",
    "https://tailwindcss.com/",
    "https://sass-lang.com/",
    "https://lesscss.org/",
    "https://vuejs.org/",
    "https://svelte.dev/",
    "https://preactjs.com/",
    "https://lit.dev/",
    "https://emberjs.com/",
    "https://backbonejs.org/",
    "https://underscorejs.org/",
    "https://d3js.org/",
    # infrastructure / tooling
    "https://redis.io/",
    "https://www.postgresql.org/",
    "https://www.mysql.com/",
    "https://mariadb.org/",
    "https://www.mongodb.com/",
    "https://prometheus.io/",
    "https://grafana.com/",
    "https://www.nagios.org/",
    "https://www.ansible.com/",
    "https://www.terraform.io/",
    "https://www.vagrantup.com/",
    "https://kubernetes.io/",
    "https://helm.sh/",
    "https://etcd.io/",
    "https://traefik.io/",
    "https://caddyserver.com/",
    "https://httpd.apache.org/",
    "https://www.haproxy.org/",
    "https://openssl.org/",
    "https://www.wireshark.org/",
    "https://www.gnupg.org/",
    "https://git-scm.com/",
    "https://mercurial-scm.org/",
    "https://subversion.apache.org/",
    "https://cmake.org/",
    "https://www.gnu.org/software/make/",
    "https://gcc.gnu.org/",
    "https://llvm.org/",
    "https://www.qt.io/",
    "https://www.gtk.org/",
    # operating systems / distributions
    "https://www.kernel.org/",
    "https://www.freebsd.org/",
    "https://openbsd.org/",
    "https://netbsd.org/",
    "https://www.archlinux.org/",
    "https://fedoraproject.org/",
    "https://ubuntu.com/",
    "https://linuxmint.com/",
    "https://www.opensuse.org/",
    "https://alpinelinux.org/",
    "https://www.gentoo.org/",
    "https://slackware.com/",
    "https://www.centos.org/",
    "https://rockylinux.org/",
    "https://almalinux.org/",
    # standards, foundations, institutions
    "https://www.w3.org/",
    "https://www.iso.org/home.html",
    "https://www.ietf.org/",
    "https://www.iana.org/",
    "https://www.unicode.org/",
    "https://www.khronos.org/",
    "https://www.linuxfoundation.org/",
    "https://www.apache.org/",
    "https://www.eclipse.org/",
    "https://www.mozilla.org/en-US/",
    "https://www.eff.org/",
    "https://creativecommons.org/",
    "https://opensource.org/",
    "https://www.fsf.org/",
    "https://archive.org/",
    # universities and reference
    "https://www.mit.edu/",
    "https://www.stanford.edu/",
    "https://www.ox.ac.uk/",
    "https://www.cam.ac.uk/",
    "https://www.ethz.ch/en.html",
    "https://www.nasa.gov/",
    "https://www.noaa.gov/",
    "https://www.usgs.gov/",
    "https://www.census.gov/",
    "https://www.bls.gov/",
    # added 2026-08-14/15, both rounds verified to actually produce pairs
    # (not just reachable) -- see the avoid-list above for what got tried
    # and rejected instead.
    "https://ant.apache.org/",
    "https://containerd.io/",
    "https://gradle.org/",
    "https://graphql.org/",
    "https://junit.org/junit5/",
    "https://maven.apache.org/",
    "https://neovim.io/",
    "https://spring.io/",
    "https://symfony.com/",
    "https://www.docker.com/",
    "https://www.electronjs.org/",
    "https://www.jenkins.io/",
    "https://www.python.org/",
    "https://www.rabbitmq.com/",
    "https://www.vim.org/",
    "https://airflow.apache.org/",
    "https://argoproj.github.io/",
    "https://dbeaver.io/",
    "https://etcher.balena.io/",
    "https://filezilla-project.org/",
    "https://hadoop.apache.org/",
    "https://httpie.io/",
    "https://insomnia.rest/",
    "https://istio.io/",
    "https://kafka.apache.org/",
    "https://keras.io/",
    "https://linkerd.io/",
    "https://nmap.org/",
    "https://pytorch.org/",
    "https://rufus.ie/en/",
    "https://spark.apache.org/",
    "https://www.elastic.co/",
    "https://www.envoyproxy.io/",
    "https://www.freecadweb.org/",
    "https://www.metasploit.com/",
    "https://www.pgadmin.org/",
    "https://www.tensorflow.org/",
    "https://www.ventoy.net/en/index.html",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=2200)
    parser.add_argument("--seed", type=int, default=77000)
    parser.add_argument("--max-hours", type=float, default=3.0,
                        help="Stop cleanly once this much wall time has passed.")
    parser.add_argument("--out-dir", default=".visual-regression/datasets/live-training-pairs")
    parser.add_argument("--sites-file", default=None,
                        help="One URL per line, replacing the built-in list. Keeping a "
                             "batch's sites in a file, and its captures in their own "
                             "--out-dir, is what allows a later run to train on one batch, "
                             "the other, or both — merging them into a single manifest "
                             "throws that choice away.")
    args = parser.parse_args()

    global SITES
    if args.sites_file:
        raw = (ROOT / args.sites_file).read_text(encoding="utf-8")
        SITES = [ln.strip() for ln in raw.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        print(f"Loaded {len(SITES)} sites from {args.sites_file}")

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"

    # Resume rather than restart: re-running after an interruption should add to
    # the set, not overwrite hours of captures.
    records = []
    if manifest_path.is_file():
        try:
            records = json.loads(manifest_path.read_text(encoding="utf-8")).get("pairs", [])
            print(f"Resuming: {len(records)} pairs already captured.")
        except Exception:
            records = []

    rng = random.Random(args.seed + len(records))
    deadline = time.time() + args.max_hours * 3600
    start_idx = len(records)
    ok = fail = skipped = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        for i in range(args.trials):
            if time.time() > deadline:
                print(f"\nTime budget reached after {ok} new pairs.")
                break

            idx = start_idx + i
            url = rng.choice(SITES)
            category = rng.choice(CATEGORIES)
            try:
                trial = run_trial(page, url, category, rng, out_dir, idx)
                # run_trial declines rather than mislabels: no element on this
                # page suits the category, or the mutation could not produce the
                # phenomenon it is named after — layout-issue refuses an element
                # whose growth pushes nothing, since the alternative is a pair
                # labelled "layout-issue" showing no layout issue. Unpacking that
                # None raised, which the loop reported as a failed trial; it is a
                # skip, and saying so keeps the log honest about what went wrong.
                if trial is None:
                    skipped += 1
                    continue
                _result, baseline_path, current_path, mutated = trial
                records.append({
                    "baseline": str(baseline_path),
                    "current": str(current_path),
                    "label": category,
                    "url": url,
                    "mutated": mutated,
                })
                ok += 1
            except Exception as exc:
                fail += 1
                print(f"  [{idx}] FAIL {url} ({category}): {str(exc)[:110]}", flush=True)
                # A dead page can wedge the context; a fresh one costs little.
                try:
                    page.close()
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                except Exception:
                    pass
                continue

            # Rewritten every trial so an interrupted run is still usable.
            manifest_path.write_text(
                json.dumps({"pairs": records, "sites": SITES}, indent=1), encoding="utf-8"
            )

            if ok % 25 == 0:
                elapsed = time.time() - (deadline - args.max_hours * 3600)
                rate = ok / max(elapsed, 1e-6)
                print(f"  [{idx}] {ok} ok / {fail} fail  ({rate * 3600:.0f}/hr)  last={category}",
                      flush=True)

        browser.close()

    print(f"\nCaptured {ok} new pairs ({fail} failures). Total in manifest: {len(records)}")
    print(f"Manifest: {manifest_path}")

    counts = {}
    for r in records:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    print("\nlabel distribution:")
    for k in sorted(counts, key=lambda k: -counts[k]):
        print(f"  {k:<24}{counts[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
