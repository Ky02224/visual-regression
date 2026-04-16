(function () {
  const messages = {
    "en-US": {
      brand: "Northstar Ops",
      locale: "English (US)",
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

  if (defect) {
    document.body.classList.add(defect);
    const defectBox = document.querySelector("[data-defect-banner]");
    if (defectBox) {
      defectBox.hidden = false;
      defectBox.textContent = locale.defect + " [" + defect + "]";
    }
  }
})();
