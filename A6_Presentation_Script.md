# A6 — Presentation Script / 演讲逐字稿

**Visual Regression Workbench — Tan Kia Yen**

| Segment | Length |
|---|---|
| Part 1 — Slides (marketing + technical) | 7:00 |
| Part 2 — Demo (dashboard + code + CI) | 7:00 |
| Closing slide | 0:15 |
| **Total** | **~14:00** |

念稿速度按 140 字/分钟估算。念快了就在标 `⏸` 的地方停一拍。

---

## 录制前 checklist / Before you hit record

1. `python -m visual_regression.cli serve-dashboard --port 8130` — 确认 dashboard 起来了
2. 浏览器开三个 tab：
   - `http://127.0.0.1:8130/` （dashboard）
   - `http://127.0.0.1:8130/demo/index.html?lang=en-US` （干净的 demo 页）
   - `http://127.0.0.1:8130/demo/index.html?lang=en-US&defect=missing-cta` （带缺陷的）
3. VS Code 开好，三个文件已经在 tab 里：
   - `visual_regression/decision.py`
   - `visual_regression/ai_features.py`
   - `sdk/src/index.ts`
4. GitHub Actions 页面开一个 tab，停在一次成功的 run 上（要能看到 `Score detection rate` 那步）
5. 浏览器缩放 100%，关掉书签栏和通知
6. **先录一遍 demo**（不带声音）确认没有卡顿，再正式录

---

# PART 1 — SLIDES

## Slide 1 — Title · 0:00–0:15

> Hi, I'm Tan Kia Yen, and this is the Visual Regression Workbench — a testing platform that catches unintended changes to a website's appearance and names them. First the product pitch, then how it was built.

**中文提示：** 开场只做两件事——报名字和产品名，然后预告结构（先卖产品，后讲技术）。不要在这里解释什么是 visual regression，第 2 页会讲。语气放轻松一点，这是全片第一印象。

---

## Slide 2 — The client and the issue · 0:15–0:57

> The client is Centific — an enterprise AI data company doing multilingual datasets, AI localisation and internationalisation across more than two hundred languages, with a global expert network doing the human evaluation. ⏸
>
> Here is the problem in that line of work. Translation QA checks the string; it does not check that the string still fits. Expansion, truncation, font fallback and right-to-left mirroring break layouts that were perfectly correct in English. ⏸
>
> The cost multiplies — forty screens across twenty-five locales on two devices is two thousand rendered screens for a single release. ⏸
>
> And a pixel differ cannot help, because every localised page differs from the source by design.

**中文提示：** 这页拿分点是 "knowledge of issue / client"。三段逻辑：**翻译对了但版面坏了** → **成本按 locale 翻倍** → **像素对比在这里没用**。第三点最关键，它同时否掉了竞品，直接铺垫第 3 页。

⚠️ 左边那张卡片里的信息全部来自 Centific 官网（多语言数据、200+ 语言、expert network、Microsoft 客户）。右边 "2,000 screens" 是**举例算术，不是 Centific 的真实数字**，slide 上已经标注了 — 念的时候也说 "forty screens across twenty-five locales" 这种假设句式，不要说成"他们有两千个页面"。

---

## Slide 3 — Target market · 0:57–1:40

> So who is this for? Primarily localisation vendors and the teams they deliver into — anyone who has to sign off the same product in many locales. ⏸
>
> The niche is multi-locale verification: locale and device are part of a baseline's identity, so the Japanese page is judged against the approved Japanese page, and it self-hosts, which matters when the screens belong to an enterprise client. ⏸
>
> Today the alternatives are Percy, Chromatic and Applitools. All three are cloud-only, and all three meter by snapshot — which is the wrong pricing shape here, because a localised product multiplies snapshot count by the number of locales.

**中文提示：** 评分表问 "Niche market? Competition?"，两个都点到了。最后半句是这页的杀招——按 snapshot 收费的模式，遇到本地化业务会被 locale 数量乘一遍。说到这里可以指一下右下角深色那行。

---

## Slide 4 — Advantages · 1:40–2:18

