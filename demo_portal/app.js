(function () {
  const messages = {
    "en-US": {
      brand: "Northstar Ops",
      locale: "English (US)",
      dashboardBody: "Visual baseline health, browser matrix status and reviewer queue for the next deployment window.",
      homeTitle: "Operations control in one visual workspace",
      homeBody: "Monitor releases, UI health, deployment risk and manual approvals across all customer touchpoints.",
      loginTitle: "Sign in to continue",
      loginBody: "Use your company identity to access release readiness and regression approvals.",
      dashboardTitle: "Release Readiness Dashboard",
      users: "Active Users",
      incidents: "Open Incidents",
      stability: "UI Stability",
      approvals: "Pending Approvals",
      defect: "Regression simulation enabled",
      navHome: "Executive Home",
      navDashboard: "Release Dashboard",
      navReports: "Approval Reports",
      email: "Work Email",
      password: "Password",
      role: "Region",
      signIn: "Sign In",
      requestAccess: "Request Access",
    },
    "ms-MY": {
      brand: "Northstar Ops",
      locale: "Bahasa Melayu",
      dashboardBody: "Status kesihatan visual baseline, matriks pelayar dan barisan semakan untuk tetingkap deployment seterusnya.",
      homeTitle: "Pusat operasi dalam satu ruang visual",
      homeBody: "Pantau release, kestabilan UI, risiko deployment dan kelulusan manual merentas semua touchpoint pelanggan.",
      loginTitle: "Log masuk untuk teruskan",
      loginBody: "Gunakan identiti syarikat untuk akses kesiapsiagaan release dan kelulusan regression.",
      dashboardTitle: "Papan Pemuka Kesiapsiagaan Release",
      users: "Pengguna Aktif",
      incidents: "Insiden Terbuka",
      stability: "Kestabilan UI",
      approvals: "Kelulusan Tertunda",
      defect: "Simulasi regression diaktifkan",
      navHome: "Laman Utama Eksekutif",
      navDashboard: "Papan Pemuka Release",
      navReports: "Laporan Kelulusan",
      email: "E-mel Kerja",
      password: "Kata Laluan",
      role: "Rantau",
      signIn: "Log Masuk",
      requestAccess: "Mohon Akses",
    },
    "zh-CN": {
      brand: "Northstar Ops",
      locale: "简体中文",
      dashboardBody: "视觉基线健康状态、浏览器矩阵状态及下次部署窗口的审核队列。",
      homeTitle: "在一个可视化工作台管理运营",
      homeBody: "统一查看发布状态、UI 健康度、部署风险和人工审批结果。",
      loginTitle: "登录以继续",
      loginBody: "使用企业身份进入发布准备和回归审批中心。",
      dashboardTitle: "发布准备仪表盘",
      users: "活跃用户",
      incidents: "未解决事件",
      stability: "UI 稳定度",
      approvals: "待审批项",
      defect: "已启用回归缺陷模拟",
      navHome: "高层首页",
      navDashboard: "发布仪表盘",
      navReports: "审批报告",
      email: "工作邮箱",
      password: "密码",
      role: "区域",
      signIn: "登录",
      requestAccess: "申请访问",
    },
  };

  const params = new URLSearchParams(window.location.search);
  const lang = params.get("lang") || "en-US";
  const defect = params.get("defect") || "";
  const locale = messages[lang] || messages["en-US"];

  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const key = node.getAttribute("data-i18n");
    if (locale[key]) {
      node.textContent = locale[key];
    }
  });

  const localeBadge = document.querySelector("[data-locale-badge]");
  if (localeBadge) {
    localeBadge.textContent = locale.locale;
  }

  document.querySelectorAll('a[href]').forEach(function(link) {
    var href = link.getAttribute('href');
    if (href && !href.startsWith('http') && href.indexOf('?') === -1) {
      link.setAttribute('href', href + '?lang=' + lang);
    }
  });

  // ?dynamic=1 turns on the things a visual test should learn to ignore: a
  // rotating ad creative and a wall clock. Both differ on every capture, which
  // is what separates them from a regression that renders the same each run.
  if (params.get("dynamic")) {
    const strip = document.querySelector("[data-dynamic-strip]");
    const adSlot = document.querySelector("[data-ad-slot]");
    const clock = document.querySelector("[data-clock]");
    if (strip) {
      strip.hidden = false;
    }
    if (adSlot) {
      const creatives = [
        { text: "Ship faster with Northstar Cloud", color: "#c2410c" },
        { text: "Try Northstar AI — 30 days free", color: "#1d4ed8" },
        { text: "Webinar: Release engineering at scale", color: "#15803d" },
        { text: "Now hiring: platform engineers", color: "#7e22ce" },
        { text: "Case study: 40% fewer rollbacks", color: "#b91c1c" },
      ];
      const pick = creatives[Math.floor(Math.random() * creatives.length)];
      adSlot.textContent = pick.text;
      adSlot.style.background = pick.color;
    }
    if (clock) {
      const render = function () {
        clock.textContent = new Date().toLocaleTimeString(lang, { hour12: false });
      };
      render();
      setInterval(render, 1000);
    }
  }

  if (defect) {
    document.body.classList.add(defect);
    const defectBox = document.querySelector("[data-defect-banner]");
    if (defectBox) {
      defectBox.hidden = false;
      defectBox.textContent = locale.defect + " [" + defect + "]";
    }
  }
})();
