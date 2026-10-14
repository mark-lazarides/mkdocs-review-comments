/* mkdocs-review-comments: comment buttons, inlined into review builds only.
   Posts to the API run by `rc serve`, which writes the tagged comment line
   into the markdown source; the live reload then rebuilds the page. */
(function () {
  var cfg = window.RC;
  if (!cfg || !cfg.page) return;

  function store(k, v) { try { localStorage.setItem("rc." + k, v); } catch (e) {} }
  function load(k) { try { return localStorage.getItem("rc." + k) || ""; } catch (e) { return ""; } }

  var panel = null;
  function closePanel() { if (panel) { panel.remove(); panel = null; } }

  function openPanel(title, mode, onSubmit) {
    closePanel();
    panel = document.createElement("div");
    panel.className = "rc-panel";
    panel.innerHTML =
      '<div class="rc-panel-title"></div>' +
      '<div class="rc-panel-row"><input class="rc-author" placeholder="Name" /> ' +
      '<input class="rc-initials" placeholder="Initials" maxlength="3" /></div>' +
      '<textarea class="rc-text" rows="4" placeholder="Comment (one paragraph; markdown links are fine)"></textarea>' +
      '<div class="rc-panel-row"><button type="button" class="rc-send">Save</button> ' +
      '<button type="button" class="rc-cancel">Cancel</button> <span class="rc-status"></span></div>';
    panel.querySelector(".rc-panel-title").textContent = title;
    var author = panel.querySelector(".rc-author"), initials = panel.querySelector(".rc-initials");
    var text = panel.querySelector(".rc-text"), status = panel.querySelector(".rc-status");
    author.value = load("author"); initials.value = load("initials");
    if (mode === "resolve") initials.disabled = true;
    panel.querySelector(".rc-cancel").onclick = closePanel;
    panel.querySelector(".rc-send").onclick = function () {
      if (!author.value.trim() || !text.value.trim() || (mode !== "resolve" && !initials.value.trim())) {
        status.textContent = "name, initials and text are all needed"; return;
      }
      store("author", author.value.trim()); store("initials", initials.value.trim().toUpperCase());
      status.textContent = "saving…";
      onSubmit({ author: author.value.trim(), initials: initials.value.trim().toUpperCase(), text: text.value.trim() })
        .then(function (r) {
          status.textContent = "saved " + r.id + ", rebuilding…";
          setTimeout(function () { location.reload(); }, 2500);
        })
        .catch(function (e) { status.textContent = "failed: " + e; });
    };
    document.body.appendChild(panel);
    text.focus();
  }

  function post(body) {
    body.page = cfg.page;
    return fetch(cfg.api + "/api/comment", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw (j.error || r.status); return j; });
    }).catch(function (e) {
      throw (e && e.message === "Failed to fetch") ? "comment API not running (start `rc serve`)" : e;
    });
  }

  function button(label, title, cls) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "rc-btn " + (cls || ""); b.textContent = label; b.title = title;
    return b;
  }

  var content = document.querySelector(".md-content") || document.querySelector("main") || document.body;

  // "+" on every heading: a new root comment at the end of that section.
  content.querySelectorAll("h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]").forEach(function (h) {
    var label = h.textContent.replace(/[¶#]+$/, "").trim();
    var b = button("+", "Add a review comment to this section");
    b.onclick = function (ev) {
      ev.preventDefault();
      openPanel("Comment on: " + label, "root", function (f) {
        return post({ anchor: h.id, author: f.author, initials: f.initials, text: f.text });
      });
    };
    h.appendChild(b);
  });

  // Reply on every thread, Resolve on open ones.
  content.querySelectorAll(".rc-thread").forEach(function (t) {
    var id = (t.id || "").replace(/^rc-/, "");
    if (!id) return;
    var bar = document.createElement("span"); bar.className = "rc-actions"; // span: the thread is a <p>
    var reply = button("Reply", "Reply in this thread");
    reply.onclick = function () {
      openPanel("Reply to " + id, "reply", function (f) {
        return post({ re: id, author: f.author, initials: f.initials, text: f.text });
      });
    };
    bar.appendChild(reply);
    if (!t.classList.contains("rc-resolved")) {
      var res = button("Resolve", "Mark this thread resolved", "rc-btn-resolve");
      res.onclick = function () {
        openPanel("Resolve " + id, "resolve", function (f) {
          return post({ resolve: id, author: f.author, text: f.text });
        });
      };
      bar.appendChild(res);
    }
    t.appendChild(bar);
  });
})();