> Four things make a team switch. ⏸
>
> It names the defect — not "2.7% of pixels changed" but which element went missing and where, so the reviewer acts without opening the page. ⏸
>
> It stays trustworthy, because structural confirmation stops dynamic content from crying wolf, and false alarms are why teams mute these suites. ⏸
>
> It compares like with like, so the Japanese page is judged against the approved Japanese page rather than the English source. And it runs on their machines with one command. ⏸
>
> Half a day of clicking becomes a short list of named defects.

**中文提示：** 这页是纯营销语言，**不要**说 DOM、siamese、SSIM 这些词。念到第一条时指右边那张 diff 截图。最后一句和第 2 页的 "half a day" 呼应，是这半段的收尾。

---

## Slide 5 — Marketing mix (7Ps) · 2:18–3:05

> The mix is aimed at that buyer. ⏸
>
> The product is a platform, and the Playwright SDK is the wedge — one line inside a suite they already run. ⏸
>
> Price is the lever: self-hosted and free, so multiplying snapshots by locale count costs nothing, which is exactly where the metered tools hurt. ⏸
>
> Place is GitHub and a Docker image, so adopting it needs no procurement. Promotion is developer-led — the ablation write-up is the lead content, the re-runnable benchmark is the proof. ⏸
>
> People is one maintainer, so the docs and decision records carry first-line support. Process is fifteen minutes to a first result. Evidence is a public CI badge and an HTML report for every run.

**中文提示：** 评分表写了 **"don't just list"**，所以每个 P 后面都必须跟一句"为什么这样定"。Price 那条最重要——它直接回应第 3 页竞品"按 snapshot × locale"的收费问题。这页最长，如果超时，People / Process / Evidence 三个可以只念名字加半句。

---

## Slide 6 — Divider · 3:05–3:15

> That was the pitch. The rest is for a technical audience: what it is made of, the code that does the work, and the evidence that it works.

**中文提示：** ⚠️ 换观众了。评分表把两段的观众定得完全不同，这里**换个语气**——前面是在卖东西，后面是在跟工程师说话。停顿一秒再继续。

---

## Slide 7 — Technologies used · 3:15–3:55

> Every technology here answers a requirement. ⏸
>
> Playwright, because capture must be repeatable across three engines and must pin locale, timezone and device — a capture that drifts makes every later comparison meaningless. ⏸
>
> OpenCV for detection, because that half must be deterministic and inspectable, and the answer needs to be a bounded region. ⏸
>
> A ResNet50 siamese head, because the task is literally comparing two images, and pre-training makes it trainable on a labelled set this size. ⏸
>
> And Docker, because Chromium renders text differently on every platform — so baselines are captured inside the project's own image.

**中文提示：** 评分表要的是 "with appropriate justification for the requirements"——所以句式一律是 **"X，because 需求 Y"**，不要只报技术名。FastAPI 和 SQLite 那两格不用念，留给评分者自己看。

---

## Slide 8 — Development process · 3:55–4:35

> Three things about the process. ⏸
>
> Anything that would look arbitrary later is written down as a decision record — why detection and classification are separate metrics, why baselines are committed but models are not. ⏸
>
> The DOM capture script lives on the server and the SDK fetches it, so the two can never drift. ⏸
>
> And the ablation drove real code changes: it exposed four inference paths zero-padding the pixel columns, meaning the model was trained on evidence it never received in production. ⏸
>
> Around eleven hundred tests and a benchmark that fails on one miss gate all of it.

**中文提示：** 这页对应 "innovative use of technologies"。第三条（ablation 反过来改代码）是最能体现工程判断的，念的时候慢一点。

---

## Slide 9 — The code (decision + SDK) · 4:35–5:15

> Here is what separates this from a pixel differ. ⏸
>
> On the left, the decision function. A CNN score is a guess, so it is gated behind pixel corroboration — otherwise developers get nagged by false failures and stop trusting the build. But a DOM-diff verdict is not a guess, so it bypasses that gate. Without this line, a removed element covering very few pixels silently passes. ⏸
>
> On the right is the whole client-side integration: one call, uploading the DOM alongside the screenshot. Image-only would leave structural comparison nothing to work with.

