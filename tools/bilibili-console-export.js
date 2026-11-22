// BiliBrief helper for the Bilibili page console.
// Paste this whole script on https://www.bilibili.com/ while logged in.
// Browsers hide HttpOnly cookies such as SESSDATA from document.cookie.

(() => {
  const allowedHosts = ["bilibili.com", "www.bilibili.com", "m.bilibili.com"];
  const host = location.hostname.toLowerCase();
  if (!allowedHosts.includes(host)) {
    console.error("请在 www.bilibili.com 页面运行此脚本。");
    return;
  }

  const visibleCookies = document.cookie
    .split(";")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const separator = item.indexOf("=");
      return separator < 0
        ? [item, ""]
        : [item.slice(0, separator), item.slice(separator + 1)];
    });
  const exportNames = new Set([
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "sid",
    "buvid3",
    "buvid4",
    "buvid_fp",
  ]);
  const exportedCookies = visibleCookies.filter(([name]) => exportNames.has(name));

  const lines = [
    "# Netscape HTTP Cookie File",
    "# Exported from the Bilibili page console by BiliBrief",
    "",
    ...exportedCookies.map(([name, value]) =>
      [".bilibili.com", "TRUE", "/", "TRUE", "0", name, value].join("\t"),
    ),
    "",
  ];
  const content = lines.join("\n");
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "bilibili-visible-cookies.txt";
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);

  const names = new Set(exportedCookies.map(([name]) => name));
  if (names.has("SESSDATA")) {
    console.info("已下载 Cookie 文件，包含 SESSDATA。可以交给 BiliBrief 使用。");
  } else {
    console.warn(
      "已下载可见 Cookie，但没有 SESSDATA。Chrome 的 HttpOnly 规则会隐藏它，" +
        "这个文件通常不足以读取需要登录的 B 站字幕。请使用 BiliBrief 扫码登录，" +
        "或在 DevTools 的 Application → Cookies 中手动复制 SESSDATA。",
    );
  }
})();
