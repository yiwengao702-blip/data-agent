/* ============================================================
   auth.js —— 登录 / 注册 页面交互逻辑
   职责：实时输入校验、密码显隐、按钮加载动效、模拟提交（前端演示，无真实后端）。
   两页共用本脚本，依据是否存在邮箱字段自动区分「注册页 / 登录页」。
   ============================================================ */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var form = $("authForm");
  if (!form) return;

  var isRegister = !!$("email"); // 含邮箱字段 => 注册页

  // ---------- 校验规则 ----------
  var rules = {
    username: function (v) { return "请输入用户名"; }, // 登录页：宽松
    email: function (v) {
      if (!v) return "请输入邮箱";
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return "邮箱格式不正确";
      return "";
    },
    password: function (v) {
      if (!v) return "请输入密码";
      if (v.length < 8) return "密码至少 8 位";
      if (!/[a-zA-Z]/.test(v) || !/[0-9]/.test(v)) return "密码需同时包含字母与数字";
      return "";
    },
    confirm: function (v) {
      var p = $("password").value;
      if (!v) return "请再次输入密码";
      if (v !== p) return "两次输入的密码不一致";
      return "";
    }
  };

  // 注册页用户名规则收紧（3-20 位字母数字下划线）
  if (isRegister) {
    rules.username = function (v) {
      if (!v) return "请输入用户名";
      if (!/^[A-Za-z0-9_]{3,20}$/.test(v)) return "用户名需为 3-20 位字母、数字或下划线";
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
    Object.keys(rules).forEach(function (name) {
      if (!validateField(name)) ok = false;
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
      } else {
        agreeBox.classList.remove("show");
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

    // 模拟后端请求（前端演示：无真实鉴权接口）
    setTimeout(function () {
      btn.classList.remove("loading");
      btn.disabled = false;
      label.textContent = original;
      if (spinner.parentNode) spinner.remove();

      // 写入演示会话标记，并重定向到控制台
      try {
        localStorage.setItem("da_session", JSON.stringify({
          user: $("username").value, ts: Date.now()
        }));
      } catch (_) { /* 忽略隐私模式等存储异常 */ }

      var success = $("authSuccess");
      success.style.background = "";
      success.style.borderColor = "";
      success.style.color = "";
      success.textContent = isRegister ? "注册成功！正在进入控制台…" : "登录成功！正在进入控制台…";
      success.classList.add("show");

      setTimeout(function () { window.location.href = "/ui/"; }, 1100);
    }, 1100);
  });
})();