**中文提示：** 念到 "bypasses that gate" 时用鼠标圈一下橙色那两行 `passed = not (meaningful and (pixel_fail or dom_confirmed))`。这是评分表 "demonstrate the actual code" 的第一个证据点。

---

## Slide 10 — The DOM engine · 5:15–5:55

> This is the function the ablation points at. It compares real element geometry, tags, fonts and colours from two page loads, so it generalises to a site it has never seen — no training data needed. ⏸
>
> The ordering is the interesting part. Scanning in document order picked up whichever side effect came first, not the cause — removing an image reflows everything below it. So elements are bucketed, then resolved by priority, with identity-less "missing" last because it is the noisiest verdict. ⏸
>
> And the second return value is the evidence sentence printed in the report — a claim the reviewer can check.

**中文提示：** 这页是技术段的重点。"no training data needed" 和 "evidence sentence" 是两个卖点，都要念清楚。底下那句 "Remove this function and the same model scores 38.7% instead of 94.8%" 不用念，让它替你说话，然后直接翻页。

---

## Slide 11 — Evidence · 5:55–6:35

> Detection and classification are scored separately, because they fail differently. ⏸
>
> Detection: eighty-one of eighty-one injected defects caught, zero false alarms on nine clean controls. Classification: 94.8% over five hundred trials on real pages, confidence interval 92.85 to 96.75. ⏸
>
> The ablation shows where that comes from — removing either feature group moves accuracy under a point, but removing the DOM engine drops it to 38.7, with colour, text and font at zero recall. The structural comparison is the contribution, not the network. ⏸
>
> Weakest class is missing-element at 87.7%, and that is where the remaining work is.

**中文提示：** 最后那句主动认弱点，不要跳过——评分者最容易问的就是"哪里不行"，你先说了就没得问。

---

## Slide 12 — Demo handoff · 6:35–6:45

> Now let me show you the tool doing the client's Thursday, and then the code and the CI gate behind it.

**中文提示：** 说完立刻切屏，不要停顿。

---

# PART 2 — DEMO（7 分钟）

镜头切到浏览器。下面每一段的斜体是要说的话，**粗体**是要做的动作。

## ① Dashboard tour · 0:00–0:45

**动作：** 打开 `http://127.0.0.1:8130/`，停在 runs 列表。慢慢滚一遍，然后点一次 status filter。

> *This is the dashboard the client's QA engineer opens on a Thursday. Every comparison the system has run is here — with its status, the severity, the browser, the device and the language it was captured in. They can filter down to just the failures, or just one locale, instead of reading through a wall of screenshots.*

## ② Create a baseline · 0:45–1:45

**动作：** 走 create-baseline 表单，URL 填 `http://127.0.0.1:8130/demo/index.html?lang=en-US`，语言选 en-US，device 选 desktop，提交。等它跑完，展开 baseline 的 metadata。

> *First they need a reference. I give it a URL and pin the language and the device — and those two are not just metadata, they are part of this baseline's identity. The same page in Malay is a separate baseline, not a variation of this one. That is the difference that stops a multi-language site from producing constant false failures.*

## ③ Run the comparison · 1:45–2:45

**动作：** 用 run-compare 表单，对同一个 baseline 跑 `...&defect=missing-cta`。等结果出来，指着 FAIL。

> *Now imagine a developer ships a change. I'm loading the same page with a defect injected — the call-to-action button is gone. I run it against the baseline we just captured. ⏸ It fails. Note that nothing about this required a human to look at anything yet.*

## ④ Read the verdict · 2:45–4:00

**动作：** 进 run detail。依次展示：side-by-side → slider / flash toggle → diff overlay → severity → AI label → DOM evidence 那句话。

> *This is the part that matters. Side by side, with a slider to wipe between them, and the highlighted overlay showing where the difference is. ⏸*
>
> *But the important thing is here: the change is labelled `missing-element`, and underneath it there is a sentence generated from the two DOM snapshots — which element, at which coordinates, and what happened to it. That is a claim the engineer can go and check against the page. It is not a confidence score. This is what the competitors do not give you.*

