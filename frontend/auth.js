/* ============================================================
   auth.js —— 登录 / 注册 页面交互逻辑
   职责：实时输入校验、密码显隐、按钮加载动效、调用真实鉴权后端（/api/auth/*）。
   两页共用本脚本，依据是否存在邮箱字段自动区分「注册页 / 登录页」。
   ============================================================ */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var form = $("authForm");
  if (!form) return;

  // 页面识别：优先读取表单上的 data-auth-page 显式标记（register / login）。
  // 若标记缺失（例如浏览器缓存了旧版 HTML），再退回“是否含邮箱字段”的判断，
  // 避免旧缓存把注册页误判为登录页 —— 那样会走登录校验分支导致永远无法提交。
  var pageKind = (form.getAttribute("data-auth-page") || "").toLowerCase();
  var isRegister = pageKind === "register" || (pageKind !== "login" && !!$("email"));

  // ---------- 校验规则 ----------
  var rules = {
    // 登录页：用户名/邮箱只需非空即可（具体是否存在由后端统一校验），
    // 注意：这里必须依据 v 判断，不能无条件返回错误（否则登录会被永久卡死）。
    username: function (v) { return v ? "" : "请输入用户名或邮箱"; },
    email: function (v) {
      if (!v) return "请输入邮箱";
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return "邮箱格式不正确";
      return "";
    },
    password: function (v) {
      if (!v) return "请输入密码";
      // 与后端 /api/auth/register 保持一致：后端要求 >= 6 位；
      // 前端不再额外加严（如强制字母+数字），以免误拦本可注册通过的密码。
      if (v.length < 6) return "密码至少 6 位";
      return "";
    },
    confirm: function (v) {
      var p = $("password").value;
      if (!v) return "请再次输入密码";
      if (v !== p) return "两次输入的密码不一致";
      return "";
    }
  };

  // 注册页用户名规则（与后端 _USER_RE 对齐：3-32 位字母、数字或下划线）
  if (isRegister) {
    rules.username = function (v) {
      if (!v) return "请输入用户名";
      if (!/^[A-Za-z0-9_]{3,32}$/.test(v)) return "用户名需为 3-32 位字母、数字或下划线";
      return "";
    };
  }

  function setError(name, msg) {
    var box = form.querySelector('.field-error[data-for="' + name + '"]');
    var input = $(name);
    if (box) {
      box.textContent = msg || "";
      box.classList.toggle("show", !!msg);
    }
    if (input) input.classList.toggle("invalid", !!msg);
  }

  function validateField(name) {
    var el = $(name);
    var v = el ? el.value.trim() : "";
    var msg = rules[name] ? rules[name](v) : "";
    setError(name, msg);
    return !msg;
  }

  // ---------- 实时校验绑定 ----------
  Object.keys(rules).forEach(function (name) {
    var el = $(name);
    if (!el) return;
    el.addEventListener("blur", function () { validateField(name); });
    el.addEventListener("input", function () {
      var box = form.querySelector('.field-error[data-for="' + name + '"]');
      if (box && box.classList.contains("show")) {
        validateField(name); // 已有错误时随输入即时纠正
      } else {
        el.classList.remove("invalid");
      }
    });
  });

  // ---------- 密码显隐 ----------
  document.querySelectorAll(".pw-toggle").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var t = $(btn.dataset.target);
      if (!t) return;
      var show = t.type === "password";
      t.type = show ? "text" : "password";
      btn.textContent = show ? "🙈" : "👁";
    });
  });

  // ---------- 辅助链接（演示，阻止跳转） ----------
  function flashInfo(text) {
    var box = $("authSuccess");
    if (!box) return;
    box.style.background = "#eef3ff";
    box.style.borderColor = "#c9d8ff";
    box.style.color = "#2451b3";
    box.textContent = text;
    box.classList.add("show");
    setTimeout(function () { box.classList.remove("show"); }, 3200);
  }
  if ($("forgotLink")) {
    $("forgotLink").addEventListener("click", function (e) {
      e.preventDefault();
      flashInfo("演示环境：请联系管理员重置密码，或对接真实找回密码接口。");
    });
  }
  if ($("termsLink")) {
    $("termsLink").addEventListener("click", function (e) {
      e.preventDefault();
      flashInfo("演示环境：完整服务条款文本请在实际部署时补充。");
    });
  }

  // ---------- 提交 ----------
  function validateAll() {
    var ok = true;
    var firstBad = null;
    Object.keys(rules).forEach(function (name) {
      // 关键：跳过当前页面不存在的字段。
      // 登录页并没有「邮箱 / 确认密码」输入框，若仍按空值校验会永远报错，
      // 导致登录/提交被永久卡死（这是历史 bug 的根因）。
      if (!$(name)) return;
      if (!validateField(name)) {
        ok = false;
        if (!firstBad) firstBad = name;
      }
    });
    // 注册页：检查同意条款
    if (isRegister) {
      var agree = $("agree");
      var agreeBox = form.querySelector('.field-error[data-for="agree"]');
      if (!agreeBox) {
        agreeBox = document.createElement("div");
        agreeBox.className = "field-error";
        agreeBox.setAttribute("data-for", "agree");
        agreeBox.style.marginTop = "8px";
        agree.closest(".field-row").after(agreeBox);
      }
      if (!agree || !agree.checked) {
        agreeBox.textContent = "请先阅读并同意服务条款";
        agreeBox.classList.add("show");
        ok = false;
        if (!firstBad) firstBad = "agree";
      } else {
        agreeBox.classList.remove("show");
      }
    }
    if (!ok) {
      // 汇总提示 + 滚动聚焦到第一个出错项，避免用户以为“点了没反应”
      showAuthMsg("请检查标红的输入项后再提交", true);
      var target = firstBad ? $(firstBad) : null;
      if (target) {
        try { target.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (_) {}
        try { target.focus({ preventScroll: true }); } catch (_) {}
      }
    }
    return ok;
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!validateAll()) return;

    var btn = $("submitBtn");
    var label = btn.querySelector(".btn-label");
    var original = label.textContent;
    btn.classList.add("loading");
    btn.disabled = true;
    label.textContent = isRegister ? "注册中…" : "登录中…";
    var spinner = document.createElement("span");
    spinner.className = "spinner";
    btn.appendChild(spinner);

    // 调用真实鉴权后端（data-agent 的 /api/auth/*），不再模拟
    var endpoint = isRegister ? "/api/auth/register" : "/api/auth/login";
    var payload = { username: $("username").value.trim(), password: $("password").value };
    if (isRegister) payload.email = $("email").value.trim();

    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (resp) {
        // 先读文本再解析：兼容非 JSON 响应（如 404 返回的 HTML 页面），
        // 避免 resp.json() 直接抛错掩盖真实失败原因。
        return resp.text().then(function (txt) {
          var data = null;
          try { data = JSON.parse(txt); } catch (_) { data = null; }
          return { ok: resp.ok, status: resp.status, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          throw new Error(extractError(res, endpoint));
        }
        // 真实鉴权成功：保存 Token 与用户名，跳转控制台
        try {
          localStorage.setItem("da_session", JSON.stringify({
            user: res.data.user.username,
            token: res.data.token,
            ts: Date.now()
          }));
        } catch (_) { /* 忽略隐私模式等存储异常 */ }
        showAuthMsg(isRegister ? "注册成功！正在进入控制台…" : "登录成功！正在进入控制台…", false);
        setTimeout(function () { window.location.href = "/ui/"; }, 1100);
      })
      .catch(function (err) {
        var msg = (err && err.message) ? err.message : "";
        // fetch 自身失败（服务未启动 / 网络不可达 / 被中断）时给出可操作的提示
        if (!msg || (err && err.name === "TypeError")) {
          msg = "无法连接鉴权接口（" + endpoint + "），请确认 data-agent 服务已启动。";
        }
        showAuthMsg(msg, true);
      })
      .finally(function () {
        btn.classList.remove("loading");
        btn.disabled = false;
        label.textContent = original;
        if (spinner.parentNode) spinner.remove();
      });
  });

  // 从后端响应中提取可读错误文案：
  // - 兼容 FastAPI 422 的 detail 数组（校验错误）
  // - 兼容 404（接口不存在，常见于服务未更新）与纯文本响应
  function extractError(res, endpoint) {
    var d = res.data;
    if (d) {
      if (typeof d.detail === "string" && d.detail) return d.detail;
      if (Object.prototype.toString.call(d.detail) === "[object Array]" && d.detail.length) {
        return d.detail.map(function (it) {
          return (it && (it.msg || it.message)) ? (it.msg || it.message) : String(it);
        }).join("；");
      }
      if (typeof d.message === "string" && d.message) return d.message;
    }
    if (res.status === 404) {
      return "接口不存在（HTTP 404：" + endpoint + "）。请确认已启动最新版 data-agent 服务后重试。";
    }
    if (res.status === 409) {
      return "用户名或邮箱已被注册，请更换后重试，或直接前往登录。";
    }
    if (res.status === 429) {
      return "操作过于频繁，请稍后再试。";
    }
    return "请求失败（HTTP " + res.status + "），请稍后重试。";
  }

  // 结果提示：成功（蓝）/ 失败（红）共用 #authSuccess 容器
  function showAuthMsg(text, isError) {
    var box = $("authSuccess");
    if (!box) return;
    box.textContent = text;
    if (isError) {
      box.style.background = "#fdeeee";
      box.style.borderColor = "#f0caca";
      box.style.color = "#c0392b";
    } else {
      box.style.background = "";
      box.style.borderColor = "";
      box.style.color = "";
    }
    box.classList.add("show");
  }
})();
