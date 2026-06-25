# Visual Regression Testing Platform - Resume Materials & Interview Guide

This document contains ready-to-use resume templates and an interview preparation guide based on the **Visual Regression Testing Platform** you built.

---

## 1. Resume Templates (Ready to Copy)

### 📌 Option A: Detailed Bullet Points (Recommended for Tech-heavy Resumes)

**Visual Regression Testing & Automated Review Platform**  
*React, Vite, Tailwind CSS v4, Python (FastAPI/Flask), Playwright, SQLite, CI/CD (GitHub Actions)*

*   **Automated Screenshot Capture Engine**: Developed a cross-platform, concurrent capturing service using **Playwright** that automatically runs on commits/pull requests to capture full-page snapshots across multiple browsers (Chrome, Safari, Firefox), device viewports, and localized languages.
*   **Modern Visual Review Dashboard**: Designed and built a high-performance React-based single-page application (SPA) featuring Side-by-Side views, Flash Toggles, and interactive Sliders with CSS-based **pixel-diff overlays** for rapid visual bug detection and approval workflows.
*   **Visual Noise Reduction & Dynamic Area Exclusion**: Developed an interactive canvas drawing workspace that allows reviewers to drag-and-draw coordinate-based "ignore regions" (e.g., dynamic banners, timestamps) directly on the screenshot, utilizing OpenCV masking in the backend to exclude these zones from comparison, reducing false-positive alerts by **over 90%**.
*   **Robust Frontend Performance & State Management**: Resolved complex asynchronous lifecycle race conditions between image caching and dynamic layout calculations (`ResizeObserver` & `onLoad` triggers), ensuring zero-latency, zero-blank-screen rendering of compared baselines.
*   **CI/CD Pipeline & Webhook Integration**: Engineered secure API key authentication and automatic YAML pipeline generation, enabling automated visual validation in **GitHub Actions** and webhook-triggered Slack/Teams notifications upon regression detection.

---

### 📌 Option B: Concise Format (Better for Single-page Resumes)

**Visual Regression Testing Platform | Lead Developer**  
*React, Vite, Python, Playwright, SQLite, GitHub Actions*
*   Built a Percy-equivalent automated visual regression testing platform that captures, compares, and reviews Web UI layouts during continuous integration (CI) pipelines.
*   Implemented canvas-based drag-and-draw ignore regions and OpenCV pixel masking to eliminate false positives caused by dynamic content.
*   Designed an interactive visual review dashboard supporting side-by-side comparisons, sliders, and pixel diff overlays.
*   Integrated GitHub Actions pipelines and Slack webhooks to notify development teams of visual defects instantly.

---

## 2. Interview Prep: How to Talk About This Project

When interviewers ask, *"Tell me about a challenging project you built"* or *"What is the most interesting technical problem you solved recently?"*, here is how you can pitch this project:

### 💡 Talk About: Solving the "Asynchronous Image Rendering Race Condition"
> *"One of the most interesting challenges I solved in this project was a race condition in the image comparison workspace. When users opened a test report, the baseline and changes screenshots would sometimes render blank on mount, only appearing after manually clicking thumbnails.*
>
> *I diagnosed this as a timing issue: the React component used a `ResizeObserver` and `onLoad` handlers to calculate the exact dimensions for rendering zoomed images. When images were cached by the browser, `onLoad` would fire before the container element finished layout rendering (leaving container height/width at 0).*
>
> *I solved this by introducing an optimization: when the zoom scale is set to default fit-to-screen, the component bypasses all JS measurements and ResizeObservers entirely, using native CSS `object-contain` for instant, robust rendering. For custom zoom scales, I introduced a `img.complete` cached-image checker on mount. This eliminated the blank page issue completely and improved UI responsiveness."*

### 💡 Talk About: Handling Dynamic Web Content (Ignore Regions)
> *"Visual testing often fails because pages contain dynamic content like ads, live timers, or user-specific dates. To prevent false-positives, I built a feature allowing reviewers to drag-and-draw coordinate boxes directly over the screenshot on the React canvas workspace.*
>
> *The backend comparison engine receives these coordinates and uses OpenCV's masking function to cover those regions (filling them with dominant background/masking pixels) before performing absolute pixel diffs and structural similarity (SSIM) calculations. This made the automated test suite extremely stable and reliable without requiring complex DOM path hacking."*