## ⑤ Ignore region, then approve · 4:00–5:00

**动作：** 打开 ignore-region 编辑器，在动态区块上拖一个框，保存，重跑同一个 compare，展示这次 PASS。然后点 Approve，展示 decision history 和 report.html。

> *Real pages have content that changes on purpose — a live counter, a rotating promo. The reviewer drags a box over it once, and that region stops counting. ⏸ Re-run, and it passes. ⏸*
>
> *And when a change is intended, they approve it — which writes back into the report and into the decision history, so there is a record of who accepted what and when.*

## ⑥ The code and the CI gate · 5:00–7:00

**动作：** 切到 VS Code。按顺序翻三个文件，每个停 30 秒左右。

**(a) `visual_regression/decision.py` → `decide_pass_fail`，滚到 hybrid 分支**

> *This is the decision function from the slide, in place. The comment explains the trade-off: the CNN's score is gated behind pixel corroboration so developers don't get false failures — but a DOM-confirmed verdict skips that gate, because it isn't a guess.*

**(b) `visual_regression/ai_features.py` → `diagnose_from_dom_diff`，滚到底部那串 `if` 阶梯**

> *And this is the function the ablation identified as the contribution. Every baseline element goes into a bucket, and the buckets are resolved by priority rather than by document order. Each branch returns two things — the label, and the human-readable evidence sentence you saw in the report.*

**(c) `sdk/src/index.ts` → `captureDom`**

> *The SDK fetches the capture script from the server rather than duplicating it, so the client and the server can never disagree about the shape of a snapshot. If the server is too old to serve it, the screenshot comparison still runs.*

**动作：** 切到 GitHub Actions 那个 tab，展开 `Score detection rate` 这一步的日志。

> *Finally — none of these numbers are measured once by hand. This is the CI job. It captures baselines inside the project's Docker image, runs every injected defect against them, and exits non-zero on a single miss or a single false alarm. So the 81 out of 81 on the results slide is enforced on every push, not quoted from a good day.*

**动作：** 切回 slide 13。

---

## Slide 13 — Close · 0:15

> To close: the buyer ships weekly, must self-host, and serves more than one language. The edge is that it names the defect instead of reporting a percentage. The proof is 81 of 81 detected and 94.8% named correctly, re-measured on every push. Thank you.

---

## 备用：可能被问到的问题

**"为什么不用现成的 Percy？"**
> Percy is cloud-only and meters by snapshot. For a localisation business that pricing shape is the wrong one — snapshot count multiplies by locale count. And Percy reports a pixel difference against a baseline; every localised page differs from the source by design, so that signal is close to useless without something that says what changed.

**"94.8% 够高吗？"**
> On six classes, chance is under 17%. The more useful comparison is the ablation: the same model without the DOM engine scores 38.7%. And detection — the part that decides whether a build fails — is exact at 81 out of 81.

**"AI 挂了怎么办？"**
> The tool degrades to pixel comparison and records `decision_source: pixel-fallback-no-model`. It stops naming changes; it does not stop detecting them. CI actually runs on that path deliberately, so the detection gate can never be blocked by model distribution.

**"数据集是自己造的吗，会不会过拟合？"**
> Detection is scored on injected defects in the demo portal, with ground truth taken from the injected mode rather than the model's output. Classification is scored on real third-party pages with injected DOM mutations — ten seeds, fifty trials each. The weakest class is missing-element at 87.7%, and I report it rather than pooling it away.

**"Centific 的数字是哪来的？"**
> The company description is from Centific's published material — multilingual data, 200-plus languages, the expert network, enterprise customers. The 2,000-screen figure is illustrative arithmetic to show how verification cost scales with locale count; it is labelled as such on the slide.

**"这个工具能处理 RTL 或者中日韩字体吗？"**
> Capture pins locale, timezone and device, so an Arabic or Japanese page is captured and compared as its own baseline. The DOM diff reads font family and computed geometry, so a font fallback or a text overflow is detectable structurally rather than as a blur of changed pixels. Fonts do have to be present in the capture image — that is one reason baselines are captured inside the project's Docker image.
